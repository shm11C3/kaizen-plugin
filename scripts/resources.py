#!/usr/bin/env python3
"""Stable bundle metadata. Remote restore/probe commands are owned by lib.sh."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(text):
    return dict(line.split('\t', 1) for line in text.splitlines() if line)


def main():
    action, *args = sys.argv[1:]
    if action == 'config':
        h = hashlib.sha256(sys.stdin.buffer.read())
        for name in args:
            p = Path(name)
            if p.is_file():
                h.update(p.name.encode() + b'\0' + p.read_bytes() + b'\0')
        print(h.hexdigest())
        return
    path, revision, config_hash, fingerprints, *paths = args
    p = Path(path)
    actual = snapshot(fingerprints)
    if action in ('verify', 'verify-config'):
        if not p.is_file():
            raise ValueError('stable bundle missing; deploy stable, then stable.sh capture')
        expected = json.loads(p.read_text())
        assert expected['revision'] == revision, 'stable bundle revision differs; stable.sh capture/repin'
        assert expected['configHash'] == config_hash, 'target config changed; recapture stable and take fresh baseline'
        if action == 'verify':
            assert expected['resourceFingerprints'] == actual, 'resources differ from stable bundle; recover before measuring stable'
    elif action == 'capture':
        project = p.parent.parent
        trees = {}
        for entry in paths:
            r = subprocess.run(['git', '-C', str(project), 'rev-parse', '--verify', revision + ':' + entry],
                               capture_output=True, text=True)
            trees[entry] = r.stdout.strip() if not r.returncode else None
        identity = {'configHash': config_hash, 'resourceFingerprints': actual, 'trees': trees}
        identity['id'] = digest(json.dumps(identity, sort_keys=True).encode())
        identity['revision'] = revision
        # Provenance, not identity: the plugin may change mid-contest without retiring the bundle.
        identity['pluginRevision'] = os.environ.get('KAIZEN_PLUGIN_REVISION') or None
        identity['capturedAt'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        history = p.parent / 'bundles'
        history.mkdir(exist_ok=True)
        archived = history / (identity['id'] + '.json')
        if not archived.exists():
            archived.write_text(json.dumps(identity, indent=2) + '\n')
        p.write_text(json.dumps(identity, indent=2) + '\n')
        print(identity['id'])
    elif action == 'repin':
        expected = json.loads(p.read_text())
        assert expected['configHash'] == config_hash and expected['resourceFingerprints'] == actual, 'resource/config drift; cannot repin'
        expected['revision'] = revision
        p.write_text(json.dumps(expected, indent=2) + '\n')
    else:
        raise ValueError('unknown stable bundle operation')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, AssertionError) as error:
        sys.exit(str(error))
