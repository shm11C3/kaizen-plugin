import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


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
        with self.assertRaises(ValueError):
            control.remote_command({'remote_plugin_root': '/srv/test/plugin', 'state_db': '/srv/test/db'}, 'target', [])


if __name__ == '__main__':
    unittest.main()
