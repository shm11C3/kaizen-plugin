import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('comparison', ROOT / 'scripts/compare.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def trial():
    return dict(variant='fixture-only', startedAt='2026-10-17T00:00:00Z',
                conditions=dict(problem='test', initialRevision='same-source', environmentSpec={'app': 'same'},
                                models={'workers': ['same-model']}, agentCount=3, durationMinutes=120,
                                inferenceBudget={'mode': 'fixed-token-budget', 'tokens': 100},
                                humanPolicy='record all steering', externalHintsHash='none',
                                measurementHarnessRevision='fixed'),
                firstVerifiedPromotion={'at': '2026-10-17T00:10:00Z', 'artifact': 'fixture: adoption'},
                finalVerification=dict(revision='selected', selectedAt='2026-10-17T01:59:00Z',
                                       restartPassed=True, correctnessPassed=True, scores=[100, 110], artifact='fixture: final'),
                humanInterventions=[], failureRecoveryIntervals=[])


class ComparisonTests(unittest.TestCase):
    def test_comparison_refuses_resource_or_initial_state_mismatches(self):
        for key, value in [('initialRevision', 'different'), ('agentCount', 1), ('models', {'worker': 'other'}),
                           ('durationMinutes', 180), ('measurementHarnessRevision', 'changed')]:
            right = trial()
            right['conditions'][key] = value
            with self.assertRaisesRegex(ValueError, 'conditions differ'):
                comparison.compare(trial(), right)

    def test_unknown_is_not_zero_and_failed_restart_has_no_valid_final_score(self):
        right = trial()
        right.update(firstVerifiedPromotion=None, humanInterventions=None, failureRecoveryIntervals=None)
        right['finalVerification']['restartPassed'] = False
        result = comparison.compare(trial(), right)['results'][1]
        for key in ('final_valid_score_median', 'first_verified_promotion_minutes',
                    'human_interventions', 'failure_recovery_minutes'):
            self.assertIsNone(result[key])
        self.assertEqual(comparison.summarize(trial())['final_valid_score_median'], 105)

    def test_failure_recovery_overlap_is_counted_once(self):
        report = trial()
        report['failureRecoveryIntervals'] = [dict(startedAt='2026-10-17T00:10:00Z', endedAt='2026-10-17T00:20:00Z', artifact='fixture: failed deploy'),
                                              dict(startedAt='2026-10-17T00:15:00Z', endedAt='2026-10-17T00:25:00Z', artifact='fixture: restore')]
        self.assertEqual(comparison.summarize(report)['failure_recovery_minutes'], 15)

    def test_out_of_deadline_and_unsubstantiated_results_are_rejected(self):
        report = trial()
        report['finalVerification']['selectedAt'] = '2026-10-17T02:01:00Z'
        with self.assertRaises(ValueError):
            comparison.summarize(report)
        report = trial()
        report['firstVerifiedPromotion']['artifact'] = ''
        with self.assertRaises(ValueError):
            comparison.summarize(report)
        report = trial()
        report['humanInterventions'] = [dict(at='2026-10-17T03:00:00Z', artifact='fixture: late steering')]
        with self.assertRaises(ValueError):
            comparison.summarize(report)
        report = trial()
        report['finalVerification']['scores'] = [100, float('nan')]
        with self.assertRaises(ValueError):
            comparison.summarize(report)


if __name__ == '__main__':
    unittest.main()
