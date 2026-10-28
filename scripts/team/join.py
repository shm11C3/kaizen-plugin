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
sys.path.insert(0, str(ROOT / 'scripts/team'))
import control  # noqa: E402


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


def probe_failure(provider, result):
    """Classify a failed probe without returning any provider text."""
    text = result.stdout + '\n' + result.stderr
    try:
        if provider == 'claude':
            data = json.loads(result.stdout)
            text = str(data.get('result', '')) if data.get('is_error') else text
    except (ValueError, TypeError, AttributeError):
        pass
    lowered = text.lower()
    if re.search(r'authenticat|log ?in|oauth|unauthori[sz]ed|\b401\b|api key|credential', lowered):
        return 'auth'
    if re.search(r'model|not available|not found|\b404\b|access denied|\b403\b', lowered):
        return 'model_unavailable'
    if result.returncode == 0:
        return 'mismatch'
    return 'cli_error'


PROBE_ADVICE = {
    'auth': 'model probe failed (auth); log in again in this CLI (desktop app sessions use separate credentials)',
    'model_unavailable': 'model probe failed (model_unavailable); check the model name and account access',
    'mismatch': 'model probe failed (mismatch); the CLI answered but not with the probe nonce',
    'cli_error': 'model probe failed (cli_error); run the provider CLI once by hand to see why',
    'timeout': 'model probe failed (timeout); the CLI did not answer in time',
}


def github_login_warning(agent, project):
    """Session IDs start with the exact GitHub login; a case slip splits branches and claims."""
    try:
        login = run(['gh', 'api', 'user', '--jq', '.login'], project, 15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    login = login.stdout.strip() if login.returncode == 0 else ''
    if login and not agent.startswith(login + '-') and agent.lower().startswith(login.lower() + '-'):
        return 'session ID prefix differs in case from GitHub login ' + login + '; use ' + login + agent[len(login):]
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', default=os.getcwd())
    where = p.add_mutually_exclusive_group()
    where.add_argument('--host-config', help='explicit host config path')
    where.add_argument('--env', help='environment name: team/environments/NAME or ~/.config/kaizen/NAME/control-host.json')
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
        a.host_config = str(control.host_config_path(a.env, a.host_config))
        config = json.loads(Path(a.host_config).read_text())
        version = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())['version']
        if json.loads((ROOT / '.codex-plugin/plugin.json').read_text())['version'] != version:
            raise ValueError('the plugin manifests disagree on version')
        result['plugin_version'] = version
        result['environment'] = {'name': control.environment_label(config, a.host_config), 'host_config': a.host_config,
                                 **{k: config.get(k) for k in ('account_id', 'region', 'instance_id', 'repository')}}
        if config.get('discord'):
            # Snowflakes only: the MCP cannot list servers or find channels by name.
            result['discord'] = config['discord']
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
        warning = github_login_warning(a.agent, project)
        if warning:
            result['warnings'] = [warning]
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
                try:
                    probe = run(probe_command(a.provider, a.model, nonce), directory)
                except subprocess.TimeoutExpired:
                    result['model_failure'] = 'timeout'
                    raise ValueError(PROBE_ADVICE['timeout'])
            if not probe_succeeded(a.provider, probe, nonce):
                result['model_failure'] = probe_failure(a.provider, probe)
                raise ValueError(PROBE_ADVICE[result['model_failure']])
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
