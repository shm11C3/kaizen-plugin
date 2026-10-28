import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/team'))


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ('scripts/team/' + name + '.py'))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class JoinTests(unittest.TestCase):
    def test_model_probe_requires_actual_successful_response(self):
        join = module('join')
        good = subprocess.CompletedProcess([], 0, json.dumps({'result': 'NONCE', 'is_error': False}), '')
        self.assertTrue(join.probe_succeeded('claude', good, 'NONCE'))
        good.stdout = json.dumps({'result': 'OAuth expired', 'is_error': True})
        self.assertFalse(join.probe_succeeded('claude', good, 'NONCE'))
        good.stdout = '\n'.join(json.dumps(e) for e in [
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'NONCE'}},
            {'type': 'turn.completed'}])
        self.assertTrue(join.probe_succeeded('codex', good, 'NONCE'))
        good.stdout += '\n' + json.dumps({'type': 'turn.failed'})
        self.assertFalse(join.probe_succeeded('codex', good, 'NONCE'))
        for provider in ('claude', 'codex'):
            cmd = join.probe_command(provider, 'explicit-model', 'NONCE')
            self.assertIn('explicit-model', cmd)
            self.assertNotIn('--dangerously-skip-permissions', cmd)
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', cmd)

    def test_probe_failures_are_classified_without_provider_text(self):
        join = module('join')
        done = lambda code, out, err='': subprocess.CompletedProcess([], code, out, err)
        expired = done(1, json.dumps({'result': 'Failed to authenticate. OAuth token has expired', 'is_error': True}))
        self.assertEqual(join.probe_failure('claude', expired), 'auth')
        self.assertEqual(join.probe_failure('codex', done(1, '', 'error: model gpt-x not found')), 'model_unavailable')
        self.assertEqual(join.probe_failure('claude', done(0, json.dumps({'result': 'hello', 'is_error': False}))), 'mismatch')
        self.assertEqual(join.probe_failure('codex', done(3, '', 'segfault')), 'cli_error')
        self.assertTrue(all(k in join.PROBE_ADVICE[k] for k in join.PROBE_ADVICE))
        self.assertNotIn('OAuth token', join.PROBE_ADVICE['auth'])

    def test_session_prefix_case_slip_against_github_login_warns(self):
        join = module('join')
        original = join.run
        self.addCleanup(setattr, join, 'run', original)
        join.run = lambda *a, **k: subprocess.CompletedProcess([], 0, 'shm11C3\n', '')
        self.assertIn('shm11C3-claude-01', join.github_login_warning('shm11c3-claude-01', '.'))
        self.assertIsNone(join.github_login_warning('shm11C3-claude-01', '.'))
        self.assertIsNone(join.github_login_warning('agent2-claude', '.'))
        join.run = lambda *a, **k: subprocess.CompletedProcess([], 1, '', 'gh: not logged in')
        self.assertIsNone(join.github_login_warning('shm11c3-claude-01', '.'))

    def test_env_name_resolves_bundled_then_per_pc_config(self):
        import os, tempfile
        control = module('control')
        self.assertEqual(control.host_config_path('competition').parent.name, 'competition')
        self.assertEqual(control.host_config_path('x', '/explicit.json'), Path('/explicit.json'))
        with tempfile.TemporaryDirectory() as directory:
            old = os.environ.get('KAIZEN_CONFIG_DIR')
            os.environ['KAIZEN_CONFIG_DIR'] = directory
            self.addCleanup(lambda: os.environ.pop('KAIZEN_CONFIG_DIR') if old is None else os.environ.update(KAIZEN_CONFIG_DIR=old))
            with self.assertRaisesRegex(ValueError, 'isu14-practice/control-host.json'):
                control.host_config_path('isu14-practice')
            path = Path(directory) / 'isu14-practice/control-host.json'
            path.parent.mkdir()
            path.write_text('{}')
            self.assertEqual(control.host_config_path('isu14-practice'), path)
            self.assertEqual(control.environment_label({}, path), 'isu14-practice')
            self.assertEqual(control.environment_label({'name': 'practice-1029'}, path), 'practice-1029')
            with self.assertRaises(ValueError):
                control.host_config_path('../competition')

    def test_watch_reports_only_this_sessions_task_changes(self):
        watch = module('watch')
        tasks = [{'id': 'T-0001', 'owner': 'me', 'status': 'READY', 'reason': 'candidate', 'source_sha': 'a'},
                 {'id': 'T-0002', 'owner': 'other', 'status': 'READY', 'reason': 'x', 'source_sha': 'b'}]
        before = watch.mine(tasks, 'me')
        self.assertEqual(watch.changes(before, before), [])
        tasks[1]['status'] = 'ACCEPTED'
        self.assertEqual(watch.changes(before, watch.mine(tasks, 'me')), [])
        tasks[0].update(status='NEEDS_MEASUREMENT', reason='integrator: split index and retry')
        found = watch.changes(before, watch.mine(tasks, 'me'))
        self.assertEqual([(c['id'], c['after']['status']) for c in found], [('T-0001', 'NEEDS_MEASUREMENT')])
        tasks[1]['owner'] = 'me'
        self.assertIn('T-0002', [c['id'] for c in watch.changes(before, watch.mine(tasks, 'me'))])

    def test_configurable_remote_paths_need_no_dispatch_adapter(self):
        control = module('control')
        config = {'remote_plugin_root': '/srv/test/plugin', 'state_db': '/srv/test/state.sqlite3',
                  'target_config': '/srv/test/target.json'}
        command = shlex.split(control.remote_command(config, 'target', ['--agent', 'a', '--token', 'token', 'status']))
        self.assertEqual(command[command.index('--db') + 1], '/srv/test/state.sqlite3')
        self.assertEqual(command[command.index('--config') + 1], '/srv/test/target.json')
        self.assertNotIn('/srv/isucon/state/team.sqlite3', command)
        ledger = shlex.split(control.remote_command(config, 'queue', []))
        self.assertEqual(ledger[-1], 'queue')
        config['environment'] = 'lane-a'
        lane = shlex.split(control.remote_command(config, 'target', ['--agent', 'a', '--token', 'token', 'status']))
        self.assertEqual(lane[lane.index('--environment') + 1], 'lane-a')
        self.assertEqual(lane[lane.index('--db') + 1], '/srv/test/state.sqlite3')
        with self.assertRaises(ValueError):
            control.remote_command({'remote_plugin_root': '/srv/test/plugin', 'state_db': '/srv/test/db'}, 'target', [])


if __name__ == '__main__':
    unittest.main()
