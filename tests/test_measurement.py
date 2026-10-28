import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

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

    def test_rare_new_error_type_promotes_with_stabilization(self):
        b = [sample(n, 'stable', 'map[25:3]', 17000) for n in (940, 1000)]
        c = [sample(n, 'candidate', e, 17000) for n, e in ((1228, 'map[25:2]'), (1285, 'map[25:1 26:1]'))]
        result = m.assess(b, c, 'stable', 'bundle', tolerate=(2, 1))
        self.assertEqual(result['decision'], 'promote')
        self.assertFalse(result['qualityBlockPromotion'])
        self.assertEqual(result['stabilizationRequired'], {'26': 1})
        self.assertIn('stabilization task', result['reason'])
        # Disabled, too many, too frequent, a correctness type or no denominators still hold.
        self.assertTrue(m.assess(b, c, 'stable', 'bundle')['qualityBlockPromotion'])
        many = [sample(n, 'candidate', 'map[26:2]', 17000) for n in (1228, 1285)]
        self.assertTrue(m.assess(b, many, 'stable', 'bundle', tolerate=(2, 1))['qualityBlockPromotion'])
        dense = [sample(n, 'candidate', 'map[26:1]', 1000) for n in (1228, 1285)]
        self.assertTrue(m.assess(b, dense, 'stable', 'bundle', tolerate=(2, 1))['qualityBlockPromotion'])
        self.assertEqual(m.assess(b, c, 'stable', 'bundle', forbidden=('26',), tolerate=(2, 1))['decision'], 'reject')
        bare = [sample(n, 'candidate', e) for n, e in ((1228, 'map[25:2]'), (1285, 'map[26:1]'))]
        self.assertTrue(m.assess(b, bare, 'stable', 'bundle', tolerate=(2, 1))['qualityBlockPromotion'])
        # A known type whose rate rises is still a regression, tolerated or not.
        worse = [sample(n, 'candidate', 'map[25:30 26:1]', 17000) for n in (1228, 1285)]
        self.assertTrue(m.assess(b, worse, 'stable', 'bundle', tolerate=(2, 1))['qualityBlockPromotion'])
        self.assertIsNone(m.parse_tolerance('0'))
        self.assertEqual(m.parse_tolerance('2:1'), (2, 1.0))

    def test_multifold_gain_with_rising_known_errors_promotes_with_stabilization(self):
        # Practice T-0001 index-only: 2946/3245 against ~992 with error25 16/10 and a new 26:1.
        b = [sample(n, 'stable', e, 17000) for n, e in ((940, 'map[25:3]'), (992, 'none'), (1000, 'none'))]
        c = [sample(n, 'candidate', e, 50000) for n, e in ((2946, 'map[25:16]'), (3245, 'map[25:10 26:1]'))]
        held = m.assess(b, c, 'stable', 'bundle', tolerate=(2, 1))
        self.assertTrue(held['qualityBlockPromotion'])
        result = m.assess(b, c, 'stable', 'bundle', tolerate=(2, 1), stabilize_gain_bp=10000)
        self.assertEqual(result['decision'], 'promote')
        self.assertEqual(result['stabilizationRequired'], {'25': 'rate', '26': 1})
        # One multi-fold sample asks for the second instead of stopping at "investigate".
        one = m.assess(b, c[:1], 'stable', 'bundle', tolerate=(2, 1), stabilize_gain_bp=10000)
        self.assertEqual((one['decision'], one['nextAction']), ('inconclusive', 'remeasure'))
        self.assertEqual(m.assess(b, c[:1], 'stable', 'bundle', tolerate=(2, 1))['nextAction'], 'investigate')
        # Below the gain, with a correctness type, or with an untolerated new type it still holds.
        small = [sample(n, 'candidate', 'map[25:16]', 50000) for n in (1500, 1600)]
        self.assertTrue(m.assess(b, small, 'stable', 'bundle', tolerate=(2, 1), stabilize_gain_bp=10000)['qualityBlockPromotion'])
        self.assertEqual(m.assess(b, c, 'stable', 'bundle', forbidden=('25',), stabilize_gain_bp=10000)['decision'], 'reject')
        # A new type beyond the count tolerance also stabilizes at a multi-fold gain.
        self.assertEqual(m.assess(b, c, 'stable', 'bundle', stabilize_gain_bp=10000)['stabilizationRequired'], {'25': 'rate', '26': 'rate'})

    def test_multifold_gain_with_a_new_error_type_promotes_with_stabilization(self):
        # Practice T-0001 retest: baseline 776/1007 without errors, candidate 3028 with error25x13.
        b = [sample(n, 'stable', 'none', 17000) for n in (776, 1007)]
        c = [sample(n, 'candidate', 'map[25:13]', 50000) for n in (3028, 3100)]
        self.assertEqual(m.assess(b, c[:1], 'stable', 'bundle', tolerate=(2, 1), stabilize_gain_bp=10000)['nextAction'], 'remeasure')
        result = m.assess(b, c, 'stable', 'bundle', tolerate=(2, 1), stabilize_gain_bp=10000)
        self.assertEqual(result['decision'], 'promote')
        self.assertEqual(result['stabilizationRequired'], {'25': 'rate'})
        self.assertTrue(m.assess(b, c, 'stable', 'bundle', tolerate=(2, 1))['qualityBlockPromotion'])

    def test_overlapping_gain_with_rising_soft_errors_remeasures(self):
        # Practice T-0004: median +15% but the worse sample overlapped the baseline.
        b = [sample(n, 'stable', 'map[26:1]', 63000) for n in (8518, 8999)]
        c = [sample(n, 'candidate', 'map[26:2]', 70000) for n in (8120, 12090)]
        result = m.assess(b, c, 'stable', 'bundle', tolerate=(2, 1), stabilize_gain_bp=300)
        self.assertEqual((result['decision'], result['nextAction']), ('inconclusive', 'remeasure'))

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

    def test_zero_caps_still_record_every_physical_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'attempts.jsonl'
            # Exceed the old defaults without a result: accounting stays intact.
            for n in range(125):
                m.reserve(path, 'E1' if n < 124 else None, f'run-{n}', 'rev', 0, 0, 0, 1, n < 124)
            rows = m.attempts(path)
            self.assertEqual(len(rows), 125)
            self.assertEqual(len({row['id'] for row in rows}), 125)
            self.assertIsNone(rows[-1]['experiment'])

    def test_each_explicit_cap_preserves_stable_capacity_without_exceeding_it(self):
        for axis in range(3):
            for limit, reserve_slots in ((3, 1), (3, 0), (1, 1)):
                with self.subTest(axis=axis, limit=limit, reserve=reserve_slots), tempfile.TemporaryDirectory() as d:
                    path = Path(d) / 'attempts.jsonl'
                    caps = [0, 0, 0]
                    caps[axis] = limit
                    for n in range(limit - reserve_slots):
                        m.reserve(path, 'E1', f'candidate-{n}', 'rev', *caps, reserve_slots, True)
                    before = path.read_bytes() if path.exists() else None
                    with self.assertRaises(ValueError):
                        m.reserve(path, 'E1', 'blocked-candidate', 'rev', *caps, reserve_slots, True)
                    self.assertEqual(path.read_bytes() if path.exists() else None, before)
                    for n in range(reserve_slots):
                        m.reserve(path, 'E1', f'baseline-recovery-{n}', 'rev', *caps, reserve_slots, False)
                    with self.assertRaises(ValueError):
                        m.reserve(path, 'E1', 'baseline-after-close', 'rev', *caps, reserve_slots, False)
                    self.assertEqual(len(m.attempts(path)), limit)

    def test_hour_window_expires_but_total_and_closed_attempts_remain(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'attempts.jsonl'
            fixed = m.now()
            old = {'id': 'old-no-result', 'experiment': 'closed', 'label': 'candidate', 'revision': 'rev',
                   'startedAt': (fixed - m.datetime.timedelta(hours=2)).isoformat()}
            path.write_text(json.dumps(old) + '\n')
            with mock.patch.object(m, 'now', return_value=fixed):
                m.reserve(path, 'new', 'candidate', 'rev', 0, 2, 1, 0, True)
                with self.assertRaisesRegex(ValueError, 'hour'):
                    m.reserve(path, None, 'baseline', 'rev', 0, 0, 1, 0, False)
                with self.assertRaisesRegex(ValueError, 'total'):
                    m.reserve(path, 'another', 'candidate', 'rev', 0, 2, 0, 0, True)
            self.assertEqual(m.attempts(path)[0], old)

    def test_invalid_caps_do_not_mutate_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'attempts.jsonl'
            m.reserve(path, 'E1', 'candidate', 'rev', 0, 0, 0, 1, True)
            before = path.read_bytes()
            for axis in range(4):
                values = [0, 0, 0, 1]
                values[axis] = -1
                with self.subTest(axis=axis), self.assertRaises(ValueError):
                    m.reserve(path, 'E1', 'invalid', 'rev', *values, True)
                self.assertEqual(path.read_bytes(), before)


class BudgetConfigurationTests(unittest.TestCase):
    def load(self, project):
        env = dict(os.environ, KAIZEN_PROJECT=str(project), KAIZEN_PLUGIN_ROOT=str(ROOT))
        for name in ('MAX_BENCH_PER_EXP', 'MAX_BENCH_TOTAL', 'MAX_BENCH_PER_HOUR',
                     'MAX_EXP_PER_HOUR', 'RECOVERY_BENCH_RESERVE'):
            env.pop(name, None)
        return subprocess.run(['bash', '-c', '. "$1"; load_config; printf "%s\\n" '
                               '"$MAX_BENCH_PER_EXP" "$MAX_BENCH_TOTAL" "$MAX_BENCH_PER_HOUR" '
                               '"$MAX_EXP_PER_HOUR" "$RECOVERY_BENCH_RESERVE"', 'budget-fixture',
                               str(ROOT / 'scripts/lib.sh')], env=env, capture_output=True, text=True)

    def test_defaults_disable_caps_explicit_values_survive_and_invalid_settings_fail(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            folder = project / '.kaizen'
            folder.mkdir()
            config = folder / 'config.sh'
            base = ('APP_HOST=fixture\nREMOTE_APP_DIR=app\nLOCAL_SYNC_PATHS=app\n'
                    'BUILD_CMD=true\nRESTART_CMD=true\nHEALTH_CMD=true\nBENCH_MODE=manual\n')
            config.write_text(base)
            result = self.load(project)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['0', '0', '0', '0', '1'])
            config.write_text(base + 'MAX_BENCH_PER_EXP=3\nMAX_BENCH_TOTAL=7\nMAX_BENCH_PER_HOUR=4\n'
                              'MAX_EXP_PER_HOUR=2\nRECOVERY_BENCH_RESERVE=1\n')
            result = self.load(project)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['3', '7', '4', '2', '1'])
            for name in ('MAX_BENCH_PER_EXP', 'MAX_BENCH_TOTAL', 'MAX_BENCH_PER_HOUR',
                         'MAX_EXP_PER_HOUR', 'RECOVERY_BENCH_RESERVE'):
                for value in ('-1', 'invalid'):
                    with self.subTest(name=name, value=value):
                        config.write_text(base + f'{name}={value}\n')
                        result = self.load(project)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(name + ' must be a nonnegative integer', result.stderr)


if __name__ == '__main__':
    unittest.main()
