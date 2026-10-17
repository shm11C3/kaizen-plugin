import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('strategy', ROOT / 'scripts/strategy.py')
strategy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(strategy)


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def record(self, i, decision='inconclusive', rule=None, hypothesis='', stable='base', value=None, samples=None, quality=None):
        path = self.root / '.kaizen/experiments' / str(i)
        path.mkdir(parents=True, exist_ok=True)
        record = dict(experimentId=str(i), stableBefore=stable, finalDecision=decision,
                      ruleDecision=dict(decision=rule or decision),
                      manifest=dict(startedAt=f'2026-10-17T00:{i*5:02d}:00Z', hypothesisId=hypothesis,
                                    strategy=dict(parameters={} if value is None else {'connections': value})),
                      closedAt=f'2026-10-17T00:{i*5+4:02d}:00Z')
        if samples is not None:
            record['samples'] = samples
            record['candidateRevision'] = 'candidate'
        if quality is not None:
            record['ruleDecision']['quality'] = {'status': quality}
            record['ruleDecision']['qualityBlockPromotion'] = quality != 'pass'
        (path / 'record.json').write_text(json.dumps(record))

    @staticmethod
    def sample(observed=False, passed=True, errors='none'):
        return dict(label='candidate-profile' if observed else 'candidate',
                    observed=observed, errors=errors,
                    deployedRevision='candidate') | {'pass': passed}

    def test_unmeasured_observed_and_qualified_unadopted_are_not_failed_optimizations(self):
        self.record(0, samples=[], quality='unknown')
        self.record(1, samples=[self.sample(observed=True)], quality='unknown')
        self.record(2, rule='promote', samples=[self.sample(), self.sample()], quality='pass')
        result = strategy.analyze(self.root)
        self.assertFalse(result['review_needed'])
        self.assertEqual(result['closed_experiments'], 3)
        self.assertEqual(result['rule_verified_promotions'], 0)
        self.assertEqual(result['qualified_comparisons'], 1)
        self.assertEqual(result['qualified_unadopted'], 1)
        self.assertEqual(result['measurement_counts'], dict(normal=1, observed_only=1, unmeasured=1, unknown=0))

    def test_quality_or_failed_samples_cannot_be_hidden_by_a_promote_label(self):
        for i in range(3):
            self.record(i, rule='promote', samples=[self.sample(passed=False)], quality='pass')
        result = strategy.analyze(self.root)
        self.assertEqual(result['qualified_comparisons'], 0)
        self.assertEqual(result['quality_issues'], 3)
        self.assertIn('no_verified_gain', [s['kind'] for s in result['signals']])

    def test_observed_failure_remains_visible_without_becoming_a_performance_comparison(self):
        self.record(0, samples=[self.sample(observed=True, passed=False)], quality='unknown')
        result = strategy.analyze(self.root)
        self.assertEqual(result['measurement_counts']['observed_only'], 1)
        self.assertEqual(result['quality_issues'], 1)
        self.assertIn('quality_evidence', [s['kind'] for s in result['signals']])
        self.assertNotIn('no_verified_gain', [s['kind'] for s in result['signals']])

    def test_observed_warning_is_not_erased_by_diagnostic_disposition(self):
        self.record(0, samples=[self.sample(observed=True, errors='map[26:1]')], quality='unknown')
        self.assertEqual(strategy.analyze(self.root)['quality_issues'], 1)

    def test_observed_zero_counts_are_clean_but_unparsed_errors_remain_unknown(self):
        sample = self.sample(observed=True)
        sample['errorCounts'] = {'25': 0}
        self.record(0, samples=[sample], quality='unknown')
        self.assertEqual(strategy.analyze(self.root)['quality_issues'], 0)
        sample['errorCounts'] = 'unparsed summary'
        self.record(0, samples=[sample], quality='unknown')
        self.assertEqual(strategy.analyze(self.root)['quality_issues'], 1)

    def test_normal_samples_with_missing_quality_remain_an_issue(self):
        self.record(0, rule='promote', samples=[self.sample()])
        result = strategy.analyze(self.root)
        self.assertEqual(result['qualified_comparisons'], 0)
        self.assertEqual(result['quality_issues'], 1)
        self.assertIn('quality_evidence', [s['kind'] for s in result['signals']])

    def test_a_qualified_unadopted_comparison_resets_non_gain_history(self):
        for i in range(3):
            self.record(i, 'reject')
        self.record(3, rule='promote', samples=[self.sample(), self.sample()], quality='pass')
        self.assertFalse(strategy.analyze(self.root)['review_needed'])

    def test_three_failed_experiments_trigger_review_and_verified_gain_resets_it(self):
        for i in range(3):
            self.record(i)
        result = strategy.analyze(self.root)
        self.assertIn('no_verified_gain', [s['kind'] for s in result['signals']])
        self.record(3, 'promote')
        self.assertFalse(strategy.analyze(self.root)['review_needed'])
        self.record(4, 'reject')
        self.assertFalse(strategy.analyze(self.root)['review_needed'])

    def test_discretionary_promotion_does_not_establish_verified_gain(self):
        for i in range(2):
            self.record(i, 'reject')
        self.record(2, 'promote', rule='inconclusive')
        self.assertTrue(strategy.analyze(self.root)['review_needed'])

    def test_repeated_hypothesis_and_oscillation_are_scoped_to_the_baseline(self):
        for i, value in enumerate((32, 128, 32)):
            self.record(i, hypothesis='pool-limit', value=value)
        kinds = [s['kind'] for s in strategy.analyze(self.root)['signals']]
        self.assertIn('repeated_hypothesis', kinds)
        self.assertIn('parameter_oscillation', kinds)
        self.record(2, hypothesis='pool-limit', stable='new-base', value=32)
        self.assertNotIn('parameter_oscillation', [s['kind'] for s in strategy.analyze(self.root)['signals']])

    def test_old_retries_do_not_keep_a_new_successful_mechanism_in_review(self):
        self.record(0, hypothesis='old')
        self.record(1, hypothesis='old')
        self.record(2, 'promote', hypothesis='new')
        self.assertFalse(strategy.analyze(self.root)['review_needed'])

    def test_long_unproductive_experiment_triggers_time_review(self):
        self.record(0, 'reject')
        path = self.root / '.kaizen/experiments/0/record.json'
        record = json.loads(path.read_text())
        record['closedAt'] = '2026-10-17T00:31:00Z'
        path.write_text(json.dumps(record))
        self.assertEqual(strategy.analyze(self.root)['signals'][0]['experiment_minutes'], 31)

    def test_previous_session_and_unreadable_history_do_not_become_success(self):
        self.record(0, 'promote')
        (self.root / '.kaizen/state.env').write_text('LOOP_STARTED_AT=2026-10-17T00:05:00Z\n')
        self.record(1, 'reject')
        path = self.root / '.kaizen/experiments/bad'
        path.mkdir()
        (path / 'record.json').write_text('{')
        result = strategy.analyze(self.root)
        self.assertEqual(result['closed_experiments'], 1)
        self.assertEqual(result['rule_verified_promotions'], 0)
        self.assertTrue(result['warnings'])
        self.assertIn('AI investigation', strategy.render_review(result))


if __name__ == '__main__':
    unittest.main()
