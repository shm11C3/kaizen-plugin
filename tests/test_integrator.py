"""The unattended integrator against the fake remote: same scripts, same guards."""
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import _git_test_env  # Keep fixture Git commands independent of the invoking repository.
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/team'))
import integrator as module  # noqa: E402

FAKE_CLAUDE = '''#!/usr/bin/env python3
import json, os, sys
prompt = sys.argv[-1]
open(os.environ['FAKE_CLAUDE_LOG'], 'a').write(json.dumps({'argv': sys.argv[1:-1], 'prompt': prompt}) + '\\n')
proceed = 'RETURN-ME' not in prompt
verdict = {'proceed': proceed, 'reasons': [] if proceed else ['diff touches benchmark-facing checks'],
           'hypothesis': 'the score file is read on every request', 'changeSummary': 'raises go/score',
           'expectedEffect': 'score up', 'scoringPath': 'all requests', 'risks': ['none seen']}
print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 1, 'session_id': 'fake',
                  'result': 'Here is my review:\\n```json\\n' + json.dumps(verdict) + '\\n```',
                  'total_cost_usd': 0.0123, 'usage': {'input_tokens': 1500, 'output_tokens': 120}}))
'''


class IntegratorFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.remote = self.directory / 'remote'
        self.remote.mkdir()
        binary = self.directory / 'bin'
        binary.mkdir()
        shims = {
            'sudo': '#!/usr/bin/env bash\nwhile [ $# -gt 0 ]; do case "$1" in -u|-i) [ "$1" = -u ] && shift; shift ;; -*) shift ;; *) break ;; esac; done\nexec "$@"\n',
            'systemctl': '#!/usr/bin/env bash\necho "systemctl $* ($FAKE_HOST)" >> "$KAIZEN_FAKE_REMOTE/systemctl.log"\n',
            'md5sum': '#!' + sys.executable + '\nimport hashlib,sys\nfor p in sys.argv[1:]: print(hashlib.md5(open(p,"rb").read()).hexdigest()+"  "+p)\n',
            'claude': FAKE_CLAUDE,
        }
        for name, contents in shims.items():
            path = binary / name
            path.write_text(contents)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.claude_log = self.directory / 'claude.log'
        self.env = dict(os.environ, KAIZEN_FAKE_REMOTE=str(self.remote), PATH=str(binary) + os.pathsep + os.environ['PATH'],
                        FAKE_CLAUDE_LOG=str(self.claude_log), GIT_TERMINAL_PROMPT='0')
        for key in ('KAIZEN_PROJECT', 'KAIZEN_PLUGIN_ROOT', 'KAIZEN_TEAM_MODE', 'KAIZEN_KNOWLEDGE_DIR'):
            self.env.pop(key, None)
        self.project = self.directory / 'project'
        (self.project / 'go').mkdir(parents=True)
        (self.project / 'sql').mkdir()
        (self.project / '.kaizen').mkdir()
        (self.project / 'go/score').write_text('1000\n')
        (self.project / 'sql/1-schema.sql').write_text('CREATE TABLE t (id INT PRIMARY KEY);\n')
        (self.project / 'notes.txt').write_text('a\nb\nc\nd\ne\n')
        (self.project / '.kaizen/config.sh').write_text('''. "$KAIZEN_PLUGIN_ROOT/presets/isucon14.sh"
APP_HOST=isu1
APP_HOSTS="isu1 isu2"
BENCH_HOST=bench
APP_PRIVATE_IP=10.0.0.1
BENCH_PRIVATE_IP=10.0.0.2
REMOTE_APP_DIR=webapp
RSYNC_PATH=""
SYNC_EXCLUDES=""
BUILD_CMD='test -f webapp/go/score'
RESTART_CMD='sudo systemctl restart app.service'
HEALTH_CMD='true'
bench_command() { echo "bash %s/tests/fake-bench.sh"; }
MAX_BENCH_PER_EXP=0
MIN_SAMPLES=2
RECOVERY_BENCH_RESERVE=0
RESOURCE_FINGERPRINT_CMD='cat database.state'
RECOVERY_CMD='cp webapp/sql/1-schema.sql database.state'
PROBLEM=test
RETRO_BLOCK_AFTER=1000
EVALUATION_RULE=v2
REQUEST_COUNT_CMD='wc -l < access.log 2>/dev/null || echo 0'
''' % ROOT)
        self.git(self.project, 'init', '-q', '-b', 'main')
        self.git(self.project, 'config', 'user.name', 'fixture')
        self.git(self.project, 'config', 'user.email', 'fixture@example.test')
        self.git(self.project, 'config', 'commit.gpgsign', 'false')
        self.git(self.project, 'add', '.')
        self.git(self.project, 'commit', '-qm', 'initial')
        self.origin = self.directory / 'origin.git'
        self.git(self.directory, 'init', '-q', '--bare', str(self.origin))
        self.git(self.project, 'remote', 'add', 'origin', str(self.origin))
        self.git(self.project, 'push', '-q', 'origin', 'main')
        # The target as setup leaves it: stable deployed, resources initialized, bundle captured, recovery drilled.
        loop = dict(self.env, KAIZEN_PROJECT=str(self.project), KAIZEN_PLUGIN_ROOT=str(ROOT))
        (self.project / '.kaizen/state.env').write_text('STABLE_REV=' + self.sha(self.project, 'main') + '\n')
        self.script(loop, 'deploy.sh', 'main')
        for host in ('isu1', 'isu2'):
            (self.remote / host / 'database.state').write_text((self.project / 'sql/1-schema.sql').read_text())
        self.script(loop, 'stable.sh', 'capture')
        self.script(loop, 'recover.sh')
        # The ledger, the registered official environment and the integrator's settings.
        self.db = self.directory / 'team.sqlite3'
        self.state = self.directory / 'integrator'
        self.state.mkdir()
        self.target = self.directory / 'target.json'
        self.target.write_text(json.dumps(dict(enabled=True, confirmed_rules=True, confirmed_recovery_drill=True,
                                               environment='competition', project=str(self.project), plugin_root=str(ROOT),
                                               knowledge_dir=str(self.directory / 'knowledge'),
                                               resources=['host:isu1', 'host:isu2', 'bench:fake'])))
        self.team('env-register', '--agent', 'admin', '--config', str(self.target), '--reason', 'fixture isolation')
        (self.state / 'integrator.json').write_text(json.dumps(dict(
            agent='integrator-01', github_user='Member-01', review='llm', poll_seconds=1, push=True,
            llm=dict(command=['claude', '-p', '--output-format', 'json'], model='fake-model', max_budget_usd=0.5, timeout_seconds=30))))
        self.worker = self.directory / 'worker'
        self.git(self.directory, 'clone', '-q', str(self.origin), str(self.worker))
        for key, value in (('user.name', 'worker'), ('user.email', 'worker@example.test'), ('commit.gpgsign', 'false')):
            self.git(self.worker, 'config', key, value)

    # -- helpers ----------------------------------------------------------------------

    def git(self, cwd, *args):
        return subprocess.check_output(['git', '-C', str(cwd), *args], text=True, stderr=subprocess.STDOUT, env=self.env)

    def sha(self, cwd, ref='HEAD'):
        return self.git(cwd, 'rev-parse', ref).strip()

    def script(self, env, name, *args):
        result = subprocess.run(['bash', str(ROOT / 'scripts' / name), *args], cwd=self.project, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, name + ': ' + result.stdout + result.stderr)
        return result.stdout

    def team(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/team/team.py'), '--db', str(self.db), *args],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def submit(self, title, branch, edits, base='origin/main', hypothesis=None):
        """A worker branch from base with the edits, pushed and submitted READY."""
        self.git(self.worker, 'fetch', '-q', 'origin')
        self.git(self.worker, 'switch', '-q', '-c', branch, base)
        for path, text in edits.items():
            (self.worker / path).write_text(text)
        self.git(self.worker, 'add', '-A')
        self.git(self.worker, 'commit', '-qm', title)
        self.git(self.worker, 'push', '-q', '-u', 'origin', branch)
        task = self.team('task-create', '--title', title, '--evidence', 'observe-001.txt:' + branch,
                         '--hypothesis', hypothesis or branch)['id']
        self.team('task-claim', '--id', task, '--agent', 'worker-claude-01')
        self.team('task-ready', '--id', task, '--agent', 'worker-claude-01', '--base', self.sha(self.worker, base),
                  '--sha', self.sha(self.worker), '--review', 'auto', '--reason', 'local checks passed')
        return task

    def once(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/team/integrator.py'), '--db', str(self.db),
                                 '--config', str(self.target), '--state', str(self.state), 'once'],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def tasks(self):
        return {row['id']: row for row in self.team('task-list')}

    def ledger(self, task=None):
        rows = [json.loads(line) for line in (self.state / 'ledger.jsonl').read_text().splitlines() if line.strip()]
        return [row for row in rows if task is None or row.get('task') == task]

    def state_env(self):
        return module.read_state(self.project)


class IntegratorLoop(IntegratorFixture):
    def test_candidates_flow_through_the_rule_and_the_ledger(self):
        # Nothing READY: the loop idles and spends nothing.
        idle = self.once()
        self.assertFalse(idle['processed'])
        self.assertEqual(idle['status']['state'], 'idle')
        self.assertFalse(self.claude_log.exists())

        # 1. A clean improvement is composed, reviewed, measured, promoted, pushed and accepted.
        first = self.submit('Raise the score', 'worker/T-0001-score', {'go/score': '2000\n'})
        before = self.sha(self.project, 'main')
        result = self.once()
        self.assertTrue(result['processed'], result)
        self.assertEqual(result['status']['state'], 'idle', result['status'])
        self.assertIn(first, result['status']['detail'])
        row = self.tasks()[first]
        self.assertEqual(row['status'], 'ACCEPTED', row)
        adopted = self.sha(self.project, 'main')
        self.assertNotEqual(adopted, before)
        self.assertEqual(self.sha(self.origin, 'main'), adopted, 'adopted main pushed to origin')
        self.assertEqual(self.state_env()['STABLE_REV'], adopted)
        self.assertEqual(self.state_env()['DEPLOYED_REV'], adopted)
        self.assertEqual((self.remote / 'isu1/webapp/go/score').read_text(), '2000\n')
        self.assertIsNone(self.team('status')['environment'], 'reservation released')
        events = [row['event'] for row in self.ledger(first)]
        for name in ('pick', 'compose', 'review', 'baseline', 'open', 'deploy', 'bench', 'evaluate', 'finish'):
            self.assertIn(name, events, events)
        self.assertGreaterEqual(events.count('baseline'), 2, 'fresh baseline taken before the candidate')
        review = [row for row in self.ledger(first) if row['event'] == 'review'][0]
        self.assertEqual((review['verdict'], review['costUsd'], review['inputTokens'], review['model']),
                         ('proceed', 0.0123, 1500, 'fake-model'))
        prompt = json.loads(self.claude_log.read_text().splitlines()[0])
        self.assertIn('--max-budget-usd', prompt['argv'])
        self.assertIn('fake-model', prompt['argv'])
        self.assertIn('+2000', prompt['prompt'], 'the composed diff is what the reviewer sees')
        self.assertIn(first, prompt['prompt'])
        records = list((self.project / '.kaizen/experiments').glob('*/record.json'))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text())
        self.assertEqual((record['finalDecision'], record['candidateRevision'], record['manifest']['team']['task']),
                         ('promote', adopted, first))
        self.assertEqual(record['manifest']['hypothesis'], 'the score file is read on every request')
        self.assertEqual(record['manifest']['allowedChanges'][0]['path'], 'go/score')
        self.assertTrue(records[0].parent.name.startswith('001-' + first))
        self.assertIn('ACCEPTED', (self.state / 'feedback' / (first + '.md')).read_text())
        self.assertFalse((self.state / 'reservation.json').exists())
        self.assertFalse((self.state / 'pause').exists())
        page = (self.state / 'dashboard/index.html').read_text()
        self.assertIn(first, page)
        self.assertIn('ACCEPTED', page)
        summary = json.loads((self.state / 'dashboard/summary.json').read_text())
        self.assertEqual(summary['promoted'], 1)
        self.assertAlmostEqual(summary['llm']['costUsd'], 0.0123)

        # 1b. A failed run of stable in the fresh baseline set is retired, not paid for with candidate slots.
        baseline_dir = self.project / '.kaizen/baseline' / adopted
        failed_sample = dict(json.loads(next(baseline_dir.glob('*.json')).read_text()), label='baseline-flaky', score=900,
                             finishedAt=module.now(), **{'pass': False})
        (baseline_dir / 'bench-flaky.json').write_text(json.dumps(failed_sample))
        neutral = self.submit('Neutral edit', 'worker/T-0002-neutral', {'notes.txt': 'a\nb\nc\nd\ne\nf\n'}, hypothesis='neutral-edit')
        self.assertTrue(self.once()['processed'])
        row = self.tasks()[neutral]
        self.assertEqual(row['status'], 'NEEDS_MEASUREMENT', row)
        self.assertEqual(self.team('status')['quality_holds'], [], 'measurement conditions are not a candidate quality hold')
        retired = [r for r in self.ledger(neutral) if r['event'] == 'baseline-retired']
        self.assertEqual(retired[0]['failed'], ['baseline-flaky'])
        self.assertTrue(list((self.project / '.kaizen/baseline').glob(adopted + '.retired-*')), 'failed set retired as evidence')
        self.assertGreaterEqual(len([r for r in self.ledger(neutral) if r['event'] == 'baseline']), 2, 'fresh baseline taken after retiring')
        self.assertTrue(list((self.project / '.kaizen/experiments').glob('002-' + neutral + '-neutral-edit')), 'slug from the hypothesis key')

        # 2. A branch from the old base that conflicts with the adopted change is returned without a bench.
        second = self.submit('Lower the score', 'worker/T-0003-conflict', {'go/score': '1500\n'}, base=before)
        self.assertTrue(self.once()['processed'])
        row = self.tasks()[second]
        self.assertEqual(row['status'], 'NEEDS_MEASUREMENT', row)
        self.assertIn('rebase', row['reason'])
        compose = [r for r in self.ledger(second) if r['event'] == 'compose'][0]
        self.assertEqual(compose['status'], 'conflict')
        self.assertEqual([r['event'] for r in self.ledger(second) if r['event'] in ('open', 'bench', 'deploy', 'review')], [])
        self.assertEqual(len(list((self.project / '.kaizen/experiments').glob('*/'))), 2, 'no experiment opened')
        self.assertEqual(self.sha(self.project, 'main'), adopted)
        self.assertEqual(self.git(self.project, 'status', '--porcelain', '--', 'go', 'sql', 'notes.txt'), '', 'checkout left clean')
        self.assertEqual(self.git(self.project, 'worktree', 'list').count('\n'), 1, 'dry-run worktree removed')

        # 3. The reviewer may return a candidate before any slot is spent; the rule never saw it.
        third = self.submit('RETURN-ME: weaken a check', 'worker/T-0004-return', {'notes.txt': 'a\nb\nc\nd\nskip-check\n'})
        self.assertTrue(self.once()['processed'])
        row = self.tasks()[third]
        self.assertEqual(row['status'], 'NEEDS_MEASUREMENT', row)
        self.assertIn('レビュー: diff touches benchmark-facing checks', row['reason'])
        self.assertEqual([r['event'] for r in self.ledger(third) if r['event'] in ('open', 'bench', 'baseline', 'deploy')], [])

        # 4. A correctness failure recovers stable and leaves a hold on the failed source.
        fourth = self.submit('Break it', 'worker/T-0005-break', {'go/score': 'fail\n'})
        self.assertTrue(self.once()['processed'])
        row = self.tasks()[fourth]
        self.assertEqual(row['status'], 'NEEDS_MEASUREMENT', row)
        holds = self.team('status')['quality_holds']
        self.assertEqual([(h['category'], h['state'], 'T-{:04d}'.format(h['task_id'])) for h in holds],
                         [('correctness', 'OPEN', fourth)])
        self.assertIn('correctness', [r for r in self.ledger(fourth) if r['event'] == 'hold'][0]['category'])
        self.assertEqual(self.state_env()['STABLE_REV'], adopted)
        self.assertEqual(self.state_env()['DEPLOYED_REV'], adopted)
        self.assertEqual(self.state_env()['REVERT_PENDING'], '0')
        self.assertEqual((self.remote / 'isu1/webapp/go/score').read_text(), '2000\n', 'stable redeployed')
        self.assertEqual(self.sha(self.project, 'main'), adopted)
        self.assertEqual(self.git(self.project, 'branch', '--show-current').strip(), 'main')
        bench = [r for r in self.ledger(fourth) if r['event'] == 'bench']
        self.assertEqual(len(bench), 1)
        self.assertFalse(bench[0]['pass'])
        self.assertIsNone(self.team('status')['environment'])
        self.assertEqual(self.state_env()['CURRENT_EXPERIMENT'], '')

        # 5. While another session holds the environment the integrator waits and takes nothing.
        fifth = self.submit('Tradeoff', 'worker/T-0006-human', {'notes.txt': 'z\n'})
        self.team('env-acquire', '--agent', 'worker-claude-01', '--purpose', 'manual integration')
        waiting = self.once()
        self.assertFalse(waiting['processed'])
        self.assertEqual(waiting['status']['state'], 'waiting')
        self.assertIn('worker-claude-01', waiting['status']['detail'])
        token = self.team('status')['environment']['token']
        self.team('env-release', '--agent', 'worker-claude-01', '--token', token, '--reason', 'done')

        # 6. pause stops new work without touching the ledger.
        (self.state / 'pause').write_text('test\n')
        paused = self.once()
        self.assertFalse(paused['processed'])
        self.assertEqual(paused['status']['state'], 'paused')
        self.assertEqual(self.tasks()[fifth]['status'], 'READY')

    def test_dry_compose_detects_overlap_and_empty(self):
        args = type('Args', (), {'db': str(self.db), 'config': str(self.target), 'state': str(self.state), 'settings': None})()
        engine = module.Integrator(args)
        engine.project = self.project
        engine.config = {'stable_branch': 'main'}
        base = self.sha(self.project, 'main')
        # main moves on line 1 of notes.txt (as an adopted change would), the worker edits line 5 from the old base.
        (self.project / 'notes.txt').write_text('A\nb\nc\nd\ne\n')
        self.git(self.project, 'commit', '-qam', 'adopted elsewhere')
        self.git(self.worker, 'switch', '-q', '-c', 'worker/overlap', base)
        (self.worker / 'notes.txt').write_text('a\nb\nc\nd\nE\n')
        self.git(self.worker, 'commit', '-qam', 'overlap')
        self.git(self.project, 'fetch', '-q', str(self.worker), 'worker/overlap')
        overlap = engine.dry_compose({'base_sha': base, 'source_sha': self.sha(self.worker)})
        self.assertEqual(overlap['status'], 'overlap', overlap)
        self.assertIn('notes.txt', overlap['message'])
        # The same edit already on main composes to nothing.
        self.git(self.worker, 'switch', '-q', '-c', 'worker/same', base)
        (self.worker / 'notes.txt').write_text('A\nb\nc\nd\ne\n')
        self.git(self.worker, 'commit', '-qam', 'same as adopted')
        self.git(self.project, 'fetch', '-q', str(self.worker), 'worker/same')
        same = engine.dry_compose({'base_sha': base, 'source_sha': self.sha(self.worker)})
        self.assertEqual(same['status'], 'empty', same)
        # An unrelated file composes cleanly and the diff is against the current stable tip.
        self.git(self.worker, 'switch', '-q', '-c', 'worker/clean', base)
        (self.worker / 'sql/2-index.sql').write_text('CREATE INDEX i ON t (id);\n')
        self.git(self.worker, 'add', '-A')
        self.git(self.worker, 'commit', '-qm', 'index')
        self.git(self.project, 'fetch', '-q', str(self.worker), 'worker/clean')
        clean = engine.dry_compose({'base_sha': base, 'source_sha': self.sha(self.worker)})
        self.assertEqual((clean['status'], clean['files']), ('ok', ['sql/2-index.sql']))
        self.assertIn('CREATE INDEX', clean['diff'])
        self.assertEqual(self.git(self.project, 'worktree', 'list').count('\n'), 1)
        self.assertEqual(self.sha(self.project, 'main'), self.sha(self.project))

    def hold(self, task_id, base, source, state='OPEN', repair=None, category='correctness'):
        db = sqlite3.connect(self.db)
        db.execute('INSERT INTO quality_holds(task_id,base_sha,source_sha,environment,category,evidence,reason,opened_at,state,repair_sha) '
                   "VALUES (?,?,?,'competition',?,'decision.json','pass=false',?,?,?)",
                   (task_id, base, source, category, '2026-10-29T00:00:00+00:00', state, repair))
        db.commit()
        db.close()

    def test_inherited_hold_returns_the_candidate_before_any_benchmark(self):
        # Practice R3: T-0045/T-0046 stacked on held T-0041/T-0042 and spent a baseline
        # and a candidate bench before promotion refused them.
        base = self.sha(self.project, 'main')
        self.git(self.worker, 'switch', '-q', '-c', 'worker/held', base)
        (self.worker / 'sql/1-schema.sql').write_text('CREATE TABLE t (id INT PRIMARY KEY, v INT);\n')
        self.git(self.worker, 'commit', '-qam', 'held change')
        self.git(self.worker, 'push', '-q', '-u', 'origin', 'worker/held')
        self.hold(99, base, self.sha(self.worker))
        # As in R3: the stacked source carries the held commit but declares the stable base.
        self.git(self.worker, 'switch', '-q', '-c', 'worker/stacked')
        (self.worker / 'go/score').write_text('1200\n')
        self.git(self.worker, 'commit', '-qam', 'stacked on held')
        self.git(self.worker, 'push', '-q', '-u', 'origin', 'worker/stacked')
        task = self.team('task-create', '--title', 'stacked on held', '--evidence', 'observe-001.txt', '--hypothesis', 'stacked')['id']
        self.team('task-claim', '--id', task, '--agent', 'worker-claude-01')
        self.team('task-ready', '--id', task, '--agent', 'worker-claude-01', '--base', base, '--sha', self.sha(self.worker),
                  '--review', 'auto', '--reason', 'stacked')
        self.once()
        row = self.tasks()[task]
        self.assertEqual(row['status'], 'NEEDS_MEASUREMENT')
        self.assertIn('integrator: ベンチ前に停止', row['reason'])
        self.assertEqual([r['event'] for r in self.ledger(task) if r['event'] in ('open', 'baseline', 'bench', 'deploy')], [])

    def test_repair_of_the_held_task_still_reaches_measurement(self):
        args = type('Args', (), {'db': str(self.db), 'config': str(self.target), 'state': str(self.state), 'settings': None})()
        engine = module.Integrator(args)
        engine.project = self.project
        base = self.sha(self.project, 'main')
        self.git(self.worker, 'switch', '-q', '-c', 'worker/failed', base)
        (self.worker / 'go/score').write_text('900\n')
        self.git(self.worker, 'commit', '-qam', 'failed change')
        failed = self.sha(self.worker)
        (self.worker / 'go/score').write_text('1100\n')
        self.git(self.worker, 'commit', '-qam', 'repair')
        repair = self.sha(self.worker)
        self.git(self.project, 'fetch', '-q', str(self.worker), 'worker/failed')
        self.hold(7, base, failed, state='RETEST_PENDING', repair=repair)
        self.assertIsNone(engine.inherited_hold_block({'id': 'T-0007', 'base_sha': base, 'source_sha': repair}, {'stable': base}))
        # The failed content itself, resubmitted unchanged, is still refused.
        self.assertIn('H-', engine.inherited_hold_block({'id': 'T-0007', 'base_sha': base, 'source_sha': failed}, {'stable': base}))


