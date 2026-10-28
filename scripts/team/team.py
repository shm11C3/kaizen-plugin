#!/usr/bin/env python3
"""Small coordination ledger. Run all writers on the single control host."""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

from environments import OFFICIAL, environment_name, register, schema, state_path
from record_proof import promoted_record
from source_proof import SourceProof, fresh_retest_samples, guard_holds
from pipeline import read_status as pipeline_status


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            evidence TEXT NOT NULL, priority INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'TODO', owner TEXT,
            base_sha TEXT, source_sha TEXT, review TEXT, reason TEXT, human_decision TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reservation (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            owner TEXT NOT NULL, token TEXT NOT NULL,
            purpose TEXT NOT NULL, acquired_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
            actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS members (
            agent TEXT PRIMARY KEY, provider TEXT NOT NULL,
            plugin_version TEXT NOT NULL, joined_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quality_holds (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            base_sha TEXT NOT NULL, source_sha TEXT NOT NULL,
            environment TEXT NOT NULL, category TEXT NOT NULL,
            evidence TEXT NOT NULL, reason TEXT NOT NULL, opened_at TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'OPEN', repair_sha TEXT, repair_submitted_at TEXT,
            retest_record TEXT, retest_digest TEXT, tested_sha TEXT, closed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_ref TEXT NOT NULL, summary TEXT NOT NULL, owner TEXT NOT NULL,
            created_at TEXT NOT NULL, decision TEXT
                CHECK(decision IN ('adopt','existing','defer','reject')),
            reason TEXT, artifact TEXT, next_action TEXT, decided_at TEXT,
            UNIQUE(source_ref, summary)
        );
    """)
    schema(db)
    for column, definition in (('human_question', 'TEXT'), ('hypothesis_key', 'TEXT'),
                               ('work_kind', "TEXT NOT NULL DEFAULT 'implementation'"), ('related_task', 'TEXT')):
        if column not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
            try:
                db.execute(f'ALTER TABLE tasks ADD COLUMN {column} {definition}')
            except sqlite3.OperationalError:
                if column not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
                    raise
    return db


@contextlib.contextmanager
def operation_lock(path, environment=OFFICIAL):
    lock = state_path(path, environment, '.operation.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('a target operation is running; inspect it before release or handoff')
        yield handle


def reservation(db, agent=None, token=None, environment=OFFICIAL):
    environment_name(environment)
    row = db.execute('SELECT * FROM reservation').fetchone() if environment == OFFICIAL else db.execute(
        'SELECT * FROM sandbox_reservations WHERE environment=?', (environment,)).fetchone()
    if agent is not None and (row is None or row['owner'] != agent or row['token'] != token):
        raise ValueError('environment owner/token mismatch; do not reuse an old reservation')
    return dict(row) if row else None


def resolve_quality_holds(db, args, row):
    official = db.execute('SELECT project FROM environments WHERE name=?', (OFFICIAL,)).fetchone()
    if not official or not args.record or not args.tested_sha:
        raise ValueError('adoption needs a registered official environment, --record and --tested-sha')
    proof = SourceProof(official['project'])
    if not proof.contains(row['base_sha'], row['source_sha'], args.tested_sha):
        raise ValueError('tested source does not preserve submitted changed blobs; resubmit the actual integrated SHA')
    try:
        record = json.loads(Path(args.record).read_text())
    except (OSError, ValueError):
        record = {}
    rule = record.get('ruleDecision') or {}
    holds = guard_holds(db, proof, args.tested_sha,
                        stabilized=rule.get('decision') == 'promote' and bool(rule.get('stabilizationRequired')),
                        stable=record.get('stableBefore'))
    own = db.execute("SELECT * FROM quality_holds WHERE task_id=? AND state IN ('OPEN','RETEST_PENDING')",
                     (row['id'],)).fetchall()
    if any(h['state'] != 'RETEST_PENDING' or h['repair_sha'] != row['source_sha'] for h in own):
        raise ValueError('resume investigation and submit the repaired/retest candidate before adoption')
    pending = {h['id']: h for h in holds if h['state'] == 'RETEST_PENDING'}
    pending.update({h['id']: dict(h) for h in own})
    record_path = Path(args.record).resolve()
    root = Path(official['project']) / '.kaizen/experiments'
    if not record_path.is_relative_to(root.resolve()) or record_path.name != 'record.json':
        raise ValueError('retest record must come from the official project experiments')
    record_bytes = record_path.read_bytes()
    record = json.loads(record_bytes)
    rule = record.get('ruleDecision', {})
    promoted_record(record, args.tested_sha)
    try:
        closed = datetime.datetime.fromisoformat(record['closedAt'].replace('Z', '+00:00'))
        submitted = max((datetime.datetime.fromisoformat(h['repair_submitted_at']) for h in pending.values()),
                        default=datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
        # experiment.sh writes timestamps at second precision.
        fresh = closed.tzinfo is not None and closed >= submitted.replace(microsecond=0)
    except (KeyError, TypeError, ValueError):
        fresh = False
    if (record.get('finalDecision') != 'promote' or record.get('candidateRevision') != args.tested_sha
            or record.get('stableAfter') != args.tested_sha
            or record.get('manifest', {}).get('candidateRevision') != args.tested_sha or not fresh
            or not re.fullmatch(r'[a-fA-F0-9]{40}', args.tested_sha)
            or rule.get('quality', {}).get('status') != 'pass'
            or rule.get('qualityBlockPromotion') is not False):
        raise ValueError('retest must be a fresh promoted official record with passing quality and matching tested SHA')
    # Records can also contain fresh baseline and observed diagnostic samples.
    samples = [s for s in record.get('samples', [])
               if s.get('label', '').startswith('candidate') and not s.get('observed')]
    if not samples or any(s.get('pass') is not True or s.get('deployedRevision') != args.tested_sha for s in samples):
        raise ValueError('retest samples must pass on the tested integrated SHA')
    fresh_retest_samples(pending.values(), samples)
    affected_human = any(db.execute('SELECT review FROM tasks WHERE id=?', (h['task_id'],)).fetchone()['review'] == 'human'
                         for h in pending.values())
    if (affected_human or row['review'] == 'human' or row['status'] == 'NEEDS_HUMAN') and (not args.human_decision or record.get('manifest', {}).get('review') != 'human'
                                     or record.get('humanDecision') != args.human_decision):
        raise ValueError('human decision must match the official retest record')
    db.executemany("UPDATE quality_holds SET state='RESOLVED',retest_record=?,retest_digest=?,tested_sha=?,closed_at=? "
                   "WHERE id=? AND state='RETEST_PENDING'",
                   [(str(record_path), hashlib.sha256(record_bytes).hexdigest(), args.tested_sha, now(), hold_id)
                    for hold_id in pending])


def task(db, name):
    if not re.fullmatch(r'T-\d+', name):
        raise ValueError('task id must be T-0001 or equivalent')
    row = db.execute('SELECT * FROM tasks WHERE id=?', (int(name[2:]),)).fetchone()
    if row is None:
        raise ValueError('unknown task ' + name)
    return row


def public_task(row):
    result = dict(row)
    result['id'] = 'T-{:04d}'.format(row['id'])
    return result


def public_feedback(row):
    result = dict(row)
    result['id'] = 'F-{:04d}'.format(row['id'])
    return result


def feedback_attention(db):
    return {
        'feedback_pending': [public_feedback(r) for r in db.execute(
            'SELECT * FROM feedback WHERE decision IS NULL ORDER BY id')],
        'feedback_deferred': [public_feedback(r) for r in db.execute(
            "SELECT * FROM feedback WHERE decision='defer' ORDER BY id")],
    }


def required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must not be blank')
    return value.strip()


def event(db, args, result):
    db.execute('INSERT INTO events(at,actor,action,details) VALUES (?,?,?,?)',
               (now(), getattr(args, 'agent', 'observer'), args.command,
                json.dumps(result, ensure_ascii=False)))


def dispatch(db, args):
    command = args.command
    if command in ('join', 'queue'):
        if args.ready_limit < 1:
            raise ValueError('ready-limit must be positive')
        version = json.loads((Path(__file__).resolve().parents[2] / '.claude-plugin/plugin.json').read_text())['version']
        if command == 'join':
            if args.plugin_version != version:
                raise ValueError('plugin version differs from control host; align the release before joining')
            db.execute('INSERT OR REPLACE INTO members VALUES (?,?,?,?)',
                       (args.agent, args.provider, version, now()))
        counts = {r['status']: r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM tasks GROUP BY status')}
        env = reservation(db)
        backlog = counts.get('READY', 0) >= args.ready_limit
        work = db.execute(
            "SELECT * FROM tasks WHERE status='TODO' AND (?=0 OR work_kind!='implementation') ORDER BY priority DESC,id LIMIT 3",
            (int(backlog),)).fetchall()
        investigate = db.execute(
            "SELECT * FROM tasks WHERE status='NEEDS_MEASUREMENT' ORDER BY priority DESC,id").fetchall()
        result = {'plugin_version': version, 'counts': counts,
                  'selected_environment': args.environment,
                  'environment_owners': {r['name']: (
                      reservation(db, environment=r['name']) or {}).get('owner')
                      for r in db.execute('SELECT name FROM environments ORDER BY name')},
                  'ready_backlog': backlog,
                  'suggested_tasks': [public_task(r) for r in work],
                  'measurement_work': [public_task(r) for r in investigate],
                  'quality_holds': [dict(r) for r in db.execute(
                      "SELECT * FROM quality_holds WHERE state IN ('OPEN','RETEST_PENDING') ORDER BY id")],
                  'integration_owner': env['owner'] if env else None,
                  'advice': 'analyze submitted candidates or logs before more implementation' if counts.get('READY', 0) >= args.ready_limit else 'claim or discover the next useful task'}
        if command == 'join':
            result['member'] = {'agent': args.agent, 'provider': args.provider}
        result.update(feedback_attention(db))
        return result
    if command == 'status':
        return {'environment': reservation(db, environment=args.environment),
                'inventory': [dict(r) for r in db.execute('SELECT * FROM environments ORDER BY name')],
                'quality_holds': [dict(r) for r in db.execute('SELECT * FROM quality_holds ORDER BY id')],
                'tasks': [public_task(r) for r in db.execute('SELECT * FROM tasks ORDER BY priority DESC,id')],
                **feedback_attention(db)}
    if command == 'feedback-list':
        query = 'SELECT * FROM feedback' + (' WHERE decision IS NULL' if args.pending else '') + ' ORDER BY id'
        return [public_feedback(r) for r in db.execute(query)]
    if command == 'feedback-add':
        source = required_text(args.source_ref, 'source-ref')
        summary = required_text(args.summary, 'summary')
        owner = required_text(args.agent, 'agent')
        db.execute('INSERT OR IGNORE INTO feedback(source_ref,summary,owner,created_at) VALUES (?,?,?,?)',
                   (source, summary, owner, now()))
        return public_feedback(db.execute('SELECT * FROM feedback WHERE source_ref=? AND summary=?',
                                          (source, summary)).fetchone())
    if command == 'feedback-decide':
        if not re.fullmatch(r'F-\d+', args.id):
            raise ValueError('feedback id must be F-0001 or equivalent')
        row = db.execute('SELECT * FROM feedback WHERE id=?', (int(args.id[2:]),)).fetchone()
        if row is None:
            raise ValueError('unknown feedback ' + args.id)
        if row['owner'] != args.agent:
            raise ValueError('only the feedback owner may record its decision')
        reason = required_text(args.reason, 'reason')
        artifact = required_text(args.artifact, 'artifact')
        next_action = required_text(args.next_action, 'next-action') if args.decision == 'defer' else args.next_action
        db.execute('UPDATE feedback SET decision=?,reason=?,artifact=?,next_action=?,decided_at=? WHERE id=?',
                   (args.decision, reason, artifact, next_action, now(), row['id']))
        return public_feedback(db.execute('SELECT * FROM feedback WHERE id=?', (row['id'],)).fetchone())
    if command == 'task-list':
        return [public_task(r) for r in db.execute('SELECT * FROM tasks ORDER BY priority DESC,id')]
    if command == 'task-create':
        if args.related:
            task(db, args.related)
        if args.hypothesis:
            existing = db.execute(
                "SELECT * FROM tasks WHERE hypothesis_key=? AND status NOT IN ('ACCEPTED','REJECTED','DONE') LIMIT 1",
                (args.hypothesis,)).fetchone()
            if existing:
                raise ValueError('active hypothesis already exists: ' + public_task(existing)['id'] + '; coordinate or add evidence there')
        cur = db.execute('INSERT INTO tasks(title,evidence,priority,updated_at,hypothesis_key,work_kind,related_task) VALUES (?,?,?,?,?,?,?)',
                         (args.title, args.evidence, args.priority, now(), args.hypothesis, args.kind, args.related))
        created = public_task(db.execute('SELECT * FROM tasks WHERE id=?', (cur.lastrowid,)).fetchone())
        if args.related:
            # Hypothesis keys are free text, so two sessions can name one mechanism
            # differently (practice: T-0006 duplicated READY T-0001). Show the
            # active work around the same task so the creator can coordinate.
            near = db.execute("SELECT * FROM tasks WHERE id<>? AND status NOT IN ('ACCEPTED','REJECTED','DONE') "
                              "AND (id=? OR related_task=?) ORDER BY id",
                              (cur.lastrowid, task(db, args.related)['id'], args.related)).fetchall()
            if near:
                created['possibleDuplicates'] = [{k: public_task(r)[k] for k in ('id', 'title', 'status', 'owner', 'hypothesis_key')}
                                                 for r in near]
        return created
    if command == 'task-claim':
        if args.ready_limit < 1:
            raise ValueError('ready-limit must be positive')
        backlog = db.execute("SELECT COUNT(*) FROM tasks WHERE status='READY'").fetchone()[0] >= args.ready_limit
        row = task(db, args.id) if args.id else db.execute(
            "SELECT * FROM tasks WHERE status='TODO' AND (?=0 OR work_kind!='implementation') ORDER BY priority DESC,id LIMIT 1",
            (int(backlog),)).fetchone()
        if row is None:
            return {'task': None, 'ready_backlog': backlog,
                    'advice': 'investigate submitted evidence or create a comparison task' if backlog else 'discover a useful task'}
        if row['status'] != 'TODO':
            raise ValueError('task is already owned or is not TODO')
        db.execute("UPDATE tasks SET status='CLAIMED',owner=?,updated_at=? WHERE id=?",
                   (args.agent, now(), row['id']))
        return public_task(db.execute('SELECT * FROM tasks WHERE id=?', (row['id'],)).fetchone())
    if command == 'task-stage':
        row = task(db, args.id)
        if row['owner'] != args.agent or row['status'] != 'CLAIMED':
            raise ValueError('only the current owner of CLAIMED work may record a stage')
        if not args.reason.strip() or (args.evidence is not None and not args.evidence.strip()):
            raise ValueError('stage observations need a reason and nonempty evidence when supplied')
        if args.sha is not None and not re.fullmatch(r'[a-fA-F0-9]{40}', args.sha):
            raise ValueError('stage source must be a full 40-character SHA')
        # An observation is not a task/source update or a proof of passing quality.
        return {'id': public_task(row)['id'], 'phase': args.phase,
                'source_sha': args.sha.lower() if args.sha else None,
                'evidence': args.evidence, 'reason': args.reason,
                'observational': True}
    if command.startswith('task-'):
        row = task(db, args.id)
        if command == 'task-quality-hold':
            reservation(db, args.agent, args.token, args.environment)
            if row['status'] not in ('READY', 'NEEDS_MEASUREMENT') or not row['source_sha']:
                raise ValueError('quality holds apply to submitted candidates; accepted history stays unchanged')
            if not args.evidence.strip() or not args.reason.strip():
                raise ValueError('quality hold requires the observed evidence and investigation reason')
            cur = db.execute('INSERT INTO quality_holds(task_id,base_sha,source_sha,environment,category,evidence,reason,opened_at) '
                             'VALUES (?,?,?,?,?,?,?,?)', (row['id'], row['base_sha'], row['source_sha'],
                             args.environment, args.category, args.evidence, args.reason, now()))
            # The retest of an earlier hold's repair just failed and opened this hold on the
            # repair itself (practice: #2 stayed RETEST_PENDING beside #3). Keep one open line.
            db.execute("UPDATE quality_holds SET state='SUPERSEDED',tested_sha=?,retest_record=?,closed_at=? "
                       "WHERE task_id=? AND state='RETEST_PENDING' AND repair_sha=? AND id<>?",
                       (row['source_sha'], 'superseded by hold #' + str(cur.lastrowid), now(),
                        row['id'], row['source_sha'], cur.lastrowid))
            db.execute("UPDATE tasks SET status='NEEDS_MEASUREMENT',reason=?,updated_at=? WHERE id=?",
                       (args.reason, now(), row['id']))
        elif command == 'task-finish':
            env = reservation(db)
            if args.environment != OFFICIAL:
                raise ValueError('sandbox results are advisory; only the official environment may adopt/reject')
            if args.result == 'BLOCKED':
                if row['owner'] != args.agent or row['status'] not in ('CLAIMED', 'READY', 'NEEDS_MEASUREMENT'):
                    raise ValueError('only the current task owner may block active work')
            elif not env or env['owner'] != args.agent or row['status'] not in ('READY', 'NEEDS_HUMAN', 'NEEDS_MEASUREMENT'):
                raise ValueError('only the environment owner may finish a submitted candidate')
            if args.result == 'ACCEPTED' and (row['review'] == 'human' or row['status'] == 'NEEDS_HUMAN') and not args.human_decision:
                raise ValueError('human-reviewed candidate needs a recorded human decision reference')
            if args.result == 'NEEDS_HUMAN' and not (args.question or '').strip():
                raise ValueError('NEEDS_HUMAN requires --question: the actual choice for the human, not unfinished investigation')
            if args.result == 'ACCEPTED':
                resolve_quality_holds(db, args, row)
            elif args.result == 'REJECTED':
                db.execute("UPDATE quality_holds SET state='ABANDONED',closed_at=? WHERE task_id=? AND state IN ('OPEN','RETEST_PENDING')",
                           (now(), row['id']))
            db.execute('UPDATE tasks SET status=?,reason=?,human_decision=?,human_question=?,updated_at=? WHERE id=?',
                       (args.result, args.reason, args.human_decision, args.question, now(), row['id']))
        elif command == 'task-priority':
            # Practice R2: the DB-bound host made the 3-host split the next thing to measure,
            # but the only way to move it ahead was withdrawing three other READY candidates.
            if row['status'] in ('ACCEPTED', 'REJECTED', 'DONE'):
                raise ValueError('finished tasks keep their priority')
            db.execute('UPDATE tasks SET priority=?,reason=?,updated_at=? WHERE id=?',
                       (args.priority, args.reason, now(), row['id']))
        else:
            if row['owner'] != args.agent:
                raise ValueError('task belongs to another session')
            warnings = []
            if command == 'task-complete':
                if row['status'] != 'CLAIMED' or row['work_kind'] == 'implementation':
                    raise ValueError('only claimed investigation/comparison work may complete without integration')
                db.execute("UPDATE tasks SET status='DONE',reason=?,updated_at=? WHERE id=?",
                           (args.reason, now(), row['id']))
            elif command == 'task-ready':
                if row['status'] != 'CLAIMED':
                    raise ValueError('only CLAIMED tasks may be submitted')
                if not all(re.fullmatch(r'[a-fA-F0-9]{40}', s) for s in (args.base, args.sha)):
                    raise ValueError('submit full 40-character base and source SHAs')
                if row['review'] == 'human' and args.review != 'human':
                    raise ValueError('a human-review candidate keeps that classification when resubmitted')
                db.execute("UPDATE tasks SET status='READY',base_sha=?,source_sha=?,review=?,reason=?,updated_at=? WHERE id=?",
                           (args.base, args.sha, args.review, args.reason, now(), row['id']))
                db.execute("UPDATE quality_holds SET state='RETEST_PENDING',repair_sha=?,repair_submitted_at=? WHERE task_id=? AND state IN ('OPEN','RETEST_PENDING')",
                           (args.sha, now(), row['id']))
                # Practice: T-0007/T-0009 were stacked on T-0001's source while it sat in a
                # quality hold; repairing T-0001 changes that SHA and forces both to rebase.
                held = db.execute("SELECT * FROM quality_holds WHERE state IN ('OPEN','RETEST_PENDING') "
                                  "AND task_id<>? AND (source_sha=? OR repair_sha=?)",
                                  (row['id'], args.base.lower(), args.base.lower())).fetchall()
                warnings = ['base ' + args.base[:7] + ' is the held source of ' + public_task(dict(id=h['task_id']))['id']
                            + ' (hold #' + str(h['id']) + ', ' + h['state'] + '); expect a rebase when it is repaired'
                            for h in held]
            elif command == 'task-withdraw':
                if row['status'] != 'READY':
                    raise ValueError('only READY candidates may be withdrawn; measured results are finished by the integrator')
                env = reservation(db)
                if env and env['owner'] != args.agent and env['purpose'] == public_task(row)['id']:
                    raise ValueError('integration of this candidate is in progress; ask ' + env['owner'] + ' to finish or release it first')
                # The repair stays unsubmitted until the next task-ready names a new SHA.
                db.execute("UPDATE quality_holds SET state='OPEN',repair_sha=NULL,repair_submitted_at=NULL "
                           "WHERE task_id=? AND state='RETEST_PENDING'", (row['id'],))
                db.execute("UPDATE tasks SET status='CLAIMED',reason=?,updated_at=? WHERE id=?",
                           (args.reason, now(), row['id']))
            elif command == 'task-resume':
                if row['status'] not in ('NEEDS_MEASUREMENT', 'BLOCKED'):
                    raise ValueError('only measurement/investigation or blocked work may be resumed')
                db.execute("UPDATE tasks SET status='CLAIMED',reason=?,human_question=NULL,updated_at=? WHERE id=?",
                           (args.reason, now(), row['id']))
            elif command == 'task-release':
                if row['status'] not in ('CLAIMED', 'BLOCKED'):
                    raise ValueError('only CLAIMED/BLOCKED tasks may return to TODO')
                db.execute("UPDATE tasks SET status='TODO',owner=NULL,reason=?,updated_at=? WHERE id=?",
                           (args.reason, now(), row['id']))
            elif command == 'task-handoff':
                if row['status'] not in ('CLAIMED', 'BLOCKED', 'READY', 'NEEDS_HUMAN', 'NEEDS_MEASUREMENT'):
                    raise ValueError('cannot hand off a finished task')
                db.execute('UPDATE tasks SET owner=?,reason=?,updated_at=? WHERE id=?',
                           (args.to, args.reason, now(), row['id']))
            if warnings:
                result = public_task(db.execute('SELECT * FROM tasks WHERE id=?', (row['id'],)).fetchone())
                result['warnings'] = warnings
                return result
        return public_task(db.execute('SELECT * FROM tasks WHERE id=?', (row['id'],)).fetchone())
    if command == 'env-register':
        return register(db, args.db, args.environment, args.config, args.reason)
    if command == 'env-acquire':
        if args.environment != OFFICIAL and not db.execute(
                'SELECT 1 FROM environments WHERE name=?', (args.environment,)).fetchone():
            raise ValueError('register the sandbox and its resources first')
        if reservation(db, environment=args.environment):
            raise ValueError('environment is reserved; inspect status, do not steal it')
        values = (args.agent, uuid.uuid4().hex, args.purpose, now())
        if args.environment == OFFICIAL:
            db.execute('INSERT INTO reservation VALUES (1,?,?,?,?)', values)
        else:
            db.execute('INSERT INTO sandbox_reservations VALUES (?,?,?,?,?)', (args.environment, *values))
        return reservation(db, environment=args.environment)
    previous = reservation(db, args.agent, args.token, args.environment)
    if state_path(args.db, args.environment, '.manual-bench').exists():
        raise ValueError('a portal benchmark is reserved; confirm it ended and record/abandon through target bench before release/handoff')
    if command == 'env-release':
        if args.environment == OFFICIAL:
            db.execute('DELETE FROM reservation')
        else:
            db.execute('DELETE FROM sandbox_reservations WHERE environment=?', (args.environment,))
        return {'released': previous, 'reason': args.reason}
    if command == 'env-handoff':
        values = (args.to, uuid.uuid4().hex, now())
        if args.environment == OFFICIAL:
            db.execute('UPDATE reservation SET owner=?,token=?,acquired_at=?', values)
        else:
            db.execute('UPDATE sandbox_reservations SET owner=?,token=?,acquired_at=? WHERE environment=?',
                       (*values, args.environment))
        return {'environment': reservation(db, environment=args.environment), 'reason': args.reason}
    raise ValueError('unknown command')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', default=os.environ.get('ISUCON_STATE_DB', '/srv/isucon/state/team.sqlite3'))
    p.add_argument('--environment', default=OFFICIAL, type=environment_name)
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('task-list')
    feedback_list = commands.add_parser('feedback-list', help='list recorded advice and its decisions')
    feedback_list.add_argument('--pending', action='store_true', help='only advice without a decision')
    feedback_add = commands.add_parser('feedback-add', help='record advice before deciding its reusable scope')
    feedback_add.add_argument('--agent', required=True)
    feedback_add.add_argument('--source-ref', required=True, help='private message/observation reference')
    feedback_add.add_argument('--summary', required=True)
    feedback_decide = commands.add_parser('feedback-decide', help='record a workflow decision, not code adoption')
    feedback_decide.add_argument('--id', required=True)
    feedback_decide.add_argument('--agent', required=True)
    feedback_decide.add_argument('--decision', required=True, choices=('adopt', 'existing', 'defer', 'reject'))
    feedback_decide.add_argument('--reason', required=True)
    feedback_decide.add_argument('--artifact', required=True, help='existing guidance, investigation, task or commit reference')
    feedback_decide.add_argument('--next-action', help='required for defer; name the next investigation/action')
    pipeline = commands.add_parser('pipeline-status', help='read-only stage timing; missing observations remain unknown')
    pipeline.add_argument('--agent', help='current task owner session to include')
    stage = commands.add_parser('task-stage', help='record a stage start; never a quality gate')
    stage.add_argument('--id', required=True)
    stage.add_argument('--agent', required=True)
    stage.add_argument('--phase', required=True, choices=('analysis', 'implementation', 'validation', 'handoff'))
    stage.add_argument('--reason', required=True)
    stage.add_argument('--sha', help='full source SHA observed, especially for validation')
    stage.add_argument('--evidence', help='reference to the observation; not interpreted as quality proof')
    for name in ('join', 'queue'):
        c = commands.add_parser(name)
        c.add_argument('--ready-limit', type=int, default=2)
        if name == 'join':
            c.add_argument('--agent', required=True)
            c.add_argument('--provider', required=True, choices=('claude', 'codex'))
            c.add_argument('--plugin-version', required=True)
    create = commands.add_parser('task-create')
    create.add_argument('--title', required=True)
    create.add_argument('--evidence', required=True)
    create.add_argument('--priority', type=int, default=50, choices=range(101), metavar='0..100')
    create.add_argument('--hypothesis', help='shared mechanism key; same active key is rejected atomically')
    create.add_argument('--kind', choices=('implementation', 'investigation', 'comparison'), default='implementation')
    create.add_argument('--related', help='existing task ID; use for new investigations after adoption')
    claim = commands.add_parser('task-claim')
    claim.add_argument('--agent', required=True)
    claim.add_argument('--id')
    claim.add_argument('--ready-limit', type=int, default=2)
    for name in ('task-ready', 'task-withdraw', 'task-release', 'task-handoff', 'task-finish', 'task-resume', 'task-complete', 'task-quality-hold', 'task-priority'):
        c = commands.add_parser(name)
        c.add_argument('--id', required=True)
        c.add_argument('--agent', required=True)
        c.add_argument('--reason', required=True)
        if name == 'task-ready':
            c.add_argument('--base', required=True)
            c.add_argument('--sha', required=True)
            c.add_argument('--review', required=True, choices=('auto', 'human'))
        if name == 'task-handoff':
            c.add_argument('--to', required=True)
        if name == 'task-priority':
            c.add_argument('--priority', type=int, required=True, choices=range(101), metavar='0..100')
        if name == 'task-quality-hold':
            c.add_argument('--token', required=True)
            c.add_argument('--evidence', required=True)
            c.add_argument('--category', required=True, choices=('correctness', 'warning', 'timeout', 'conditions', 'unknown'))
        if name == 'task-finish':
            c.add_argument('--result', required=True,
                           choices=('ACCEPTED', 'REJECTED', 'NEEDS_HUMAN', 'NEEDS_MEASUREMENT', 'BLOCKED'))
            c.add_argument('--human-decision', help='reference to the actual human decision; never fabricate one')
            c.add_argument('--question', help='concrete human choice, with alternatives and a recommendation in --reason')
            c.add_argument('--record', help='official promotion record.json required for every adoption')
            c.add_argument('--tested-sha', help='full integrated SHA actually measured in that record')
    inventory = commands.add_parser('env-register')
    inventory.add_argument('--agent', required=True)
    inventory.add_argument('--config', required=True)
    inventory.add_argument('--reason', required=True, help='rules and resource-isolation evidence')
    acquire = commands.add_parser('env-acquire')
    acquire.add_argument('--agent', required=True)
    acquire.add_argument('--purpose', required=True)
    for name in ('env-release', 'env-handoff'):
        c = commands.add_parser(name)
        c.add_argument('--agent', required=True)
        c.add_argument('--token', required=True)
        c.add_argument('--reason', required=True)
        if name == 'env-handoff':
            c.add_argument('--to', required=True)
    return p


def main():
    args = parser().parse_args()
    lock = operation_lock(args.db, args.environment) if args.command in ('env-release', 'env-handoff') else contextlib.nullcontext()
    try:
        if args.command == 'pipeline-status':
            # connect() creates/migrates schema; this observer must never call it.
            print(json.dumps(pipeline_status(args.db, args.agent), ensure_ascii=False, indent=2))
            return 0
        with lock, contextlib.closing(connect(args.db)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            result = dispatch(db, args)
            if args.command in ('task-claim', 'task-ready', 'task-handoff') and isinstance(result, dict) and result.get('id'):
                # Practice: a subagent claimed and submitted T-0010 as "parent"; its return
                # would have reached no member's watch. Name the joined session instead.
                who = args.to if args.command == 'task-handoff' else args.agent
                if db.execute('SELECT 1 FROM members LIMIT 1').fetchone() and not db.execute(
                        'SELECT 1 FROM members WHERE agent=?', (who,)).fetchone():
                    result.setdefault('warnings', []).append(
                        who + ' has not joined; use the joined session ID so returns reach its watch (task-handoff to fix)')
            if args.command not in ('status', 'task-list', 'feedback-list'):
                event(db, args, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, sqlite3.Error, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
