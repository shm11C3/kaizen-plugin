import datetime
import hashlib
import json
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/team'))
from control import output_truncated, remote_command
from pipeline import summarize


class PipelineTests(unittest.TestCase):
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

    def claim(self, owner='worker'):
        task = self.call('task-create', '--title', 'Bounded candidate', '--evidence', 'observation.txt')['id']
        self.call('task-claim', '--id', task, '--agent', owner)
        return task

    def stage(self, task, phase='analysis', owner='worker', *options):
        return self.call('task-stage', '--id', task, '--agent', owner,
                         '--phase', phase, '--reason', 'working on the bounded candidate', *options)

    def ready(self, task, sha='2' * 40, owner='worker'):
        return self.call('task-ready', '--id', task, '--agent', owner, '--base', '1' * 40,
                         '--sha', sha, '--review', 'auto', '--reason', 'source-bound tests retained')

    def test_stage_only_appends_an_observation_and_does_not_update_task(self):
        task = self.claim()
        before = self.call('task-list')
        with sqlite3.connect(self.db) as db:
            count = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        stage = self.stage(task, 'validation', 'worker', '--sha', 'A' * 40, '--evidence', 'qa.txt')
        self.assertTrue(stage['observational'])
        self.assertEqual(stage['source_sha'], 'a' * 40)
        self.assertEqual(self.call('task-list'), before)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], count + 1)
            event = db.execute('SELECT at,action,details FROM events ORDER BY id DESC LIMIT 1').fetchone()
        self.assertIsNotNone(datetime.datetime.fromisoformat(event[0]).tzinfo)
        self.assertEqual(event[1], 'task-stage')
        self.assertEqual(json.loads(event[2]), stage)

    def test_ownership_and_claimed_state_are_required(self):
        task = self.claim()
        base = ('task-stage', '--id', task, '--phase', 'analysis', '--reason', 'observation')
        self.assertNotEqual(self.run_cli(*base, '--agent', 'other').returncode, 0)
        self.call('task-handoff', '--id', task, '--agent', 'worker', '--to', 'next', '--reason', 'independent owner')
        self.assertNotEqual(self.run_cli(*base, '--agent', 'worker').returncode, 0)
        self.stage(task, owner='next')
        self.ready(task, owner='next')
        self.assertNotEqual(self.run_cli(*base, '--agent', 'next').returncode, 0)

    def test_source_mismatch_is_visible_and_cannot_relabel_a_validation(self):
        task = self.claim()
        self.stage(task, 'validation', 'worker', '--sha', '3' * 40)
        self.ready(task)
        row = self.call('pipeline-status')['tasks'][0]
        validation = row['stageIntervals'][0]
        self.assertEqual(validation['sourceSha'], '3' * 40)
        self.assertIs(validation['submittedSourceMatch'], False)
        self.assertEqual(row['sourceSha'], '2' * 40)
        self.assertIsNone(row['readyToIntegrationSeconds'])
        self.assertGreaterEqual(row['submittedAgeSeconds'], 0)
        # Stage/evidence observations do not provide an adoption record.
        self.call('env-acquire', '--agent', 'integrator', '--purpose', task)
        result = self.run_cli('task-finish', '--id', task, '--agent', 'integrator',
                              '--result', 'ACCEPTED', '--reason', 'stage is not a proof')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.call('task-list')[0]['status'], 'READY')

    def test_unmeasured_phases_stay_unknown_and_order_is_not_a_gate(self):
        task = self.claim()
        self.stage(task, 'handoff')
        self.stage(task, 'analysis')
        self.stage(task, 'validation', 'worker', '--sha', '2' * 40)
        self.ready(task)
        row = self.call('pipeline-status')['tasks'][0]
        self.assertIsNone(row['phaseSeconds']['implementation'])
        self.assertIs(row['stageIntervals'][-1]['submittedSourceMatch'], True)
        self.assertEqual([s['phase'] for s in row['stageObservations']], ['handoff', 'analysis', 'validation'])
        self.assertIsNotNone(row['workCycles'][0]['claimToReadySeconds'])

    def test_read_only_observer_does_not_migrate_write_events_or_leak_reservations(self):
        self.claim()
        lease = self.call('env-acquire', '--agent', 'integrator', '--purpose', 'private purpose')
        digest = hashlib.sha256(self.db.read_bytes()).hexdigest()
        before = self.db.stat().st_mtime_ns
        result = self.call('pipeline-status')
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), digest)
        self.assertEqual(self.db.stat().st_mtime_ns, before)
        self.assertNotIn(lease['token'], json.dumps(result))
        self.assertNotIn('private purpose', json.dumps(result))
        self.assertIsNone(result['tasks'][0]['phaseSeconds']['analysis'])

    def test_legacy_database_without_events_stays_unchanged_and_unknown(self):
        self.db = Path(self.tmp.name) / 'legacy.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE tasks (id INTEGER PRIMARY KEY,title TEXT,status TEXT,owner TEXT)')
            db.execute('INSERT INTO tasks VALUES (1,"legacy candidate","READY","old-worker")')
        digest = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = self.call('pipeline-status')
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), digest)
        self.assertIsNone(result['tasks'][0]['submittedAt'])
        self.assertIsNone(result['tasks'][0]['submittedAgeSeconds'])
        self.assertIsNone(result['tasks'][0]['unclassifiedClaimedSeconds'])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT name FROM sqlite_master').fetchall(), [('tasks',)])

    def test_missing_database_is_not_created(self):
        self.db = Path(self.tmp.name) / 'new-directory' / 'missing.sqlite3'
        self.assertNotEqual(self.run_cli('pipeline-status').returncode, 0)
        self.assertFalse(self.db.parent.exists())

    def test_cli_has_no_backdating_and_rejects_bad_source_or_empty_reason(self):
        task = self.claim()
        base = ('task-stage', '--id', task, '--agent', 'worker', '--phase', 'analysis')
        for options in (('--reason', 'now', '--at', '2020-01-01T00:00:00Z'),
                        ('--reason', 'now', '--sha', 'short'), ('--reason', ' '),
                        ('--reason', 'now', '--evidence', ' ')):
            self.assertNotEqual(self.run_cli(*base, *options).returncode, 0)
        self.assertEqual(self.call('pipeline-status')['tasks'][0]['stageObservations'], [])

    def test_current_owner_filter_keeps_handoff_history(self):
        task = self.claim()
        self.stage(task)
        self.call('task-handoff', '--id', task, '--agent', 'worker', '--to', 'next', '--reason', 'new owner')
        self.stage(task, 'implementation', 'next')
        self.assertEqual(self.call('pipeline-status', '--agent', 'worker')['tasks'], [])
        rows = self.call('pipeline-status', '--agent', 'next')['tasks']
        self.assertEqual([s['actor'] for s in rows[0]['stageObservations']], ['worker', 'next'])

    def test_control_reports_output_cut_at_the_ssm_limit(self):
        self.assertEqual(output_truncated('{"ok": true}'), '')
        self.assertIn('task-get', output_truncated('x' * 24000))
        self.assertIn('SSM limit', output_truncated('{}', 's3://bucket/key'))

    def test_control_client_passes_through_without_special_dispatch(self):
        config = {'remote_plugin_root': '/srv/plugin', 'state_db': '/srv/state/team.sqlite3',
                  'target_config': '/srv/state/target.json'}
        arguments = ['--id', 'T-0001', '--agent', 'session one', '--phase', 'analysis', '--reason', 'a; b']
        command = shlex.split(remote_command(config, 'task-stage', arguments))
        self.assertEqual(command[-len(arguments) - 1:], ['task-stage', *arguments])
        self.assertEqual(shlex.split(remote_command(config, 'pipeline-status', ['--agent', 'session one']))[-3:],
                         ['pipeline-status', '--agent', 'session one'])


