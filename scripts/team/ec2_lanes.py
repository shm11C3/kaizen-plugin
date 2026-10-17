#!/usr/bin/env python3
"""Prepare isolated EC2 lanes; deployments and benchmarks still use target.py."""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from team import connect, operation_lock
from environments import OFFICIAL, environment_name, state_path


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as handle:
        os.chmod(temporary, 0o600)
        json.dump(data, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def validate(config):
    if not re.fullmatch(r'\d{12}', config.get('account', '')):
        raise ValueError('account must be the expected 12-digit AWS account')
    if not config.get('region') or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]{0,59}', config.get('study', '')):
        raise ValueError('region and a short study ID are required')
    excluded = config.get('excluded_instance_ids')
    if not isinstance(excluded, list) or not excluded:
        raise ValueError('explicitly list official/control instance IDs to exclude')
    if not isinstance(config.get('lanes'), dict) or not config['lanes']:
        raise ValueError('at least one lane is required')
    seen = set()
    for lane, roles in config['lanes'].items():
        environment_name(lane)
        if lane == OFFICIAL or set(roles) != {'app', 'bench'}:
            raise ValueError('sandbox lanes need exactly app and bench; competition is excluded')
        for role, spec in roles.items():
            if set(spec) not in ({'instance_id'}, {'launch'}):
                raise ValueError('each role needs either instance_id or launch')
            if 'instance_id' in spec:
                instance = spec['instance_id']
                if not re.fullmatch(r'i-[a-f0-9]{8,17}', instance):
                    raise ValueError('invalid EC2 instance ID')
                if instance in excluded or instance in seen:
                    raise ValueError('official/control or duplicate EC2 resource: ' + instance)
                seen.add(instance)
            else:
                launch_request(config, lane, role, spec['launch'])
    return config


def launch_request(config, lane, role, launch):
    request = json.loads(json.dumps(launch))
    for required in ('ImageId', 'InstanceType', 'SubnetId', 'SecurityGroupIds', 'BlockDeviceMappings'):
        if not request.get(required):
            raise ValueError('launch requires ' + required)
    if request.get('UserData') or request.get('LaunchTemplate'):
        raise ValueError('use explicit launch fields without user data or inherited launch templates')
    disks = [item['Ebs'] for item in request['BlockDeviceMappings'] if 'Ebs' in item]
    if not disks or any(disk.get('Encrypted') is not True for disk in disks):
        raise ValueError('every supplied EBS mapping must explicitly enable encryption')
    request.update(MinCount=1, MaxCount=1)
    request['ClientToken'] = 'kaizen-' + digest([config['account'], config['region'], config['study'], lane, role])[:48]
    request['MetadataOptions'] = dict(request.get('MetadataOptions', {}), HttpTokens='required', HttpEndpoint='enabled')
    tags = {'Study': config['study'], 'Project': config['study'], 'Lane': lane,
            'Role': role, 'Name': config['study'] + '-' + lane + '-' + role}
    specs = {item['ResourceType']: item for item in request.get('TagSpecifications', [])}
    for resource in ('instance', 'volume'):
        merged = {item['Key']: item['Value'] for item in specs.get(resource, {}).get('Tags', [])}
        merged.update(tags)
        specs[resource] = {'ResourceType': resource, 'Tags': [{'Key': k, 'Value': v} for k, v in merged.items()]}
    request['TagSpecifications'] = list(specs.values())
    return request


class AWS:
    def __init__(self, region):
        self.region = region

    def __call__(self, service, operation, *arguments):
        result = subprocess.run(['aws', '--region', self.region, '--no-cli-pager', service,
                                 operation, *arguments, '--output', 'json'],
                                capture_output=True, text=True)
        if result.returncode:
            raise ValueError(result.stderr.strip())
        return json.loads(result.stdout or '{}')


