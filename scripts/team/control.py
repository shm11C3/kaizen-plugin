#!/usr/bin/env python3
"""Call the central ledger through AWS SSM without inbound SSH or shared keys."""
import argparse
import base64
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


def source_push_command(config, arguments):
    """Ship local branches to the control project as a small git bundle: the host often cannot fetch a private fork."""
    q = argparse.ArgumentParser(prog='control.py source-push')
    q.add_argument('--since', default='origin/main', help='commit the control project already has (default: origin/main)')
    q.add_argument('branches', nargs='+', help='local branch names; each lands at refs/remotes/origin/BRANCH on the host')
    a = q.parse_args(arguments)
    refs = []
    for branch in a.branches:
        full = subprocess.check_output(['git', 'rev-parse', '--symbolic-full-name', branch], text=True).strip()
        if not full.startswith('refs/heads/'):
            raise ValueError(branch + ' is not a local branch; create one with git branch NAME SHA')
        refs.append(full)
    data = subprocess.check_output(['git', 'bundle', 'create', '-', *refs, '--not', a.since], stderr=subprocess.DEVNULL)
    encoded = base64.b64encode(data).decode()
    if len(encoded) > 48000:
        raise ValueError('bundle is %d bytes; pass a newer --since the host already has' % len(data))
    target_config = config.get('target_config', '/srv/isucon/state/target.json')
    script = 'set -eu\n' \
        'P=$(python3 -c \'import json,sys; print(json.load(open(sys.argv[1]))["project"])\' %s)\n' \
        'F=$(mktemp /tmp/kaizen-source-XXXXXX.bundle); trap \'rm -f "$F"\' EXIT\n' \
        'echo %s | base64 -d > "$F"; chmod 644 "$F"\n' \
        'runuser -u isucon -- git -C "$P" fetch -q "$F" %s\n' \
        'for r in %s; do echo "$r $(runuser -u isucon -- git -C "$P" rev-parse "$r")"; done\n' % (
            shlex.quote(target_config), encoded,
            ' '.join(shlex.quote('+%s:refs/remotes/origin/%s' % (r, r[len('refs/heads/'):])) for r in refs),
            ' '.join(shlex.quote('refs/remotes/origin/' + r[len('refs/heads/'):]) for r in refs))
    return script


def plugin_push_command(config, arguments):
    """Practice R3: a measurement fix had no way onto the host the integrator runs from.
    Fast-forward the host plugin checkout to this clone's HEAD while the integrator is idle."""
    q = argparse.ArgumentParser(prog='control.py plugin-push')
    q.add_argument('--since', required=True, help='commit the host plugin is at now (control.py shows it on a mismatch)')
    a = q.parse_args(arguments)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.run(['git', 'merge-base', '--is-ancestor', a.since, head], capture_output=True).returncode:
        raise ValueError('HEAD does not descend from --since ' + a.since[:7])
    data = subprocess.check_output(['git', 'bundle', 'create', '-', 'HEAD', '--not', a.since], stderr=subprocess.DEVNULL)
    encoded = base64.b64encode(data).decode()
    if len(encoded) > 48000:
        raise ValueError('bundle is %d bytes; push fewer commits at a time' % len(data))
    root = config['remote_plugin_root']
    state = str(Path(config.get('target_config', '/srv/isucon/state/target.json')).parent / 'integrator' / 'status.json')
    script = 'set -eu\n' \
        'P=%s; G="git -c safe.directory=$P -C $P"\n' \
        'cur=$(runuser -u isucon -- $G rev-parse HEAD)\n' \
        'case "$cur" in %s*) ;; *) echo "host plugin is at $cur, not %s" >&2; exit 3;; esac\n' \
        '[ -z "$(runuser -u isucon -- $G status --short)" ] || { echo "host plugin has local changes" >&2; exit 3; }\n' \
        'if [ -f %s ] && grep -q \'"state": "working"\' %s; then echo "integrator is working; retry when idle" >&2; exit 3; fi\n' \
        'F=$(mktemp /tmp/kaizen-plugin-XXXXXX.bundle); trap \'rm -f "$F"\' EXIT\n' \
        'echo %s | base64 -d > "$F"; chmod 644 "$F"\n' \
        'runuser -u isucon -- $G fetch -q "$F" HEAD\n' \
        'runuser -u isucon -- $G checkout -q --detach %s\n' \
        'echo "host plugin $(runuser -u isucon -- $G log --oneline -1)"\n' % (
            shlex.quote(root), a.since, a.since[:7], shlex.quote(state), shlex.quote(state), encoded, head)
    return script


def check_ready_shas(arguments):
    """Practice R3: a mistyped --base (one digit off) was accepted and recorded; check both SHAs in the local clone."""
    q = argparse.ArgumentParser(add_help=False)
    q.add_argument('--base')
    q.add_argument('--sha')
    a, _ = q.parse_known_args(arguments)
    if not a.base or not a.sha or subprocess.run(['git', 'rev-parse', '--git-dir'], capture_output=True).returncode:
        return
    for name, sha in (('--base', a.base), ('--sha', a.sha)):
        if subprocess.run(['git', 'cat-file', '-e', sha + '^{commit}'], capture_output=True).returncode:
            raise ValueError(name + ' ' + sha + ' is not a commit in this clone; copy it from git rev-parse')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', a.base, a.sha], capture_output=True).returncode:
        raise ValueError('--base ' + a.base[:7] + ' is not an ancestor of --sha ' + a.sha[:7])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    where = p.add_mutually_exclusive_group()
    where.add_argument('--host-config', help='explicit host config path')
    where.add_argument('--env', help='environment name: team/environments/NAME or ~/.config/kaizen/NAME/control-host.json')
    p.add_argument('command', help='team.py command, target TARGET_ARGUMENTS, integrator ARGUMENTS, dashboard [--open], shell, source-push [--since BASE] BRANCH..., plugin-push --since HOST_REV, or result COMMAND_ID')
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
            if args.command == 'task-ready':
                check_ready_shas(args.arguments)
            command = (source_push_command(config, args.arguments) if args.command == 'source-push'
                       else plugin_push_command(config, args.arguments) if args.command == 'plugin-push'
                       else remote_command(config, args.command, args.arguments))
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
                    stdout = result.get('StandardOutputContent', '')
                    sys.stdout.write(stdout)
                    sys.stderr.write(result.get('StandardErrorContent', ''))
                    truncated = output_truncated(stdout, result.get('StandardOutputUrl', ''))
                    if truncated:
                        print(truncated, file=sys.stderr)
                        return 3
                    return 0 if result['Status'] == 'Success' else 2
            time.sleep(1)
        raise ValueError('result is still pending; use result ' + command_id + '; do not blindly repeat a mutation')
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 2


# get-command-invocation returns at most 24,000 characters of standard output
# and drops the rest without an error, so a large ledger answer arrives as cut
# JSON (R3: status and the full task-list broke this way).
SSM_OUTPUT_LIMIT = 24000


def output_truncated(stdout, output_url=''):
    if len(stdout) >= SSM_OUTPUT_LIMIT or output_url:
        return ('output was cut at the SSM limit of %d characters; read less at once: '
                'task-list --summary --limit N --after-id T-XXXX, or task-get --id T-XXXX'
                % SSM_OUTPUT_LIMIT)
    return ''


if __name__ == '__main__':
    sys.exit(main())
