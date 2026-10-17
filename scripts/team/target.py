#!/usr/bin/env python3
"""Run a pinned kaizen operation under the control-host reservation."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile

from team import connect, operation_lock, reservation
from environments import OFFICIAL, environment_name, state_path, validate_target
from record_proof import sync_proof


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--agent', required=True)
    p.add_argument('--token', required=True)
    p.add_argument('--db', default='/srv/isucon/state/team.sqlite3')
    p.add_argument('--config', default='/srv/isucon/state/target.json')
    p.add_argument('--environment', default=OFFICIAL, type=environment_name)
    p.add_argument('action', choices=('deploy', 'bench', 'observe', 'verify', 'evaluate', 'experiment', 'recover', 'stable', 'status', 'strategy', 'check-remote', 'stable-sync'))
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    args = p.parse_args()
    try:
        config_path = Path(args.config)
        if not config_path.is_file():
            raise ValueError('target is unconfigured; follow the plugin team/docs/RUNBOOK.md before enabling operations')
        config = json.loads(config_path.read_text())
        if not all(config.get(key) is True for key in ('enabled', 'confirmed_rules', 'confirmed_recovery_drill')):
            raise ValueError('target rules and recovery drill must be confirmed before enabling operations')
        script = Path(config['plugin_root']) / 'scripts' / (args.action + '.sh')
        project = Path(config['project']).resolve()
        if not script.is_file() or not (project / '.kaizen/config.sh').is_file():
            raise ValueError('plugin or target preset is missing')
        with operation_lock(args.db, args.environment) as lock_handle:
            with contextlib.closing(connect(args.db)) as db:
                reservation(db, args.agent, args.token, args.environment)
                validate_target(db, args.environment, config_path)
            environment = dict(os.environ, KAIZEN_PROJECT=str(project),
                               KAIZEN_TEAM_MODE='1',
                               KAIZEN_PLUGIN_ROOT=str(Path(config['plugin_root']).resolve()))
            if args.action == 'stable-sync':
                if args.environment == OFFICIAL:
                    raise ValueError('stable-sync is restricted to a registered sandbox')
                sync = argparse.ArgumentParser(prog='target stable-sync')
                choice = sync.add_mutually_exclusive_group(required=True)
                choice.add_argument('--record')
                choice.add_argument('--rollback', action='store_true')
                selected = sync.parse_args(args.arguments)
                environment['KAIZEN_SANDBOX_SYNC'] = '1'
                if selected.record:
                    with operation_lock(args.db, OFFICIAL):
                        with contextlib.closing(connect(args.db)) as db:
                            official = db.execute('SELECT project FROM environments WHERE name=?', (OFFICIAL,)).fetchone()
                            if not official:
                                raise ValueError('register competition before syncing a sandbox')
                            proof = sync_proof(official['project'], selected.record, project)
                    environment['KAIZEN_SYNC_PROOF'] = json.dumps(proof)
            environment['KAIZEN_KNOWLEDGE_DIR'] = str(Path(config.get(
                'knowledge_dir', str(Path(config['plugin_root']) / 'knowledge'))).resolve())
            if config.get('knowledge_dir'):
                knowledge = Path(environment['KAIZEN_KNOWLEDGE_DIR'])
                if not knowledge.exists():
                    knowledge.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(prefix='.kaizen-knowledge-', dir=str(knowledge.parent)) as temp:
                        staged = Path(temp) / 'corpus'
                        shutil.copytree(Path(config['plugin_root']) / 'knowledge', staged)
                        try:
                            staged.rename(knowledge)
                        except FileExistsError:
                            pass
                if not (knowledge / 'match.py').is_file() or not (knowledge / 'patterns').is_dir():
                    raise ValueError('knowledge_dir is not a complete corpus; preserve it and initialize a separate plugin knowledge copy')
            portal_marker = state_path(args.db, args.environment, '.manual-bench')
            if args.action == 'bench' and '--reserve' in args.arguments:
                portal_marker.touch()
            try:
                return subprocess.run(['bash', str(script), *args.arguments], cwd=str(project),
                                      env=environment, pass_fds=(lock_handle.fileno(),)).returncode
            finally:
                if (project / '.kaizen/manual-bench.json').exists():
                    portal_marker.touch()
                elif portal_marker.exists():
                    portal_marker.unlink()
    except (ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