def describe(aws, instance_id):
    data = aws('ec2', 'describe-instances', '--instance-ids', instance_id)
    instances = [i for reservation in data['Reservations'] for i in reservation['Instances']]
    if len(instances) != 1 or instances[0]['InstanceId'] != instance_id:
        raise ValueError('unexpected instance identity')
    return instances[0]


def validate_image_disks(aws, request):
    images = aws('ec2', 'describe-images', '--image-ids', request['ImageId'])['Images']
    if len(images) != 1:
        raise ValueError('expected exactly one launch AMI')
    mappings = {item.get('DeviceName'): item.get('Ebs', {}) for item in request['BlockDeviceMappings']}
    inherited = {item['DeviceName'] for item in images[0].get('BlockDeviceMappings', []) if 'Ebs' in item}
    inherited.add(images[0]['RootDeviceName'])
    if any(mappings.get(device, {}).get('Encrypted') is not True for device in inherited):
        raise ValueError('explicit encrypted mappings are required for the AMI root and every inherited EBS disk')


def run(config, state, path, action, aws, imported=None):
    validate(config)
    if aws('sts', 'get-caller-identity')['Account'] != config['account']:
        raise ValueError('AWS account differs from expected account; no EC2 mutation performed')
    fingerprint = digest(config)
    if state and (state.get('config_digest') != fingerprint or state.get('study') != config['study']):
        raise ValueError('state belongs to another configuration; preserve it and inspect')
    if action == 'plan':
        return {'plan': config, 'config_digest': fingerprint, 'mutation': False}
    state.setdefault('study', config['study'])
    state.setdefault('config_digest', fingerprint)
    state.setdefault('hosts', {})
    known = {spec['instance_id'] for roles in config['lanes'].values() for spec in roles.values() if 'instance_id' in spec}
    if imported:
        if action != 'ensure' or imported.get('study') != config['study'] or imported.get('account') != config['account']:
            raise ValueError('startup import must identify this study/account and is only accepted by ensure')
        for instance, item in imported.get('instances', {}).items():
            if instance not in known or item.get('original_state') not in ('stopped', 'absent') or not item.get('evidence'):
                raise ValueError('startup import needs known instance, original stopped/absent state and evidence')
    results = {}
    for lane, roles in config['lanes'].items():
        for role, spec in roles.items():
            key = lane + '/' + role
            entry = state['hosts'].get(key)
            if entry and entry.get('instance_id') in config['excluded_instance_ids']:
                raise ValueError('state contains an excluded instance')
            if entry and 'instance_id' in spec and entry.get('instance_id') != spec['instance_id']:
                raise ValueError('state instance differs from configuration')
            if not entry and action == 'ensure':
                if 'instance_id' in spec:
                    live = describe(aws, spec['instance_id'])
                    original = live['State']['Name']
                    imported_item = (imported or {}).get('instances', {}).get(spec['instance_id'])
                    entry = {'instance_id': spec['instance_id'], 'original_state': original,
                             'managed': original == 'stopped', 'created': False, 'recorded_at': now()}
                    if imported_item:
                        entry.update(original_state=imported_item['original_state'], managed=True,
                                     created=imported_item['original_state'] == 'absent', startup_import=imported_item)
                else:
                    request = launch_request(config, lane, role, spec['launch'])
                    validate_image_disks(aws, request)
                    entry = {'original_state': 'absent', 'managed': True, 'created': True,
                             'launch_request': request, 'recorded_at': now()}
                state['hosts'][key] = entry
                save(path, state)  # Persist intent before any start/create API.
            instance_id = entry.get('instance_id') if entry else spec.get('instance_id')
            if action == 'ensure' and not instance_id:
                data = aws('ec2', 'run-instances', '--cli-input-json', json.dumps(entry['launch_request']))
                instance_id = data['Instances'][0]['InstanceId']
                entry['instance_id'] = instance_id
                save(path, state)  # Retrying an interrupted response uses the same client token.
            if not instance_id:
                if action == 'stop' and entry:
                    raise ValueError('unresolved launch intent; run ensure before stopping')
                results[key] = {'state': 'not-created'}
                continue
            if instance_id in config['excluded_instance_ids']:
                raise ValueError('refusing excluded instance')
            live = describe(aws, instance_id)
            current = live['State']['Name']
            if action == 'ensure':
                if current == 'stopped':
                    if not entry['managed']:
                        raise ValueError('previously running/unmanaged instance is now stopped; inspect before restart')
                    entry['start_requested_at'] = now()
                    save(path, state)
                    aws('ec2', 'start-instances', '--instance-ids', instance_id)
                    live = describe(aws, instance_id)
                elif current not in ('pending', 'running'):
                    raise ValueError('cannot ensure instance in state ' + current)
            elif action == 'stop' and entry and entry['managed'] and current in ('running', 'pending'):
                entry['stop_requested_at'] = now()
                save(path, state)
                aws('ec2', 'stop-instances', '--instance-ids', instance_id)
                live = describe(aws, instance_id)
            result = {'instance_id': instance_id, 'state': live['State']['Name'],
                      'public_ip': live.get('PublicIpAddress'), 'private_ip': live.get('PrivateIpAddress'),
                      'resource': 'aws:' + config['account'] + ':' + config['region'] + ':' + instance_id,
                      'managed': bool(entry and entry['managed']), 'created': bool(entry and entry['created'])}
            results[key] = result
            if action in ('ensure', 'stop') and entry:
                entry['last_seen'] = result
                save(path, state)
    return {'study': config['study'], 'action': action, 'hosts': results}