class Helpers(unittest.TestCase):
    def test_irrecoverable_score_overlap_stops_candidate_measurement(self):
        scores = {'ruleVersion': 'plugin-rule-v2', 'decision': 'inconclusive', 'nextAction': 'remeasure',
                  'minimumSamples': 2, 'baselineScores': [58567, 62811],
                  'candidateScores': [65191, 61956]}
        self.assertTrue(module.overlap_cannot_recover(scores))
        self.assertFalse(module.overlap_cannot_recover(dict(scores, ruleVersion='plugin-rule-v3', candidateScores=[61956])))
        self.assertFalse(module.overlap_cannot_recover(dict(scores, ruleVersion='plugin-rule-v4')))
        self.assertFalse(module.overlap_cannot_recover(dict(scores, candidateScores=['61956', 65191])))

        decisions = [dict(scores, candidateScores=[65191]), scores]
        labels = []
        ledger = []
        engine = type('FakeEngine', (), {})()
        engine.sample_limit = lambda: 6
        engine.bench = lambda tid, experiment, label: labels.append(label) or True
        engine.evaluate = lambda experiment: decisions.pop(0)
        engine.ledger = lambda event, **fields: ledger.append((event, fields))
        result = module.Integrator.measure(engine, 'T-test', 'exp-test')
        self.assertEqual(labels, ['candidate', 'candidate-2'])
        self.assertEqual(result['candidateScores'], [65191, 61956])
        self.assertTrue(any(row[0] == 'budget' and '分離条件' in row[1]['message'] for row in ledger))

    def test_separated_candidate_can_still_take_another_sample(self):
        base = {'ruleVersion': 'plugin-rule-v2', 'decision': 'inconclusive', 'nextAction': 'remeasure',
                'minimumSamples': 2, 'baselineScores': [58567, 62811]}
        first = dict(base, candidateScores=[65191, 66000])
        second = dict(base, candidateScores=[65191, 66000, 67000])
        self.assertFalse(module.overlap_cannot_recover(first))
        decisions = [first, second, dict(second, decision='promote', nextAction='promote')]
        labels = []
        engine = type('FakeEngine', (), {})()
        engine.sample_limit = lambda: 6
        engine.bench = lambda tid, experiment, label: labels.append(label) or True
        engine.evaluate = lambda experiment: decisions.pop(0)
        engine.ledger = lambda event, **fields: None
        module.Integrator.measure(engine, 'T-test', 'exp-test')
        self.assertEqual(labels, ['candidate', 'candidate-2', 'candidate-3'])

    def test_sample_limit_respects_plugin_cap_and_own_ceiling(self):
        args = type('Args', (), {'db': '/nonexistent/db', 'config': '/nonexistent/target.json', 'state': None, 'settings': None})()
        with tempfile.TemporaryDirectory() as directory:
            args.db = str(Path(directory) / 'team.sqlite3')
            engine = module.Integrator(args)
            for cap, own, expected in ((0, 6, 6), (3, 6, 3), (8, 6, 6), (0, 0, 0), (4, 0, 4)):
                engine.config = {'max_bench_per_exp': cap}
                engine.settings['max_candidate_samples'] = own
                self.assertEqual(engine.sample_limit(), expected, (cap, own))

    def test_portal_result_must_match_the_reserved_run(self):
        reserved = '2026-10-18T10:00:00+00:00'
        good = {'experiment': '003-T-0001', 'label': 'candidate', 'at': '2026-10-18T10:05:00+00:00', 'result': 'pass=true score=1'}
        self.assertTrue(module.portal_result_matches(good, '003-T-0001', 'candidate', reserved, 'abcdef0123'))
        self.assertTrue(module.portal_result_matches(dict(good, sha='ABCDEF'), '003-T-0001', 'candidate', reserved, 'abcdef0123'))
        self.assertFalse(module.portal_result_matches(dict(good, at='2026-10-18T09:59:59+00:00'), '003-T-0001', 'candidate', reserved, 'abcdef0123'))
        self.assertFalse(module.portal_result_matches(dict(good, label='candidate-2'), '003-T-0001', 'candidate', reserved, 'abcdef0123'))
        self.assertFalse(module.portal_result_matches(dict(good, experiment='002-T-0009'), '003-T-0001', 'candidate', reserved, 'abcdef0123'))
        self.assertFalse(module.portal_result_matches(dict(good, sha='999999'), '003-T-0001', 'candidate', reserved, 'abcdef0123'))
        self.assertFalse(module.portal_result_matches({'at': good['at']}, '003-T-0001', 'candidate', reserved, 'abcdef0123'))

    def test_control_dispatches_integrator_and_dashboard_commands(self):
        import control
        config = {'remote_plugin_root': '/srv/isucon/kaizen-plugin'}
        self.assertEqual(control.remote_command(config, 'integrator', ['pause', '--reason', 'manual integration']),
                         "runuser -u isucon -- python3 /srv/isucon/kaizen-plugin/scripts/team/integrator.py --db "
                         "/srv/isucon/state/team.sqlite3 --config /srv/isucon/state/target.json pause --reason 'manual integration'")
        self.assertEqual(control.remote_command(config, 'dashboard', []),
                         'runuser -u isucon -- cat /srv/isucon/state/integrator/dashboard/summary.json')
        lane = dict(config, state_db='/srv/isucon/state/lane.sqlite3', target_config='/srv/isucon/state/lane.json')
        self.assertIn('--db /srv/isucon/state/lane.sqlite3 --config /srv/isucon/state/lane.json status',
                      control.remote_command(lane, 'integrator', ['status']))

    def test_conditions_problem_is_about_the_baseline_not_the_candidate(self):
        self.assertTrue(module.conditions_problem({'decision': 'inconclusive', 'reason': 'need passing baseline and candidate samples'}))
        self.assertTrue(module.conditions_problem({'decision': 'inconclusive', 'reason': 'stable bundle/measurement conditions differ; take fresh samples'}))
        self.assertFalse(module.conditions_problem({'decision': 'inconclusive', 'reason': 'improvement/noise not separated; remeasure within the physical-run budget'}))
        self.assertFalse(module.conditions_problem({'decision': 'reject', 'reason': 'need passing baseline and candidate samples'}))

    def test_model_answer_and_hold_category(self):
        self.assertEqual(module.parse_json_object('text ```json\n{"proceed": true}\n``` more')['proceed'], True)
        with self.assertRaises(ValueError):
            module.parse_json_object('no object here')
        self.assertEqual(module.hold_category({'quality': {'reason': 'request timed out 3 times'}, 'reason': ''}), 'timeout')
        self.assertEqual(module.hold_category({'quality': {'reason': 'error rates need request denominators'}, 'reason': ''}), 'conditions')
        self.assertEqual(module.hold_category({'quality': {'reason': 'an error family the baseline never showed'}, 'reason': ''}), 'unknown')


if __name__ == '__main__':
    unittest.main()