class TimingTests(unittest.TestCase):
    def event(self, n, task_id, at, action, **details):
        return {'id': n, 'at': at, 'actor': details.pop('actor', 'worker'), 'action': action,
                'details': json.dumps({'id': 'T-%04d' % task_id, **details})}

    def report(self, events, rows=None):
        rows = rows or [{'id': 1, 'title': 'candidate', 'owner': 'worker', 'status': 'READY', 'source_sha': 'a' * 40}]
        return summarize(rows, events, datetime.datetime.fromisoformat('2026-10-18T01:00:00+00:00'))

    def test_known_intervals_union_and_unclassified_claim_time(self):
        events = [
            self.event(1, 1, '2026-10-18T00:00:00+00:00', 'task-claim', status='CLAIMED', owner='worker'),
            self.event(2, 1, '2026-10-18T00:10:00+00:00', 'task-stage', phase='analysis'),
            self.event(3, 2, '2026-10-18T00:15:00+00:00', 'task-claim', status='CLAIMED', owner='worker'),
            self.event(4, 2, '2026-10-18T00:20:00+00:00', 'task-stage', phase='implementation'),
            self.event(5, 1, '2026-10-18T00:30:00+00:00', 'task-ready', source_sha='a' * 40),
            self.event(6, 2, '2026-10-18T00:40:00+00:00', 'task-ready', source_sha='b' * 40),
        ]
        rows = [{'id': n, 'title': 'candidate', 'owner': 'worker', 'status': 'READY'} for n in (1, 2)]
        result = self.report(events, rows)
        self.assertEqual(result['knownStageSecondsSum'], 2400)
        self.assertEqual(result['knownStageSecondsUnion'], 1800)
        self.assertEqual(result['tasks'][0]['unclassifiedClaimedSeconds'], 600)
        self.assertEqual(result['tasks'][1]['unclassifiedClaimedSeconds'], 300)
        self.assertEqual(result['tasks'][0]['workCycles'][0]['claimToReadySeconds'], 1800)
        self.assertIsNone(result['phaseUnionSeconds']['validation'])

    def test_clock_reversal_is_unknown_and_never_negative(self):
        events = [
            self.event(1, 1, '2026-10-18T00:20:00+00:00', 'task-claim', status='CLAIMED', owner='worker'),
            self.event(2, 1, '2026-10-18T00:30:00+00:00', 'task-stage', phase='analysis'),
            self.event(3, 1, '2026-10-18T00:10:00+00:00', 'task-ready', source_sha='a' * 40),
        ]
        row = self.report(events)['tasks'][0]
        self.assertTrue(row['timingIssues'])
        self.assertEqual(row['stageIntervals'], [])
        self.assertIsNone(row['unclassifiedClaimedSeconds'])
        self.assertIsNone(row['submittedAgeSeconds'])

    def test_resume_does_not_join_previous_source_validation_to_new_submission(self):
        events = [
            self.event(1, 1, '2026-10-18T00:00:00+00:00', 'task-claim', status='CLAIMED', owner='worker'),
            self.event(2, 1, '2026-10-18T00:10:00+00:00', 'task-stage', phase='validation', source_sha='a' * 40),
            self.event(3, 1, '2026-10-18T00:20:00+00:00', 'task-ready', source_sha='a' * 40),
            self.event(4, 1, '2026-10-18T00:30:00+00:00', 'task-finish', status='NEEDS_MEASUREMENT'),
            self.event(5, 1, '2026-10-18T00:40:00+00:00', 'task-resume', status='CLAIMED', owner='worker'),
            self.event(6, 1, '2026-10-18T00:50:00+00:00', 'task-ready', source_sha='b' * 40),
        ]
        row = self.report(events)['tasks'][0]
        self.assertIs(row['stageIntervals'][0]['submittedSourceMatch'], True)
        self.assertEqual(len(row['workCycles']), 2)
        self.assertEqual(row['workCycles'][1]['unclassifiedSeconds'], 600)
        self.assertEqual(row['workCycles'][1]['claimToReadySeconds'], 600)
        self.assertEqual(row['firstReadyAt'], '2026-10-18T00:20:00+00:00')
        self.assertEqual(row['submittedAt'], '2026-10-18T00:50:00+00:00')

    def test_handoff_preserves_task_claim_cycle_and_closes_owner_stage(self):
        events = [
            self.event(1, 1, '2026-10-18T00:00:00+00:00', 'task-claim', status='CLAIMED', owner='worker'),
            self.event(2, 1, '2026-10-18T00:10:00+00:00', 'task-stage', phase='analysis'),
            self.event(3, 1, '2026-10-18T00:20:00+00:00', 'task-handoff', status='CLAIMED', owner='next'),
            self.event(4, 1, '2026-10-18T00:25:00+00:00', 'task-stage', phase='validation', actor='next'),
            self.event(5, 1, '2026-10-18T00:30:00+00:00', 'task-ready', source_sha='a' * 40, actor='next'),
        ]
        row = self.report(events)['tasks'][0]
        self.assertEqual(len(row['workCycles']), 1)
        self.assertEqual(row['workCycles'][0]['claimToReadySeconds'], 1800)
        self.assertEqual([i['seconds'] for i in row['stageIntervals']], [600, 300])
        self.assertEqual(row['unclassifiedClaimedSeconds'], 900)


if __name__ == '__main__':
    unittest.main()
