#!/usr/bin/env python3
"""Check this member's clone/model and join the configured central ledger.

The model probe runs in an empty temporary directory; no source is sent.
Only readiness flags are printed, never provider output or AWS credentials.
--offline checks files only and deliberately does not report a joined member.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]


def run(command, cwd, timeout=45):
    return subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=timeout, env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))


def probe_command(provider, model, nonce):
    prompt = 'Reply with exactly ' + nonce + '. Do not use tools, access files, or run commands.'
    if provider == 'claude':
        args = ['claude', '-p', '--safe-mode', '--no-session-persistence', '--tools', '',
                '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                '--permission-mode', 'plan', '--output-format', 'json']
    else:
        args = ['codex', '-a', 'never', 'exec', '--ephemeral', '--skip-git-repo-check',
                '--sandbox', 'read-only', '--json', '--color', 'never']
    if model:
        args += ['--model', model]
    return [*args, prompt]


def probe_succeeded(provider, result, nonce):
    if result.returncode:
        return False
    try:
        if provider == 'claude':
            data = json.loads(result.stdout)
            return not data.get('is_error') and data.get('result', '').strip() == nonce
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        return (any(e.get('type') == 'turn.completed' for e in events)
                and not any(e.get('type') in ('turn.failed', 'error') for e in events)
                and any(e.get('item', {}).get('type') == 'agent_message'
                        and e['item'].get('text', '').strip() == nonce for e in events))
    except (ValueError, TypeError, AttributeError):
        return False


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', default=os.getcwd())
    p.add_argument('--host-config', default=str(ROOT / 'team/environments/competition/control-host.json'))
    p.add_argument('--agent', required=True)
    p.add_argument('--provider', required=True, choices=('claude', 'codex'))
    p.add_argument('--model', help='optional command-only override; never changes global settings')
    p.add_argument('--offline', action='store_true')
    a = p.parse_args()
    result = {'joined': False, 'agent': a.agent, 'checks': {}, 'offline': a.offline}
    stage = 'configuration'
    try:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', a.agent):
            raise ValueError('use a unique session ID of at most 80 letters/digits/._-')
        config = json.loads(Path(a.host_config).read_text())
        version = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())['version']
        if json.loads((ROOT / '.codex-plugin/plugin.json').read_text())['version'] != version:
            raise ValueError('the plugin manifests disagree on version')
        result['plugin_version'] = version
        result['environment'] = {k: config.get(k) for k in ('account_id', 'region', 'instance_id', 'repository')}
        result['checks']['configuration'] = True
        stage = 'repository'
        project = Path(a.project).resolve()
        revision = run(['git', 'rev-parse', '--show-toplevel'], project, 10)
        origin = run(['git', 'remote', 'get-url', 'origin'], project, 10)
        if revision.returncode or origin.returncode:
            raise ValueError('select the competition clone with an origin remote')
        expected = config.get('repository')
        if expected and not origin.stdout.strip().removesuffix('.git').endswith(('/' + expected, ':' + expected)):
            raise ValueError('clone origin does not match this environment repository')
        result['checks']['repository'] = True
        if a.offline:
            result['next'] = 'Run without --offline to probe the model, Git access, and central ledger.'
        else:
            stage = 'git_access'
            if run(['git', 'ls-remote', '--exit-code', 'origin', 'HEAD'], project, 20).returncode:
                raise ValueError('Git read access failed; check this member authentication')
            result['checks'][stage] = True
            stage = 'model'
            nonce = 'KAIZEN_JOIN_' + uuid.uuid4().hex
            with tempfile.TemporaryDirectory(prefix='kaizen-join-') as directory:
                probe = run(probe_command(a.provider, a.model, nonce), directory)
            if not probe_succeeded(a.provider, probe, nonce):
                raise ValueError('model probe failed; check provider login and model availability in this CLI')
            result['checks'][stage] = True
            stage = 'control_host'
            remote = run([sys.executable, str(ROOT / 'scripts/team/control.py'), '--host-config', a.host_config,
                          'join', '--agent', a.agent, '--provider', a.provider, '--plugin-version', version], project, 60)
            if remote.returncode:
                # Do not relay stdout/stderr: a provider or AWS error can contain sensitive context.
                raise ValueError('control join failed; check AWS login/account, SSM access, paths and release alignment')
            result['queue'] = json.loads(remote.stdout)
            result['checks'][stage] = True
            result['joined'] = True
            result['next'] = 'Read POLICY/RUNBOOK, inspect queue and task-list, then continue autonomously.'
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        result['failed_check'] = stage
        result['error'] = str(error) if isinstance(error, ValueError) else 'check unavailable or timed out; no join confirmed'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['joined'] or (a.offline and 'failed_check' not in result) else 2


if __name__ == '__main__':
    sys.exit(main())
