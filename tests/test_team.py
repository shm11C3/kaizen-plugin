import concurrent.futures
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'team.sqlite3'
        self.call('status')

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/team/team.py'), '--db', str(self.db), *args],
                              capture_output=True, text=True)

    def call(self, *args):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def create(self):
        return self.call('task-create', '--title', 'Measured hypothesis', '--evidence', 'observe-001.txt')['id']

    def test_simultaneous_claim_has_one_winner(self):
        task_id = self.create()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda agent: self.run_cli('task-claim', '--id', task_id, '--agent', agent),
                                    ('a', 'b', 'c')))
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)
        status = self.call('status')
        self.assertEqual(status['tasks'][0]['status'], 'CLAIMED')

    def test_duplicate_hypothesis_creation_is_atomic(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.run_cli('task-create', '--title', 'Same cause',
                                    '--evidence', 'same dump', '--hypothesis', 'rides-index'), range(2)))
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)
        self.assertEqual(len(self.call('task-list')), 1)

    def test_backlog_redirects_automatic_claims_and_research_can_complete(self):
        for i in range(2):
            task_id = self.create()
            self.call('task-claim', '--id', task_id, '--agent', 'worker')
            self.call('task-ready', '--id', task_id, '--agent', 'worker', '--base', '1'*40,
                      '--sha', '2'*40, '--review', 'auto', '--reason', 'candidate')
        implementation = self.create()
        self.assertIsNone(self.call('task-claim', '--agent', 'new-worker')['task'])
        research = self.call('task-create', '--title', 'Disprove lock explanation', '--evidence', 'existing trace',
                             '--kind', 'comparison', '--hypothesis', 'lock-vs-cpu')['id']
        queue = self.call('queue')
        self.assertTrue(queue['ready_backlog'])
        self.assertEqual(queue['suggested_tasks'][0]['id'], research)
        self.assertEqual(self.call('task-claim', '--agent', 'new-worker')['id'], research)
        self.assertNotEqual(self.run_cli('task-complete', '--id', research, '--agent', 'other', '--reason', 'done').returncode, 0)
        self.assertEqual(self.call('task-complete', '--id', research, '--agent', 'new-worker',
                                  '--reason', 'trace refutes CPU; evidence artifact retained')['status'], 'DONE')
        # Explicit claims remain possible when the next implementation is justified.
        self.call('task-claim', '--id', implementation, '--agent', 'worker')
        self.assertNotEqual(self.run_cli('task-complete', '--id', implementation, '--agent', 'worker',
                                        '--reason', 'cannot skip measurement').returncode, 0)

    def test_environment_is_persistent_and_handoff_invalidates_old_token(self):
        first = self.call('env-acquire', '--agent', 'a', '--purpose', 'experiment')
        self.assertNotEqual(self.run_cli('env-acquire', '--agent', 'b', '--purpose', 'other').returncode, 0)
        self.assertEqual(self.call('status')['environment']['token'], first['token'])
        second = self.call('env-handoff', '--agent', 'a', '--token', first['token'],
                           '--to', 'b', '--reason', 'verified stable')['environment']
        self.assertNotEqual(first['token'], second['token'])
        self.assertNotEqual(self.run_cli('env-release', '--agent', 'a', '--token', first['token'],
                                        '--reason', 'stale').returncode, 0)
        self.call('env-release', '--agent', 'b', '--token', second['token'], '--reason', 'stable')
        self.assertIsNone(self.call('status')['environment'])

    def test_active_operation_prevents_release_and_handoff(self):
        env = self.call('env-acquire', '--agent', 'a', '--purpose', 'experiment')
        with Path(str(self.db) + '.operation.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            result = self.run_cli('env-release', '--agent', 'a', '--token', env['token'], '--reason', 'stable')
            self.assertNotEqual(result.returncode, 0)
            result = self.run_cli('env-handoff', '--agent', 'a', '--token', env['token'],
                                  '--to', 'b', '--reason', 'handoff')
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.call('status')['environment']['owner'], 'a')

    def test_human_candidate_cannot_be_closed_without_decision_reference(self):
        task_id = self.create()
        self.call('task-claim', '--id', task_id, '--agent', 'worker')
        result = self.run_cli('task-ready', '--id', task_id, '--agent', 'other', '--base', '1'*40,
                              '--sha', '2'*40, '--review', 'human', '--reason', 'tradeoff')
        self.assertNotEqual(result.returncode, 0)
        self.call('task-ready', '--id', task_id, '--agent', 'worker', '--base', '1'*40,
                  '--sha', '2'*40, '--review', 'human', '--reason', 'tradeoff')
        self.call('env-acquire', '--agent', 'integrator', '--purpose', task_id)
        args = ('task-finish', '--id', task_id, '--agent', 'integrator', '--result', 'ACCEPTED', '--reason', 'verified')
        self.assertNotEqual(self.run_cli(*args).returncode, 0)
        self.assertEqual(self.call('task-list')[0]['status'], 'READY')
        # A human reference cannot replace the source-bound official record.
        # Actual Git + matching human-record acceptance is in test_source_proof.
        result = self.run_cli(*args, '--human-decision', 'fixture: human approved SHA in the test')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--record', result.stderr)

    def test_unconfigured_target_never_invokes_plugin(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/team/target.py'), '--agent', 'a',
                                 '--token', 'unused', '--db', str(self.db), '--config',
                                 str(Path(self.tmp.name) / 'absent.json'), 'deploy', 'HEAD'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unconfigured', result.stderr)

    def test_measurement_work_is_resumable_without_human_approval(self):
        task_id = self.create()
        self.call('task-claim', '--id', task_id, '--agent', 'worker')
        self.call('task-ready', '--id', task_id, '--agent', 'worker', '--base', '1'*40,
                  '--sha', '2'*40, '--review', 'auto', '--reason', 'candidate')
        self.call('env-acquire', '--agent', 'integrator', '--purpose', task_id)
        base = ('task-finish', '--id', task_id, '--agent', 'integrator')
        self.assertNotEqual(self.run_cli(*base, '--result', 'NEEDS_HUMAN', '--reason', 'missing samples').returncode, 0)
        self.call(*base, '--result', 'NEEDS_MEASUREMENT', '--reason', 'investigate errors and request denominator')
        resumed = self.call('task-resume', '--id', task_id, '--agent', 'worker', '--reason', 'continue investigation')
        self.assertEqual(resumed['status'], 'CLAIMED')
        self.call('task-ready', '--id', task_id, '--agent', 'worker', '--base', '1'*40,
                  '--sha', '3'*40, '--review', 'human', '--reason', 'now a latency tradeoff')
        question = 'Accept increased notification latency for lower CPU?'
        pending = self.call(*base, '--result', 'NEEDS_HUMAN', '--question', question,
                            '--reason', 'comparison complete; recommend current behavior')
        self.assertEqual(pending['human_question'], question)

    def test_join_release_alignment_and_queue_do_not_disclose_reservation_token(self):
        version = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())['version']
        self.call('env-acquire', '--agent', 'integrator', '--purpose', 'work')
        self.assertNotEqual(self.run_cli('join', '--agent', 'a', '--provider', 'codex', '--plugin-version', 'wrong').returncode, 0)
        result = self.call('join', '--agent', 'a', '--provider', 'codex', '--plugin-version', version)
        self.assertNotIn('token', json.dumps(result))
        self.assertEqual(result['integration_owner'], 'integrator')
        self.assertIn('counts', self.call('queue'))

    def test_existing_tasks_survive_additive_schema_upgrade(self):
        legacy = Path(self.tmp.name) / 'legacy.sqlite3'
        with sqlite3.connect(legacy) as db:
            db.execute('CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,evidence TEXT NOT NULL,priority INTEGER NOT NULL,status TEXT NOT NULL DEFAULT "TODO",owner TEXT,base_sha TEXT,source_sha TEXT,review TEXT,reason TEXT,human_decision TEXT,updated_at TEXT NOT NULL)')
            db.execute('INSERT INTO tasks(title,evidence,priority,status,owner,updated_at) VALUES (?,?,?,?,?,?)',
                       ('existing work', 'old observation', 80, 'READY', 'worker', '2026-10-17'))
        self.db = legacy
        row = self.call('task-list')[0]
        self.assertEqual((row['title'], row['status'], row['owner']), ('existing work', 'READY', 'worker'))
        self.assertIsNone(row['human_question'])

    def test_portal_benchmark_blocks_release_and_handoff_between_commands(self):
        env = self.call('env-acquire', '--agent', 'a', '--purpose', 'portal')
        marker = Path(str(self.db) + '.manual-bench')
        marker.touch()
        self.assertNotEqual(self.run_cli('env-release', '--agent', 'a', '--token', env['token'], '--reason', 'too early').returncode, 0)
        self.assertNotEqual(self.run_cli('env-handoff', '--agent', 'a', '--token', env['token'], '--to', 'b', '--reason', 'too early').returncode, 0)
        marker.unlink()
        self.call('env-release', '--agent', 'a', '--token', env['token'], '--reason', 'portal finished')

    def test_target_portal_marker_and_isolated_knowledge_survive_between_calls(self):
        env = self.call('env-acquire', '--agent', 'a', '--purpose', 'portal')
        project, plugin = Path(self.tmp.name) / 'project', Path(self.tmp.name) / 'plugin'
        (project / '.kaizen').mkdir(parents=True)
        (project / '.kaizen/config.sh').write_text('# fixture\n')
        (plugin / 'scripts').mkdir(parents=True)
        knowledge = (Path(self.tmp.name) / 'isolated-knowledge').resolve()
        (plugin / 'knowledge/patterns').mkdir(parents=True)
        (plugin / 'knowledge/match.py').write_text('# corpus seed\n')
        (plugin / 'knowledge/patterns/test.md').write_text('seed pattern\n')
        (plugin / 'scripts/bench.sh').write_text(
            '#!/bin/bash\nset -eu\n'
            'test "$KAIZEN_KNOWLEDGE_DIR" = ' + repr(str(knowledge)) + '\n'
            'if [ "$2" = --reserve ]; then echo pending > .kaizen/manual-bench.json; else rm .kaizen/manual-bench.json; fi\n')
        config = Path(self.tmp.name) / 'target.json'
        config.write_text(json.dumps(dict(enabled=True, confirmed_rules=True, confirmed_recovery_drill=True,
                                          project=str(project), plugin_root=str(plugin), knowledge_dir=str(knowledge))))
        base = [sys.executable, str(ROOT / 'scripts/team/target.py'), '--agent', 'a', '--token', env['token'],
                '--db', str(self.db), '--config', str(config), 'bench', 'baseline']
        r = subprocess.run([*base, '--reserve'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(Path(str(self.db) + '.manual-bench').exists())
        self.assertEqual((knowledge / 'patterns/test.md').read_text(), 'seed pattern\n')
        (knowledge / 'patterns/test.md').write_text('local measured evidence\n')
        self.assertNotEqual(self.run_cli('env-release', '--agent', 'a', '--token', env['token'], '--reason', 'early').returncode, 0)
        r = subprocess.run([*base, '--abandon', 'portal ended'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(Path(str(self.db) + '.manual-bench').exists())
        self.assertEqual((knowledge / 'patterns/test.md').read_text(), 'local measured evidence\n')
        self.assertEqual((plugin / 'knowledge/patterns/test.md').read_text(), 'seed pattern\n')
        self.call('env-release', '--agent', 'a', '--token', env['token'], '--reason', 'ended')

    def test_target_requires_current_owner_and_holds_operation_lock(self):
        env = self.call('env-acquire', '--agent', 'a', '--purpose', 'fixture')
        project = Path(self.tmp.name) / 'project'
        plugin = Path(self.tmp.name) / 'plugin'
        (project / '.kaizen').mkdir(parents=True)
        (project / '.kaizen/config.sh').write_text('# fixture\n')
        (plugin / 'scripts').mkdir(parents=True)
        marker = Path(self.tmp.name) / 'invoked'
        (plugin / 'scripts/status.sh').write_text(
            '#!/bin/bash\nset -eu\ntest "$KAIZEN_TEAM_MODE" = 1\n' + sys.executable + ' - <<\'PY\'\n'
            'import fcntl\nfrom pathlib import Path\n'
            'with open(' + repr(str(self.db) + '.operation.lock') + ', "a") as f:\n'
            '    try:\n        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
            '    except BlockingIOError:\n        Path(' + repr(str(marker)) + ').touch()\n'
            '    else:\n        raise RuntimeError("operation was not locked")\nPY\n')
        config = Path(self.tmp.name) / 'target.json'
        config.write_text(json.dumps({'enabled': True, 'confirmed_rules': True,
                                     'confirmed_recovery_drill': True, 'plugin_root': str(plugin),
                                     'project': str(project)}))
        base = [sys.executable, str(ROOT / 'scripts/team/target.py'), '--agent', 'a', '--db', str(self.db),
                '--config', str(config), '--token']
        wrong = subprocess.run([*base, 'old-token', 'status'], capture_output=True, text=True)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertFalse(marker.exists())
        correct = subprocess.run([*base, env['token'], 'status'], capture_output=True, text=True)
        self.assertEqual(correct.returncode, 0, correct.stderr)
        self.assertTrue(marker.exists())
        # The remote test action uses exactly the same ownership and process lock.
        (plugin / 'scripts/check-remote.sh').write_text((plugin / 'scripts/status.sh').read_text())
        marker.unlink()
        wrong = subprocess.run([*base, 'old-token', 'check-remote'], capture_output=True, text=True)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertFalse(marker.exists())
        with Path(str(self.db) + '.operation.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            busy = subprocess.run([*base, env['token'], 'check-remote'], capture_output=True, text=True)
            self.assertNotEqual(busy.returncode, 0)
            self.assertFalse(marker.exists())
        correct = subprocess.run([*base, env['token'], 'check-remote'], capture_output=True, text=True)
        self.assertEqual(correct.returncode, 0, correct.stderr)
        self.assertTrue(marker.exists())


if __name__ == '__main__':
    unittest.main()
