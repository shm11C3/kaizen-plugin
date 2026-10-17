#!/usr/bin/env python3
"""Build immutable Go tests and run them in the owned host's temporary directory."""
import argparse
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid


REMOTE_RUNNER = ('import json,os,sys; p=json.load(sys.stdin); '
                 'e=dict(os.environ); e.update(p["env"]); '
                 'os.execve("./kaizen-test",p["argv"],e)')


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def remote_path(value):
    if not re.fullmatch(r'/var/tmp/kaizen-check\.[A-Za-z0-9]{6,16}', value):
        raise ValueError('remote temporary directory is outside the permitted check namespace')
    return value


def relative_path(value):
    path = Path(value)
    if (not value or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', value)
            or path.is_absolute() or '..' in path.parts or str(path) != value):
        raise ValueError('artifact paths must be explicit normalized relative paths')
    return value


def exported(project, revision, module, includes, allowed_paths):
    if not re.fullmatch(r'[a-fA-F0-9]{40}', revision):
        raise ValueError('--ref must be a full immutable commit SHA')
    paths = [relative_path(module), *[relative_path(path) for path in includes]]
    if any(not any(path == allowed or path.startswith(allowed + '/') for allowed in allowed_paths) for path in paths):
        raise ValueError('test module/includes must be inside configured LOCAL_SYNC_PATHS')
    actual = subprocess.check_output(['git', '-C', str(project), 'rev-parse', '--verify', revision + '^{commit}'], stderr=subprocess.PIPE).decode().strip()
    if actual.lower() != revision.lower():
        raise ValueError('ref does not resolve to the requested commit')
    tree = subprocess.check_output(['git', '-C', str(project), 'rev-parse', revision + '^{tree}']).decode().strip()
    data = subprocess.check_output(['git', '-C', str(project), 'archive', '--format=tar', revision, *paths], stderr=subprocess.PIPE)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        names = {member.name.rstrip('/') for member in archive}
        if module + '/go.mod' not in names or not any(name.startswith(module + '/') and name.endswith('_test.go') for name in names):
            raise ValueError('immutable ref needs a Go module containing test source')
        if any(path not in names for path in includes):
            raise ValueError('an explicitly included artifact is missing from the ref')
    return actual, tree, data


def unpack(data, root):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Git export contains a link or unsafe archive member')
        archive.extractall(root, members=members)


