import datetime
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REV_A = 'a' * 40
REV_B = 'b' * 40


def iso(delta_minutes):
    at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=delta_minutes)
    return at.replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def sample(label, revision, score, minutes_ago, passed=True):
    # Shape written by bench.sh (see scripts/bench.sh, tests/run.sh).
    return {'label': label, 'experiment': '001-flush-log', 'deployedRevision': revision, 'pass': passed,
            'score': score, 'errors': 'map[]', 'durationSec': 60, 'finishedAt': iso(minutes_ago),
            'mode': 'auto', 'observed': False, 'requests': 120, 'stableBundleId': 'bundle-1'}


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'team.sqlite3'
        self.project = self.root / 'project'
        self.state = self.root / 'state'
        self.out = self.root / 'out'

    def team(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/team/team.py'), '--db', str(self.db), *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def dashboard(self, db=None, project=None, state=None):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/team/dashboard.py'),
                               '--db', str(db or self.db), '--project', str(project or self.project),
                               '--state', str(state or self.state), '--out', str(self.out)],
                              capture_output=True, text=True)

    def build_ledger(self):
        first = self.team('task-create', '--title', 'Add rides index', '--evidence', 'slowlog: rides scan')['id']
        self.team('task-claim', '--id', first, '--agent', 'worker')
        self.team('task-ready', '--id', first, '--agent', 'worker', '--base', REV_A, '--sha', REV_B,
                  '--review', 'auto', '--reason', 'candidate ready')
        self.team('task-create', '--title', 'Second idea', '--evidence', 'profile', '--priority', '30')
        third = self.team('task-create', '--title', 'Latency tradeoff', '--evidence', 'trace')['id']
        self.team('task-claim', '--id', third, '--agent', 'worker')
        self.team('task-ready', '--id', third, '--agent', 'worker', '--base', REV_A, '--sha', 'c' * 40,
                  '--review', 'human', '--reason', 'tradeoff')
        token = self.team('env-acquire', '--agent', 'integrator', '--purpose', 'integrate ' + first)['token']
        self.team('task-finish', '--id', third, '--agent', 'integrator', '--result', 'NEEDS_HUMAN',
                  '--question', 'Accept +20ms notification latency?', '--reason', 'recommend keeping current behavior')
        return first, third, token

    def build_project(self):
        kaizen = self.project / '.kaizen'
        exp = kaizen / 'experiments/001-flush-log'
        exp.mkdir(parents=True)
        (kaizen / 'state.env').write_text('STABLE_REV={}\nDEPLOYED_REV={}\nDEPLOYED_HEALTHY=1\nREVERT_PENDING=0\n'
                                          'CURRENT_EXPERIMENT=\nLAST_RUN=candidate-2\nLAST_PASS=true\nLAST_SCORE=2010\n'
                                          .format(REV_B, REV_B))
        samples = [sample('baseline', REV_A, 1000, 50), sample('baseline-2', REV_A, 1010, 48),
                   sample('candidate', REV_B, 2000, 44), sample('candidate-2', REV_B, 2010, 42)]
        # record.json as experiment.sh record writes it.
        (exp / 'record.json').write_text(json.dumps({
            'experimentId': '001-flush-log',
            'manifest': {'experimentId': '001-flush-log', 'hypothesis': 'COMMIT waits on fsync',
                         'stableRevision': REV_A, 'candidateRevision': REV_B, 'review': 'auto'},
            'ruleDecision': {'ruleVersion': 'plugin-rule-v2', 'decision': 'promote', 'nextAction': 'promote',
                             'reason': 'median improved 9900 bp and worst candidate 2000 > best baseline 1010',
                             'quality': {'status': 'pass', 'reason': 'no errors'}, 'qualityBlockPromotion': False,
                             'baselineScores': [1000, 1010], 'candidateScores': [2000, 2010]},
            'finalDecision': 'promote', 'override': None, 'reason': 'flush setting, +100%', 'humanDecision': None,
            'stableBefore': REV_A, 'stableAfter': REV_B, 'candidateRevision': REV_B, 'samples': samples,
            'recovery': 'not-needed',
            'timeline': [iso(52) + '\tdeploy\tHEAD\t6s\tok', iso(50) + '\tbench\tbaseline\t60s\tpass=true score=1000',
                         iso(42) + '\tbench\tcandidate-2\t60s\tpass=true score=2010'],
            'closedAt': iso(41)}, indent=2))
        baseline = kaizen / 'baseline' / REV_B
        baseline.mkdir(parents=True)
        for s in samples[2:]:
            (baseline / ('bench-' + s['label'] + '-reseed.json')).write_text(json.dumps(s))
        # Earlier stable revision: one sample in its own directory, one in a retired copy (stable.sh retire).
        (kaizen / 'baseline' / REV_A).mkdir()
        (kaizen / 'baseline' / REV_A / 'bench-baseline.json').write_text(json.dumps(samples[0]))
        retired = kaizen / 'baseline' / (REV_A + '.retired-20261018T000000Z')
        retired.mkdir()
        (retired / 'bench-baseline-2.json').write_text(json.dumps(samples[1]))
        (retired / 'REASON.txt').write_text('fixture\tretired\n')
        # An open experiment with one failed sample (score 0) that must sit on the axis line.
        open_exp = kaizen / 'experiments/002-open'
        open_exp.mkdir()
        (open_exp / 'manifest.json').write_text(json.dumps({'hypothesis': 'drop reader flock'}))
        (open_exp / 'bench-candidate.json').write_text(json.dumps(sample('candidate', 'd' * 40, 0, 3, passed=False)))
        (kaizen / 'bench-attempts.jsonl').write_text(''.join(json.dumps(
            {'id': 'att%d' % i, 'experiment': '001-flush-log', 'label': 'candidate', 'revision': REV_B,
             'startedAt': iso(minutes)}) + '\n' for i, minutes in enumerate((150, 5))))
        (kaizen / 'plan.md').write_text('# plan\n- next: index on rides\n')

    def build_state(self):
        self.state.mkdir()
        (self.state / 'status.json').write_text(json.dumps({
            'agent': 'integrator', 'state': 'working', 'detail': 'benchmarking candidate', 'task': 'T-0001',
            'experiment': '001-flush-log', 'step': 'bench', 'since': iso(10), 'updatedAt': iso(1),
            'lastError': None, 'candidatesProcessed': 1}))
        events = [
            {'at': iso(40), 'event': 'pick', 'task': 'T-0001', 'experiment': '001-flush-log', 'title': 'Add rides index'},
            {'at': iso(39), 'event': 'review', 'task': 'T-0001', 'experiment': '001-flush-log', 'verdict': 'proceed',
             'reasons': ['small diff'], 'model': 'test-model', 'costUsd': 0.012, 'inputTokens': 1200,
             'outputTokens': 300, 'durationSeconds': 4.2},
            {'at': iso(30), 'event': 'bench', 'task': 'T-0001', 'experiment': '001-flush-log', 'label': 'candidate',
             'score': 2000, 'pass': True, 'durationSeconds': 60},
            {'at': iso(20), 'event': 'record', 'task': 'T-0001', 'experiment': '001-flush-log', 'final': 'promote',
             'reason': 'flush setting', 'stableAfter': REV_B},
            {'at': iso(19), 'event': 'finish', 'task': 'T-0001', 'experiment': '001-flush-log', 'result': 'ACCEPTED',
             'reason': 'promoted'},
            {'at': iso(18), 'event': 'llm', 'task': None, 'experiment': None, 'purpose': 'summary', 'model': 'test-model',
             'costUsd': 0.003, 'inputTokens': 400, 'outputTokens': 100, 'durationSeconds': 1.5},
        ]
        (self.state / 'ledger.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
        (self.state / 'pause').write_text('')
        (self.state / 'feedback').mkdir()
        (self.state / 'feedback/001.md').write_text('Prefer index changes over config changes\nmore text\n')

    def test_renders_fixture(self):
        first, third, token = self.build_ledger()
        self.build_project()
        self.build_state()
        result = self.dashboard()
        self.assertEqual(result.returncode, 0, result.stderr)
        page = (self.out / 'index.html').read_text()
        summary_text = (self.out / 'summary.json').read_text()
        summary = json.loads(summary_text)
        self.assertEqual(summary['counts'], {'READY': 1, 'TODO': 1, 'NEEDS_HUMAN': 1})
        self.assertEqual(summary['ready'], [first])
        self.assertEqual(summary['needsHuman'], [{'id': third, 'question': 'Accept +20ms notification latency?'}])
        self.assertEqual(summary['promoted'], 1)
        self.assertEqual((summary['rejected'], summary['inconclusive']), (0, 0))
        self.assertAlmostEqual(summary['llm']['costUsd'], 0.015)
        self.assertEqual((summary['llm']['calls'], summary['llm']['inputTokens'], summary['llm']['outputTokens']),
                         (2, 1600, 400))
        self.assertTrue(summary['paused'])
        self.assertEqual(summary['baselineMedian'], 2005)
        self.assertEqual(summary['firstBaselineMedian'], 1005)
        self.assertEqual(summary['benchAttempts'], {'lastHour': 1, 'total': 2})
        self.assertEqual(summary['stable'], REV_B)
        self.assertEqual(summary['reservation'], {'owner': 'integrator', 'purpose': 'integrate ' + first,
                                                  'acquiredAt': summary['reservation']['acquiredAt']})
        self.assertEqual(summary['integrations'][0]['task'], first)
        self.assertEqual(summary['integrator']['state'], 'working')
        self.assertEqual(summary['unavailable'], [])
        for needle in ('Add rides index', '001-flush-log', '統合Agent: 作業中 (working)', 'T-0001', 'Accept +20ms',
                       '<svg', 'Prefer index changes', 'meta http-equiv="refresh" content="30"',
                       '<h2>スコア時系列</h2>', '<h2>キュー</h2>', '<h2>統合履歴</h2>', '<h2>予算</h2>',
                       '採用 1 / 却下 0 / 判定保留 0', '一時停止'):
            self.assertIn(needle, page)
        self.assertNotIn('取得不可', page)
        # Dark scheme: custom properties on :root, a dark media block, state colour via class not inline style.
        self.assertIn(':root{--bg:', page)
        self.assertIn('@media (prefers-color-scheme: dark){:root{', page)
        self.assertIn('class="card state st-working"', page)
        self.assertNotIn('style="', page)
        # Timeline: both stable revisions make a two-step median line (4 coordinate pairs); axis starts at
        # 90% of the lowest passing score floored to a nice number (1000 -> 900); the failed sample is a cross.
        step = re.search(r'<path class="step" d="([^"]+)"', page).group(1)
        self.assertEqual(len(re.findall(r'[\d.]+,[\d.]+', step)), 4, step)
        self.assertIn('>900</text>', page)
        self.assertIn('>2010</text>', page)
        self.assertIn('class="fail"', page)
        self.assertIn('進行中 002-open', page)
        self.assertNotIn(token, page)
        self.assertNotIn(token, summary_text)
        self.assertNotIn('"token"', page)

    def test_missing_sources_render_unavailable_and_exit_zero(self):
        missing = self.root / 'absent'
        result = self.dashboard(db=missing / 'team.sqlite3', project=missing / 'project', state=missing / 'state')
        self.assertEqual(result.returncode, 0, result.stderr)
        page = (self.out / 'index.html').read_text()
        self.assertIn('取得不可: ', page)
        self.assertIn('統合Agent: 取得不可', page)
        self.assertIn('ベンチ標本が2件未満', page)
        summary = json.loads((self.out / 'summary.json').read_text())
        self.assertEqual(summary['counts'], {})
        self.assertIsNone(summary['integrator'])
        self.assertGreaterEqual(len(summary['unavailable']), 3)
        self.assertTrue(all(note.startswith('取得不可: ') for note in summary['unavailable']), summary['unavailable'])
        self.assertFalse(sorted(self.out.iterdir()) != [self.out / 'index.html', self.out / 'summary.json'])


if __name__ == '__main__':
    unittest.main()
