#!/usr/bin/env python3
"""Call the central ledger through AWS SSM without inbound SSH or shared keys."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time


def remote_command(config, command, arguments):
    if ('state_db' in config) != ('target_config' in config):
        raise ValueError('set both state_db and target_config for an environment; never mix a test ledger with the default target')
    for key in ('state_db', 'target_config'):
        if key in config and (not isinstance(config[key], str) or not Path(config[key]).is_absolute()):
            raise ValueError(key + ' must be an absolute control-host path')
    script = 'target.py' if command == 'target' else 'team.py'
    forwarded = list(arguments) if command == 'target' else [command, *arguments]
    options = ['--db', config.get('state_db', '/srv/isucon/state/team.sqlite3')]
    if command == 'target':
        options += ['--config', config.get('target_config', '/srv/isucon/state/target.json')]
    return shlex.join(['runuser', '-u', 'isucon', '--', 'python3',
                      config['remote_plugin_root'] + '/scripts/team/' + script, *options, *forwarded])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host-config', default=str(Path(__file__).resolve().parents[2] / 'team/environments/competition/control-host.json'))
    p.add_argument('command', help='team.py command, target TARGET_ARGUMENTS, shell, or result COMMAND_ID')
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    args = p.parse_args()
    try:
        config = json.loads(Path(args.host_config).read_text())
        base = ['aws', '--region', config['region'], '--no-cli-pager']

        def aws(*arguments):
            return json.loads(subprocess.check_output([*base, *arguments, '--output', 'json'], text=True))

        identity = aws('sts', 'get-caller-identity')
        if identity['Account'] != config['account_id']:
            raise ValueError('AWS account mismatch; refusing to dispatch commands')
        if args.command == 'shell':
            return subprocess.run([*base, 'ssm', 'start-session', '--target', config['instance_id']]).returncode
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
