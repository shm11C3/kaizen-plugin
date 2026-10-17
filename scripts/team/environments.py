"""Environment inventory and lock names for one shared team ledger."""
import hashlib
import json
from pathlib import Path
import re

OFFICIAL = 'competition'


def environment_name(value):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', value):
        raise ValueError('environment must be a lowercase name, at most 40 characters')
    return value


def state_path(db_path, environment, suffix):
    environment_name(environment)
    namespace = '' if environment == OFFICIAL else '.env.' + environment
    return Path(str(db_path) + namespace + suffix)


def schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS environments (
            name TEXT PRIMARY KEY, config_path TEXT NOT NULL,
            fingerprint TEXT NOT NULL, project TEXT NOT NULL,
            evidence TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS environment_resources (
            resource TEXT PRIMARY KEY, environment TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sandbox_reservations (
            environment TEXT PRIMARY KEY, owner TEXT NOT NULL, token TEXT NOT NULL,
            purpose TEXT NOT NULL, acquired_at TEXT NOT NULL
        );
    ''')


def target_identity(path, environment):
    path = Path(path).resolve()
    data = path.read_bytes()
    config = json.loads(data)
    if config.get('environment') != environment:
        raise ValueError('target config environment does not match the selected environment')
    project = Path(config['project']).resolve()
    preset = project / '.kaizen/config.sh'
    if not preset.is_file() or not config.get('knowledge_dir'):
        raise ValueError('registered environments need a project preset and separate knowledge_dir')
    resources = config.get('resources')
    if not isinstance(resources, list) or not resources or any(
            not isinstance(r, str) or not r.strip() for r in resources):
        raise ValueError('resources must list canonical host, DB, mock and benchmark resource IDs')
    resources = set(resources) | {'project:' + str(project),
                                  'knowledge:' + str(Path(config['knowledge_dir']).resolve())}
    fingerprint = hashlib.sha256(data + b'\0' + preset.read_bytes()).hexdigest()
    return str(path), fingerprint, str(project), resources


def register(db, db_path, environment, config_path, evidence):
    environment_name(environment)
    if not evidence.strip():
        raise ValueError('registration needs isolation/rules evidence')
    if db.execute('SELECT 1 FROM reservation').fetchone() or db.execute(
            'SELECT 1 FROM sandbox_reservations').fetchone():
        raise ValueError('register or change inventory only when every environment is released')
    names = {OFFICIAL, environment} | {r['name'] for r in db.execute('SELECT name FROM environments')}
    if any(state_path(db_path, name, '.manual-bench').exists() for name in names):
        raise ValueError('a portal benchmark is pending; inventory cannot change')
    if environment != OFFICIAL and not db.execute(
            'SELECT 1 FROM environments WHERE name=?', (OFFICIAL,)).fetchone():
        raise ValueError('register the official competition environment first')
    path, fingerprint, project, resources = target_identity(config_path, environment)
    for resource in resources:
        row = db.execute('SELECT environment FROM environment_resources WHERE resource=?', (resource,)).fetchone()
        if row and row['environment'] != environment:
            raise ValueError('resource overlaps environment ' + row['environment'] + ': ' + resource)
    db.execute('INSERT OR REPLACE INTO environments VALUES (?,?,?,?,?)',
               (environment, path, fingerprint, project, evidence))
    db.execute('DELETE FROM environment_resources WHERE environment=?', (environment,))
    db.executemany('INSERT INTO environment_resources VALUES (?,?)',
                   [(r, environment) for r in sorted(resources)])
    return {'environment': environment, 'resources': sorted(resources), 'fingerprint': fingerprint,
            'evidence': evidence}


def validate_target(db, environment, path):
    row = db.execute('SELECT * FROM environments WHERE name=?', (environment,)).fetchone()
    if row is None:
        if environment != OFFICIAL:
            raise ValueError('register this sandbox before operating it')
        # Preserve the existing single-environment workflow.
        return
    config_path, fingerprint, project, _ = target_identity(path, environment)
    if (row['config_path'], row['fingerprint'], row['project']) != (config_path, fingerprint, project):
        raise ValueError('registered target changed; inspect and re-register at an idle boundary')
