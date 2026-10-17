import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('measurement', ROOT / 'scripts/measurement.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sample(score, rev, errors='none', requests=None, **changes):
    return dict(score=score, deployedRevision=rev, errors=errors, requests=requests,
                stableBundleId='bundle', resourceFingerprints={}, finishedAt=m.now().isoformat(),
                **{'pass': True}, **changes)


class MeasurementTests(unittest.TestCase):
    def assess(self, errors='none', requests=None):
        return m.assess([sample(900, 'stable'), sample(1000, 'stable')],
                        [sample(2900, 'candidate', errors, requests), sample(3000, 'candidate', errors, requests)],
                        'stable', 'bundle')

    def test_real_rehearsal_score_gain_does_not_waive_unknown_quality(self):
        b = [sample(n, 'stable', 'map[25:3]') for n in (880, 903, 1450)]
        c = [sample(n, 'candidate', f'map[25:{e}]') for n, e in ((2927, 17), (3221, 10), (2861, 16))]
        result = m.assess(b, c, 'stable', 'bundle')
        self.assertEqual(result['decision'], 'inconclusive')
        self.assertEqual(result['nextAction'], 'investigate')
        self.assertTrue(result['qualityBlockPromotion'])

    def test_error_rates_use_denominators_instead_of_counts(self):
        b = [sample(1000, 's', 'map[25:5]', 100)]
        c = [sample(3000, 'c', 'map[25:10]', 1000)]
        self.assertEqual(m.quality(b, c)['status'], 'pass')
        c[0]['requests'] = 100
        self.assertEqual(m.quality(b, c)['status'], 'unknown')
        self.assertEqual(m.quality(b, [sample(3000, 'c', 'map[30:1]', 1000)])['status'], 'unknown')
        self.assertEqual(m.quality(b, c, ('25',))['status'], 'failed')

    def test_unknown_errors_are_not_zero(self):
        self.assertIsNone(m.error_counts('unparsed warnings'))
        self.assertIsNone(m.error_counts(''))
        self.assertIsNone(m.error_counts(None))
        self.assertTrue(self.assess('unparsed warnings')['qualityBlockPromotion'])

    def test_normal_improvement_and_noise_overlap(self):
        self.assertEqual(self.assess()['decision'], 'promote')
        result = m.assess([sample(n, 'stable') for n in (880, 903, 1450)],
                          [sample(n, 'candidate') for n in (1218, 1243, 1366)], 'stable', 'bundle')
        self.assertEqual(result['decision'], 'inconclusive')
        self.assertEqual(result['nextAction'], 'remeasure')

    def test_denominator_provenance_must_match_when_samples_record_it(self):
        b = [sample(n,'stable',requestSource={'id':'counter-A'}) for n in (900,1000)]
        for rule in ('v2','v3'):
            for source in ({'id':'counter-B'}, None):
                with self.subTest(rule=rule,source=source):
                    c = [sample(n,'candidate',requestSource=source) for n in (2900,3000)]
                    result = m.assess(b,c,'stable','bundle',rule=rule)
                    self.assertEqual(result['decision'],'inconclusive')
                    self.assertEqual(result['nextAction'],'remeasure')
                    self.assertIn('denominator sources differ',result['reason'])
            c = [sample(n,'candidate',requestSource={'id':'counter-A'}) for n in (2900,3000)]
            self.assertEqual(m.assess(b,c,'stable','bundle',rule=rule)['decision'],'promote')

    def test_correctness_missing_samples_mixed_revision_and_stale_conditions(self):
        b = [sample(900, 'stable'), sample(1000, 'stable')]
        c = [sample(2000, 'candidate')]
        self.assertEqual(m.assess(b, c, 'stable', 'bundle')['decision'], 'inconclusive')
        c[0]['pass'] = False
        self.assertEqual(m.assess(b, c, 'stable', 'bundle')['decision'], 'reject')
        c = [sample(2000, 'c1'), sample(2100, 'c2')]
        self.assertTrue(m.assess(b, c, 'stable', 'bundle')['qualityBlockPromotion'])
        c[1]['deployedRevision'] = 'c1'; c[1]['stableBundleId'] = 'other'
        self.assertTrue(m.assess(b, c, 'stable', 'bundle')['qualityBlockPromotion'])
        c[1]['stableBundleId'] = 'bundle'; c[1]['resourceFingerprints'] = {'db': 'different'}
        self.assertTrue(m.assess(b, c, 'stable', 'bundle')['qualityBlockPromotion'])
        for row in b: row['finishedAt'] = '2000-01-01T00:00:00Z'
        self.assertEqual(m.assess(b, c, 'stable', 'bundle')['staleBaselineSamplesIgnored'], 2)

    def test_physical_budget_counts_no_result_recovery_and_closed_experiment(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'attempts.jsonl'
            def take(exp, label, candidate=0):
                return m.reserve(path, exp, label, 'rev', 4, 6, 6, 1, candidate)
            for n in range(3): take('E1', f'candidate-{n}', 1)
            with self.assertRaises(ValueError): take('E1', 'one-more-candidate', 1)
            take('E1', 'baseline-recovery')
            with self.assertRaises(ValueError): take('E1', 'baseline-after-close')
            # No result was written for any attempt: they all still count.
            take('E2', 'candidate', 1); take(None, 'baseline')
            with self.assertRaises(ValueError): take('E3', 'candidate', 1)
            self.assertEqual(len(m.attempts(path)), 6)


if __name__ == '__main__':
    unittest.main()
