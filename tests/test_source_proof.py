"""Actual Git DAG + disposable ledger: failed source cannot hide behind a task ID."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('KAIZEN_TEST_PLUGIN_ROOT', Path(__file__).resolve().parents[1]))


class SourceProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.git('init', '-q', '-b', 'main')
        for k, v in [('user.name', 'fixture'), ('user.email', 'fixture@example.invalid'), ('commit.gpgsign', 'false')]:
            self.git('config', k, v)
        (self.project / '.git/info/exclude').write_text('.kaizen/\nknowledge/\n')
        self.base = self.commit('baseline', {'go/owner': 'safe\n', 'sql/schema': 'base\n'})
        self.held = self.commit('known failure', {'go/owner': 'known bug\n'})
        self.descendant = self.commit('T3 index on held source', {'sql/schema': 'base\nrides index\n'})
        self.git('switch', '-q', '--detach', self.held)
        self.repair = self.commit('repair', {'go/owner': 'safe repaired\n', 'sql/schema': 'base\nowner index\n'})
        self.later = self.commit('T3 same SQL file after accepted repair', {'sql/schema': 'base\nowner index\nrides index\n'})
        self.git('switch', '-q', '--detach', self.base)
        self.independent = self.commit('independent feature', {'go/other': 'unrelated\n'})
        self.equal = self.git('commit-tree', self.git('rev-parse', self.held + '^{tree}'), '-p', self.base,
                              '-m', 'T5 same source, different commit')
        self.git('switch', '-q', '--detach', self.held)
        self.t6 = self.commit('T6 driver on held source', {'go/driver': 'interpolate existing driver\n'})
        self.db = self.root / 'team.sqlite3'
        self.plugin = self.root / 'plugin'
        (self.plugin / 'scripts').mkdir(parents=True)
        (self.plugin / 'scripts/experiment.sh').write_text('touch invoked\n')
        (self.project / '.kaizen').mkdir()
        (self.project / '.kaizen/config.sh').write_text('# offline fixture\n')
        (self.project / '.kaizen/stable-bundle.json').write_text(json.dumps(dict(trees={'go': None, 'sql': None, 'etc': None})))
        knowledge = self.project / 'knowledge'
        (knowledge / 'patterns').mkdir(parents=True)
        (knowledge / 'match.py').write_text('# fixture\n')
        self.config = self.root / 'competition.json'
        self.config.write_text(json.dumps(dict(environment='competition', project=str(self.project),
            plugin_root=str(self.plugin), knowledge_dir=str(knowledge), resources=['fixture:host'],
            enabled=True, confirmed_rules=True, confirmed_recovery_drill=True)))
        self.cli('env-register', '--agent', 'fixture', '--config', str(self.config), '--reason', 'offline fixture')
        self.token = self.cli('env-acquire', '--agent', 'integrator', '--purpose', 'test')['token']
        self.records = 0

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args], text=True, stderr=subprocess.PIPE).strip()

    def commit(self, message, files):
        for name, content in files.items():
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/team/team.py'), '--db', str(self.db), *args],
                                capture_output=True, text=True)
        if not ok:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def submit(self, title, source, related=None, review='auto'):
        task = self.cli('task-create', '--title', title, '--evidence', 'fixture', *(['--related', related] if related else []))['id']
        self.cli('task-claim', '--id', task, '--agent', 'worker')
        self.ready(task, source, review=review)
        return task

    def ready(self, task, source, review='auto', extra=()):
        return self.cli('task-ready', '--id', task, '--agent', 'worker', '--base', self.base,
                        '--sha', source, '--review', review, '--reason', 'fixture', *extra)

    def hold(self):
        task = self.submit('T1 known failure', self.held)
        self.cli('task-quality-hold', '--id', task, '--agent', 'integrator', '--token', self.token,
                 '--category', 'correctness', '--evidence', 'fixture CODE26', '--reason', 'repair needed')
        return task

    def resubmit(self, task, source):
        self.cli('task-resume', '--id', task, '--agent', 'worker', '--reason', 'repair')
        self.ready(task, source)

    def record(self, source, **changes):
        self.records += 1
        folder = self.project / '.kaizen/experiments' / str(self.records)
        folder.mkdir(parents=True)
        instant = datetime.datetime.now(datetime.timezone.utc).isoformat()
        data = dict(finalDecision='promote', candidateRevision=source, stableAfter=source,
                    manifest=dict(candidateRevision=source), closedAt=instant,
                    ruleDecision=dict(quality=dict(status='pass'), qualityBlockPromotion=False),
                    samples=[dict(label='candidate-1', deployedRevision=source, finishedAt=instant, **{'pass': True})])
        data.update(changes)
        path = folder / 'record.json'
        path.write_text(json.dumps(data))
        (folder / 'manifest.json').write_text(json.dumps(data['manifest']))
        for index, sample in enumerate(data['samples']):
            (folder / ('bench-candidate-' + str(index) + '.json')).write_text(json.dumps(sample))
        (self.project / '.kaizen/state.env').write_text('CURRENT_EXPERIMENT=' + str(self.records) + '\n')
        return path

    def finish(self, task, source=None, record=None, ok=True, extra=()):
        if source and not record:
            record = self.record(source)
        args = ['task-finish', '--id', task, '--agent', 'integrator', '--result', 'ACCEPTED', '--reason', 'test']
        if record:
            args += ['--record', str(record), '--tested-sha', source]
        return self.cli(*args, *extra, ok=ok)

    def target(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/team/target.py'), '--db', str(self.db),
            '--config', str(self.config), '--agent', 'integrator', '--token', self.token, 'experiment', *args],
            capture_output=True, text=True)

    def test_t3_t5_t6_inherit_another_tasks_open_hold(self):
        self.hold()
        for title, source in [('T3 indexes', self.descendant), ('T5 copied tree', self.equal), ('T6 driver', self.t6)]:
            task = self.submit(title, source)
            self.assertIn('inherits unresolved quality hold', self.finish(task, source, ok=False))
        self.assertEqual(self.cli('status')['quality_holds'][0]['state'], 'OPEN')

    def test_every_adoption_requires_source_bound_record(self):
        task = self.submit('ordinary candidate', self.independent)
        self.assertIn('--record', self.finish(task, ok=False))
        self.assertEqual(self.finish(task, self.independent)['status'], 'ACCEPTED')

    def test_own_repair_cannot_use_unrelated_tested_source(self):
        task = self.hold()
        self.resubmit(task, self.repair)
        self.assertIn('does not preserve submitted', self.finish(task, self.independent, ok=False))
        self.assertEqual(self.cli('status')['quality_holds'][0]['state'], 'RETEST_PENDING')

    def test_plain_revert_of_submitted_repair_is_rejected_despite_ancestry(self):
        task = self.hold()
        self.resubmit(task, self.repair)
        self.git('switch', '-q', '--detach', self.repair)
        reverted = self.commit('revert the runtime repair', {'go/owner': 'known bug\n'})
        self.assertEqual(self.git('merge-base', self.repair, reverted), self.repair)
        self.assertIn('does not preserve submitted', self.finish(task, reverted, ok=False))

    def test_nonoverlapping_cherrypick_and_same_deployable_content_pass(self):
        task = self.submit('independent change', self.independent)
        self.git('switch', '-q', '--detach', self.base)
        self.commit('other nonoverlapping file', {'go/additional': 'extra\n'})
        self.git('cherry-pick', self.independent)
        cherry = self.git('rev-parse', 'HEAD')
        self.assertNotEqual(cherry, self.independent)
        self.assertEqual(self.finish(task, cherry)['status'], 'ACCEPTED')
        task = self.submit('same deployable content', self.independent)
        self.git('switch', '-q', '--detach', self.independent)
        metadata = self.commit('metadata only', {'README.md': 'not deployed\n'})
        self.assertEqual(self.finish(task, metadata)['status'], 'ACCEPTED')

    def test_overlapping_composition_requires_actual_integrated_resubmission(self):
        task = self.submit('initial source', self.independent)
        self.git('switch', '-q', '--detach', self.independent)
        integrated = self.commit('same file further edited', {'go/other': 'unrelated plus another change\n'})
        self.assertIn('resubmit the actual integrated SHA', self.finish(task, integrated, ok=False))
        self.cli('task-finish', '--id', task, '--agent', 'integrator', '--result', 'NEEDS_MEASUREMENT', '--reason', 'resubmit composition')
        self.resubmit(task, integrated)
        self.assertEqual(self.finish(task, integrated)['status'], 'ACCEPTED')

    def test_repair_and_fresh_retest_clear_hold_but_preserve_failure(self):
        task = self.hold()
        self.resubmit(task, self.repair)
        stale = self.record(self.repair, samples=[dict(label='candidate', deployedRevision=self.repair,
                           finishedAt='2020-01-01T00:00:00Z', **{'pass': True})])
        self.assertIn('fresh candidate samples', self.finish(task, self.repair, stale, ok=False))
        self.assertEqual(self.finish(task, self.repair)['status'], 'ACCEPTED')
        hold = self.cli('status')['quality_holds'][0]
        self.assertEqual((hold['state'], hold['source_sha'], hold['repair_sha']), ('RESOLVED', self.held, self.repair))

    def test_adopted_repair_allows_later_index_in_same_file(self):
        task = self.hold()
        self.resubmit(task, self.repair)
        self.finish(task, self.repair)
        later = self.submit('T3 after accepted repaired stable', self.later)
        self.assertEqual(self.finish(later, self.later)['status'], 'ACCEPTED')

    def test_closed_history_is_retained_without_inventing_a_reopen_workflow(self):
        task = self.hold()
        self.cli('task-finish', '--id', task, '--agent', 'integrator', '--result', 'REJECTED', '--reason', 'budget')
        related = self.submit('explicit follow-up investigation', self.repair, related=task)
        self.assertEqual(self.finish(related, self.repair)['status'], 'ACCEPTED')
        status = self.cli('status')
        self.assertEqual(status['quality_holds'][0]['state'], 'ABANDONED')
        self.assertEqual(status['quality_holds'][0]['source_sha'], self.held)
        self.assertEqual(next(t['status'] for t in status['tasks'] if t['id'] == task), 'REJECTED')

    def test_unchanged_bad_source_cannot_reroll_clean_samples(self):
        task = self.hold()
        self.resubmit(task, self.held)
        self.assertIn('changed repair content', self.finish(task, self.held, ok=False))

    def test_official_target_blocks_before_script_but_allows_inconclusive_close(self):
        self.hold()
        self.git('switch', '-q', '--detach', self.t6)
        result = self.target('record', '--override', 'promote', 'fixture')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inherits unresolved quality hold', result.stderr)
        self.assertFalse((self.project / 'invoked').exists())
        result = self.target('record', '--override', 'inconclusive', 'fixture recovery')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.project / 'invoked').exists())

    def test_reason_words_and_duplicate_override_cannot_bypass_promotion_guard(self):
        self.hold()
        self.git('switch', '-q', '--detach', self.t6)
        for args in [('record', 'reason', '--override', 'inconclusive'),
                     ('record', '--override', 'promote', 'reason', '--override', 'reject'),
                     ('record', '--override', 'inconclusive', '--override', 'promote', 'reason')]:
            with self.subTest(args=args):
                result = self.target(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('inherits unresolved quality hold', result.stderr)
                self.assertFalse((self.project / 'invoked').exists())
        result = self.target('record', '--override', 'promote', '--override', 'reject', 'explicit close')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_other_task_resolves_inherited_pending_hold_only_with_the_measured_repair(self):
        origin = self.hold()
        self.resubmit(origin, self.repair)
        later = self.submit('T6 composed with submitted repair', self.repair)
        self.assertEqual(self.finish(later, self.repair)['status'], 'ACCEPTED')
        self.assertEqual(self.cli('status')['quality_holds'][0]['state'], 'RESOLVED')

    def test_official_target_allows_pending_repair_and_independent_candidate(self):
        task = self.hold()
        self.git('switch', '-q', '--detach', self.independent)
        self.assertEqual(self.target('record', 'independent source').returncode, 0)
        self.resubmit(task, self.repair)
        self.git('switch', '-q', '--detach', self.repair)
        self.record(self.repair)
        result = self.target('record', 'repair pending official retest record')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_official_target_does_not_promote_stale_pending_repair_samples(self):
        task = self.hold()
        self.resubmit(task, self.repair)
        self.git('switch', '-q', '--detach', self.repair)
        self.record(self.repair, samples=[dict(label='candidate', deployedRevision=self.repair,
                    finishedAt='2020-01-01T00:00:00Z', **{'pass': True})])
        result = self.target('record', 'stale sample')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fresh candidate samples', result.stderr)
        self.assertFalse((self.project / 'invoked').exists())

    def test_human_review_still_matches_the_actual_record(self):
        task = self.submit('tradeoff', self.independent, review='human')
        self.assertIn('human decision', self.finish(task, self.independent, ok=False))
        reference = 'fixture: actual human selection'
        path = self.record(self.independent, humanDecision=reference,
                           manifest=dict(candidateRevision=self.independent, review='human'))
        self.assertEqual(self.finish(task, self.independent, path, extra=('--human-decision', reference))['status'], 'ACCEPTED')

    def test_inherited_human_review_cannot_be_downgraded_by_an_auto_task(self):
        origin = self.submit('human-reviewed repair', self.held, review='human')
        self.cli('task-quality-hold', '--id', origin, '--agent', 'integrator', '--token', self.token,
                 '--category', 'correctness', '--evidence', 'fixture', '--reason', 'repair')
        self.cli('task-resume', '--id', origin, '--agent', 'worker', '--reason', 'repair')
        self.ready(origin, self.repair, review='human')
        later = self.submit('ordinary task includes human-reviewed repair', self.repair)
        path = self.record(self.repair)
        self.assertIn('human decision', self.finish(later, self.repair, path, ok=False))
        self.git('switch', '-q', '--detach', self.repair)
        self.assertIn('human-review manifest', self.target('record', 'fixture').stderr)
        reference = 'fixture: actual inherited human choice'
        path = self.record(self.repair, humanDecision=reference,
                           manifest=dict(candidateRevision=self.repair, review='human'))
        self.assertIn('human decision', self.finish(later, self.repair, path, ok=False))
        self.assertEqual(self.finish(later, self.repair, path, extra=('--human-decision', reference))['status'], 'ACCEPTED')


if __name__ == '__main__':
    unittest.main()
