"""Rules replayed over the recorded experiments (knowledge/records).

Pins how plugin-rule-v2 and plugin-rule-v3 judge the same evidence. The
records hold the candidate samples; the baseline samples measured on each
stable revision are stored next to them under baseline/<stable>/ (copied
from the practice repositories, errors included). Only when no stored
sample exists is a baseline rebuilt from the recorded scores, with the
candidate's error kinds at count 1.
"""
import glob
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import measurement  # noqa: E402


def load_records():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, 'knowledge', 'records', '*', '*.json'))):
        record = json.load(open(path))
        if 'ruleDecision' not in record:
            continue
        key = os.path.basename(os.path.dirname(path)) + '/' + record['experimentId'][:3]
        samples = record.get('samples', [])
        candidate = [dict(s, stableBundleId=None) for s in samples if s['label'].startswith('candidate')]
        baseline = [dict(s, stableBundleId=None) for s in samples if s['label'].startswith('baseline')]
        stable = record['manifest']['stableRevision']
        # Baseline samples measured on the stable revision live under
        # records/<problem>/baseline/<stable>/ (copied from the practice repos).
        stored = []
        for f in sorted(glob.glob(os.path.join(os.path.dirname(path), 'baseline', stable, '*.json'))):
            s = json.load(open(f))
            if s.get('deployedRevision') == stable and s.get('pass') and not s.get('observed'):
                stored.append(dict(s, stableBundleId=None))
        if stored:
            baseline = stored
        elif not baseline:
            kinds = candidate[0].get('errors') if candidate else 'none'
            assumed = measurement.error_counts(kinds)
            assumed = 'none' if not assumed else 'map[' + ' '.join(f'{k}:1' for k in assumed) + ']'
            baseline = [{'label': 'baseline', 'deployedRevision': stable, 'pass': True, 'score': sc, 'errors': assumed,
                         'finishedAt': '2026-10-17T09:00:00Z', 'stableBundleId': None}
                        for sc in record['ruleDecision'].get('baselineScores') or []]
        out[key] = (baseline, candidate, stable)
    return out


def judge(rule):
    return {key: measurement.assess(b, c, stable, None, min_bp=300, minimum=2, max_age=10 ** 7, rule=rule)['decision']
            for key, (b, c, stable) in load_records().items()}


class RulesOnRecords(unittest.TestCase):
    def test_records_present(self):
        self.assertGreaterEqual(len(load_records()), 15)

    def test_v2_blocks_on_missing_denominators(self):
        v2 = judge('v2')
        # Every isucon14/isucon13 candidate carried warnings and no request denominator.
        self.assertEqual([k for k, d in v2.items() if d == 'promote'], ['isucon12-qualify/004', 'isucon12-qualify/005'])

    def test_v3_decisions(self):
        v3 = judge('v3')
        self.assertEqual({k for k, d in v3.items() if d == 'promote'},
                         {'isucon12-qualify/004', 'isucon12-qualify/005', 'isucon13/001', 'isucon13/002',
                          'isucon14/002', 'isucon14/005'})
        self.assertEqual({k for k, d in v3.items() if d == 'reject'},
                         {'isucon12-qualify/001', 'isucon14/003', 'isucon14/004'})
        # 13/003 and 14/007: an error family the stable baseline never showed
        # (timeouts; warning 26) appeared on the candidate, so v3 asks for an
        # investigation instead of deciding on the score.
        self.assertEqual({k for k, d in v3.items() if d == 'inconclusive'},
                         {'isucon12-qualify/002', 'isucon12-qualify/003', 'isucon13/003',
                          'isucon14/001', 'isucon14/006', 'isucon14/007'})

    def test_v3_matches_the_final_decisions_except_overrides_and_new_error_families(self):
        """v3 agrees with every recorded non-override final decision, except where
        the candidate showed an error family absent from the stable baseline."""
        v3 = judge('v3')
        disagreements = []
        for path in sorted(glob.glob(os.path.join(ROOT, 'knowledge', 'records', '*', '*.json'))):
            record = json.load(open(path))
            if 'ruleDecision' not in record or record.get('override'):
                continue
            key = os.path.basename(os.path.dirname(path)) + '/' + record['experimentId'][:3]
            if v3[key] != record['finalDecision']:
                disagreements.append((key, v3[key], record['finalDecision']))
        self.assertEqual(disagreements, [('isucon13/003', 'inconclusive', 'promote'),
                                         ('isucon14/007', 'inconclusive', 'reject')])


class ErrorFormats(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(measurement.error_counts('map[25:13 26:1]'), {'25': 13, '26': 1})
        self.assertEqual(measurement.error_counts('map[25:13,26:1]'), {'25': 13, '26': 1})
        self.assertEqual(measurement.error_counts('一般エラー:POST:/api/iconx1,一般エラー:POST:/api/livestream/:id/reportx3'),
                         {'一般エラー:POST:/api/icon': 1, '一般エラー:POST:/api/livestream/:id/report': 3})
        self.assertEqual(measurement.error_counts('errors=3,critical=0'), {'errors': 3})
        self.assertEqual(measurement.error_counts('none'), {})
        self.assertIsNone(measurement.error_counts('unknown'))

    def test_surge_without_denominators_blocks_only_v3_style(self):
        b = [{'pass': True, 'score': 100, 'errors': 'map[25:4]'}]
        c = [{'pass': True, 'score': 300, 'errors': 'map[25:40]'}]
        self.assertEqual(measurement.quality(b, c, require_denominators=False)['status'], 'unknown')
        c = [{'pass': True, 'score': 300, 'errors': 'map[25:6]'}]
        self.assertEqual(measurement.quality(b, c, require_denominators=False)['status'], 'pass')
        self.assertEqual(measurement.quality(b, c, require_denominators=True)['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