@contextlib.contextmanager
def idle(db_path, config):
    """Hold normal operation locks and the ledger write transaction while mutating EC2."""
    with contextlib.ExitStack() as stack:
        for name in sorted({OFFICIAL, *config['lanes']}):
            stack.enter_context(operation_lock(db_path, name))
        db = stack.enter_context(contextlib.closing(connect(db_path)))
        db.execute('BEGIN IMMEDIATE')
        names = {OFFICIAL, *config['lanes']} | {row['name'] for row in db.execute('SELECT name FROM environments')}
        if db.execute('SELECT 1 FROM reservation').fetchone() or db.execute('SELECT 1 FROM sandbox_reservations').fetchone():
            raise ValueError('release all environment reservations before infrastructure changes')
        if any(state_path(db_path, name, '.manual-bench').exists() for name in names):
            raise ValueError('portal benchmark is pending')
        for row in db.execute('SELECT project FROM environments'):
            project = Path(row['project']) / '.kaizen'
            state = project / 'state.env'
            if (project / 'manual-bench.json').exists() or (project / 'bench.lock').exists() or (state.exists() and any(
                    line.startswith(('CURRENT_EXPERIMENT=', 'REVERT_PENDING='))
                    and line.split('=', 1)[1].strip().strip("'\"") not in ('', '0', 'false')
                    for line in state.read_text().splitlines())):
                raise ValueError('close experiments and pending benchmark/recovery work before infrastructure changes')
        yield
        db.rollback()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--db', help='the shared team ledger; required for ensure/stop')
    parser.add_argument('--import-startup', help='explicit evidence of resources already started/created for this study')
    parser.add_argument('--output', help='write status/inventory JSON here')
    parser.add_argument('action', choices=('plan', 'ensure', 'status', 'stop'))
    args = parser.parse_args()
    try:
        config = validate(json.loads(Path(args.config).read_text()))
        path = Path(args.state)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_name(path.name + '.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = json.loads(path.read_text()) if path.exists() else {}
            imported = json.loads(Path(args.import_startup).read_text()) if args.import_startup else None
            if args.action in ('ensure', 'stop') and not args.db:
                raise ValueError('--db is required to verify idle team operations')
            scope = idle(args.db, config) if args.action in ('ensure', 'stop') else contextlib.nullcontext()
            with scope:
                result = run(config, state, path, args.action, AWS(config['region']), imported)
            if args.output:
                save(args.output, result)
            print(json.dumps(result, indent=2))
        return 0
    except (ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
