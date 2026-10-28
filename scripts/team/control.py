#!/usr/bin/env python3
"""Call the central ledger through AWS SSM without inbound SSH or shared keys."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from environments import environment_name


ROOT = Path(__file__).resolve().parents[2]


def host_config_path(name=None, explicit=None):
    """Resolve --env NAME to one fixed per-PC place so every session passes the same host config."""
    if explicit:
        return Path(explicit)
    name = name or 'competition'
    if not all(part.isalnum() or part in '-_.' for part in name) or name.startswith('.'):
        raise ValueError('environment name must be letters/digits/-_.')
    bundled = ROOT / 'team/environments' / name / 'control-host.json'
    if bundled.exists():
        return bundled
    local = Path(os.environ.get('KAIZEN_CONFIG_DIR', Path.home() / '.config/kaizen')) / name / 'control-host.json'
    if not local.exists():
        raise ValueError('no host config for environment ' + name + '; save the shared JSON as ' + str(local))
    return local


def environment_label(config, path):
    return config.get('name') or Path(path).parent.name


def remote_command(config, command, arguments):
    if ('state_db' in config) != ('target_config' in config):
        raise ValueError('set both state_db and target_config for an environment; never mix a test ledger with the default target')
    for key in ('state_db', 'target_config'):
        if key in config and (not isinstance(config[key], str) or not Path(config[key]).is_absolute()):
            raise ValueError(key + ' must be an absolute control-host path')
    database = config.get('state_db', '/srv/isucon/state/team.sqlite3')
    target_config = config.get('target_config', '/srv/isucon/state/target.json')
    if command == 'integrator':
        # status, pause, resume, result, abandon: short commands against the resident integrator's state.
        return shlex.join(['runuser', '-u', 'isucon', '--', 'python3', config['remote_plugin_root'] + '/scripts/team/integrator.py',
                           '--db', database, '--config', target_config, *arguments])
    if command == 'dashboard':
        return shlex.join(['runuser', '-u', 'isucon', '--', 'cat', str(Path(database).parent / 'integrator/dashboard/summary.json')])
    script = 'target.py' if command == 'target' else 'team.py'
    forwarded = list(arguments) if command == 'target' else [command, *arguments]
    options = ['--db', database]
    if 'environment' in config:
        options += ['--environment', environment_name(config['environment'])]
    if command == 'target':
        options += ['--config', target_config]
    return shlex.join(['runuser', '-u', 'isucon', '--', 'python3',
                      config['remote_plugin_root'] + '/scripts/team/' + script, *options, *forwarded])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    where = p.add_mutually_exclusive_group()
    where.add_argument('--host-config', help='explicit host config path')
    where.add_argument('--env', help='environment name: team/environments/NAME or ~/.config/kaizen/NAME/control-host.json')
    p.add_argument('command', help='team.py command, target TARGET_ARGUMENTS, integrator ARGUMENTS, dashboard [--open], shell, or result COMMAND_ID')
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    args = p.parse_args()
    try:
        args.host_config = host_config_path(args.env, args.host_config)
        config = json.loads(args.host_config.read_text())
        print('environment: ' + environment_label(config, args.host_config), file=sys.stderr, flush=True)
        base = ['aws', '--region', config['region'], '--no-cli-pager']

        def aws(*arguments):
            return json.loads(subprocess.check_output([*base, *arguments, '--output', 'json'], text=True))

        identity = aws('sts', 'get-caller-identity')
        if identity['Account'] != config['account_id']:
            raise ValueError('AWS account mismatch; refusing to dispatch commands')
        if args.command == 'shell':
            return subprocess.run([*base, 'ssm', 'start-session', '--target', config['instance_id']]).returncode
        if args.command == 'dashboard' and args.arguments == ['--open']:
            # The control host has no inbound port: forward 127.0.0.1:8080 of the host to this PC through SSM.
            print('dashboard: http://localhost:18080/ while this session runs (Ctrl-C ends it)', file=sys.stderr, flush=True)
            return subprocess.run([*base, 'ssm', 'start-session', '--target', config['instance_id'],
                                   '--document-name', 'AWS-StartPortForwardingSession',
                                   '--parameters', json.dumps({'portNumber': ['8080'], 'localPortNumber': ['18080']})]).returncode
        if args.command == 'result':
            if len(args.arguments) != 1:
                raise ValueError('result requires the previous SSM Command ID')
            command_id = args.arguments[0]
        else:
            command = remote_command(config, args.command, args.arguments)
            response = aws('ssm', 'send-command', '--document-name', 'AWS-RunShellScript',
                           '--instance-ids', config['instance_id'], '--timeout-seconds', '60',
                           '--parameters', json.dumps({'commands': [command], 'executionTimeout':
                                                        ['1800' if args.command == 'target' else '60']}))
            command_id = response['Command']['CommandId']
            print('SSM Command ID: ' + command_id, file=sys.stderr, flush=True)
        for _ in range(60):
            response = subprocess.run([*base, 'ssm', 'get-command-invocation', '--command-id', command_id,
                                       '--instance-id', config['instance_id'], '--output', 'json'],
                                      capture_output=True, text=True)
            if response.returncode:
                if 'InvocationDoesNotExist' not in response.stderr:
                    raise ValueError(response.stderr.strip())
            else:
                result = json.loads(response.stdout)
                if result['Status'] in ('Success', 'Failed', 'Cancelled', 'TimedOut', 'Undeliverable', 'Terminated'):
                    sys.stdout.write(result.get('StandardOutputContent', ''))
                    sys.stderr.write(result.get('StandardErrorContent', ''))
                    return 0 if result['Status'] == 'Success' else 2
            time.sleep(1)
        raise ValueError('result is still pending; use result ' + command_id + '; do not blindly repeat a mutation')
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