def execute(project, revision, label, test_filter, host, ssh_config, environment,
            module='go', includes=(), allowed_paths=('go', 'sql'), runner=subprocess.run):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', label):
        raise ValueError('label must be a safe short identifier')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', host):
        raise ValueError('APP_HOST must be a configured SSH host alias')
    if not isinstance(environment, dict) or any(not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key)
            or not isinstance(value, str) or '\0' in value for key, value in environment.items()):
        raise ValueError('env-file must contain an environment-variable string map')
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start = time.monotonic()
    directory = project / '.kaizen/checks-remote'
    directory.mkdir(parents=True, exist_ok=True)
    stem = label + '-' + uuid.uuid4().hex
    log_path, record_path = directory / (stem + '.log'), directory / (stem + '.json')
    result = dict(label=label, sourceRevision=revision, sourceTree=None, binarySha256=None,
                  artifactSha256={}, goVersion=None, host=host, startedAt=started,
                  log=str(log_path), record=str(record_path), status='failed', passed=False, exitCode=2,
                  module=module, includes=list(includes), environmentKeys=sorted(environment),
                  environmentHash=checksum(json.dumps(environment, sort_keys=True).encode()),
                  testFilter=test_filter, testTimeoutSeconds=120)
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']
    if ssh_config:
        ssh += ['-F', ssh_config]
    ssh += [host]
    output = bytearray()
    test_output = b''
    temporary_remote = None
    secrets = [value for value in environment.values() if value]
    for value in environment.values():
        password = re.match(r'[^:]+:([^@]*)@', value)
        if password and password.group(1):
            secrets.append(password.group(1))

    def call(arguments, **kwargs):
        completed = runner(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        output.extend(completed.stdout or b'')
        return completed

    try:
        revision, tree, data = exported(project, revision, module, includes, allowed_paths)
        result.update(sourceRevision=revision, sourceTree=tree)
        with tempfile.TemporaryDirectory(prefix='kaizen-go-check-') as folder:
            root = Path(folder)
            unpack(data, root)
            for included in includes:
                path = root / included
                for file in ([path] if path.is_file() else sorted(path.rglob('*'))):
                    if file.is_file():
                        result['artifactSha256'][str(file.relative_to(root))] = checksum(file.read_bytes())
            version = call(['go', 'version'])
            result['goVersion'] = version.stdout.decode(errors='replace').strip()
            if version.returncode:
                result['exitCode'] = version.returncode
                return result
            cache = project / '.kaizen/remote-go-build-cache'
            cache.mkdir(parents=True, exist_ok=True)
            build_env = dict(os.environ, CGO_ENABLED='0', GOOS='linux', GOARCH='amd64', GOCACHE=str(cache))
            build = call(['go', 'test', '-c', '-o', str(root / module / 'kaizen-test'), '.'], cwd=root / module, env=build_env)
            result['exitCode'] = build.returncode
            if build.returncode:
                return result
            binary = root / module / 'kaizen-test'
            if not binary.is_file():
                raise ValueError('Go did not produce a test binary')
            result['binarySha256'] = checksum(binary.read_bytes())
            made = call([*ssh, 'mktemp -d /var/tmp/kaizen-check.XXXXXX'])
            if made.returncode:
                result['exitCode'] = made.returncode
                return result
            temporary_remote = remote_path(made.stdout.decode().strip())
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode='w') as archive:
                archive.add(binary, arcname=module + '/kaizen-test', recursive=False)
                for included in includes:
                    archive.add(root / included, arcname=included)
            copied = call([*ssh, 'tar -xf - -C ' + shlex.quote(temporary_remote)], input=payload.getvalue())
            if copied.returncode:
                result['exitCode'] = copied.returncode
                return result
            arguments = ['./kaizen-test', '-test.count=1', '-test.v', '-test.timeout=120s']
            if test_filter:
                arguments += ['-test.run', test_filter]
            command = ('cd ' + shlex.quote(temporary_remote + '/' + module)
                       + ' && sudo -n python3 -c ' + shlex.quote(REMOTE_RUNNER))
            checked = call([*ssh, command], input=json.dumps({'env': environment, 'argv': arguments}).encode())
            test_output = checked.stdout or b''
            result['exitCode'] = checked.returncode
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Do not format CalledProcessError or native argv: they may carry secrets.
        output.extend(('check setup failed: ' + type(error).__name__ + '\n').encode())
        result['setupError'] = str(error) if isinstance(error, ValueError) else type(error).__name__
        result['exitCode'] = 2
    finally:
        if temporary_remote is not None:
            try:
                cleanup = call([*ssh, 'rm -rf -- ' + shlex.quote(remote_path(temporary_remote))])
                result['cleanupPassed'] = cleanup.returncode == 0
            except (ValueError, OSError, subprocess.SubprocessError):
                result['cleanupPassed'] = False
            if not result.get('cleanupPassed'):
                result['exitCode'] = result['exitCode'] or 2
        result['durationSeconds'] = round(time.monotonic() - start, 6)
        text = test_output.decode(errors='replace')
        result['skippedTests'] = re.findall(r'--- SKIP: ([^\s]+)', text)
        result['passedTests'] = re.findall(r'--- PASS: ([^\s]+)', text)
        result['failedTests'] = re.findall(r'--- FAIL: ([^\s]+)', text)
        result['processPassed'] = result['exitCode'] == 0
        result['passed'] = result['processPassed'] and bool(result['passedTests']) and not result['skippedTests']
        result['status'] = ('passed' if result['passed'] else 'failed' if not result['processPassed']
                            else 'skipped' if result['skippedTests'] else 'no_tests')
        text = output.decode(errors='replace')
        for secret in sorted(secrets, key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        log_path.write_text(text)
        os.chmod(log_path, 0o600)
        record_path.write_text(json.dumps(result, indent=2) + '\n')
        os.chmod(record_path, 0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--test')
    parser.add_argument('--module', default='go')
    parser.add_argument('--include', action='append', default=[])
    parser.add_argument('--env-file', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('KAIZEN_TEAM_MODE') != '1':
        parser.error('use the owned target.py check-remote action')
    try:
        result = execute(Path(os.environ['KAIZEN_PROJECT']).resolve(), args.ref, args.label, args.test,
                         os.environ['APP_HOST'], os.environ.get('SSH_CONFIG', ''),
                         json.loads(args.env_file.read_text()), args.module, args.include,
                         tuple(os.environ['LOCAL_SYNC_PATHS'].split()))
        print(json.dumps(result, indent=2))
        return 0 if result['passed'] else 3 if result['processPassed'] else 2
    except (ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
