"""Observational timing from existing task events; no scheduling or quality proof."""
import contextlib
import datetime
import json
from pathlib import Path
import sqlite3

PHASES = ('analysis', 'implementation', 'validation', 'handoff')
BOUNDARIES = {'task-ready', 'task-release', 'task-resume', 'task-handoff',
              'task-finish', 'task-complete', 'task-claim', 'task-quality-hold'}


def timestamp(value):
    result = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp has no timezone')
    return result.astimezone(datetime.timezone.utc)


def seconds(start, end):
    return round((end - start).total_seconds(), 6)


def union_seconds(intervals):
    """Do not count concurrent tasks or observations twice."""
    merged = []
    for start, end in sorted(intervals):
        if end < start:
            raise ValueError('negative interval')
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return round(sum((end - start).total_seconds() for start, end in merged), 6)


def task_timing(row, events, as_of):
    intervals, cycles, observations, issues = [], [], [], []
    active = cycle = last = latest_ready = first_ready = None
    stage_times = []
    phase_intervals = {phase: [] for phase in PHASES}
    claim_intervals = []

    def close_stage(at, ongoing=False):
        nonlocal active
        if active is not None:
            start, details, actor = active
            item = {'phase': details['phase'], 'actor': actor,
                    'startedAt': start.isoformat(), 'endedAt': at.isoformat(),
                    'seconds': seconds(start, at), 'ongoing': ongoing,
                    'sourceSha': details.get('source_sha'),
                    'submittedSourceMatch': None}
            intervals.append(item)
            stage_times.append((start, at))
            phase_intervals[details['phase']].append((start, at))
            active = None

    def close_cycle(at, ready=False, ongoing=False):
        nonlocal cycle
        if cycle is not None:
            start, actor, action, first_interval = cycle
            span = (start, at)
            claim_intervals.append(span)
            known = [(timestamp(i['startedAt']), timestamp(i['endedAt']))
                     for i in intervals[first_interval:]]
            elapsed = seconds(start, at)
            cycles.append({'actor': actor, 'startedBy': action,
                           'startedAt': start.isoformat(), 'endedAt': at.isoformat(),
                           'readyAt': at.isoformat() if ready else None,
                           'claimToReadySeconds': elapsed if ready and action != 'task-handoff' else None,
                           'elapsedSeconds': elapsed, 'ongoing': ongoing,
                           'unclassifiedSeconds': round(elapsed - union_seconds(known), 6)})
            cycle = None

    for event in events:
        try:
            at = timestamp(event['at'])
            if at > as_of or (last is not None and at < last):
                raise ValueError('clock moved backwards or event is in the future')
        except (AttributeError, TypeError, ValueError):
            issues.append({'eventId': event['id'], 'reason': 'unusable or nonmonotonic timestamp; interval unknown'})
            active = cycle = last = latest_ready = None
            continue
        last = at
        action, details, actor = event['action'], event['details'], event['actor']
        if action == 'task-stage':
            if details.get('phase') not in PHASES:
                issues.append({'eventId': event['id'], 'reason': 'unknown stage; interval unknown'})
                active = None
                continue
            close_stage(at)
            active = (at, details, actor)
            observations.append({'at': at.isoformat(), 'actor': actor, 'phase': details['phase'],
                                 'sourceSha': details.get('source_sha'),
                                 'evidence': details.get('evidence')})
        elif action in BOUNDARIES:
            close_stage(at)
            if action == 'task-ready':
                if cycle is not None:
                    for interval in intervals[cycle[3]:]:
                        observed = interval['sourceSha']
                        interval['submittedSourceMatch'] = (
                            observed.lower() == details['source_sha'].lower()
                            if observed and details.get('source_sha') else None)
                close_cycle(at, ready=True)
                latest_ready = at
                first_ready = first_ready or at
            elif action == 'task-handoff':
                # Ownership changes end its activity observation, not the task's
                # claim-to-ready cycle. A missing original claim stays unknown.
                if cycle is None and details.get('status') == 'CLAIMED':
                    cycle = (at, details.get('owner', actor), action, len(intervals))
            else:
                close_cycle(at)
                if action in ('task-claim', 'task-resume') and details.get('status') == 'CLAIMED':
                    cycle = (at, details.get('owner', actor), action, len(intervals))
                latest_ready = None
    close_stage(as_of, ongoing=True)
    close_cycle(as_of, ongoing=True)
    return {
        'id': 'T-{:04d}'.format(row['id']), 'title': row['title'], 'owner': row.get('owner'),
        'status': row['status'], 'sourceSha': row.get('source_sha'),
        'stageObservations': observations, 'stageIntervals': intervals, 'workCycles': cycles,
        'phaseSeconds': {phase: (round(sum(i['seconds'] for i in intervals if i['phase'] == phase), 6)
                                 if phase_intervals[phase] else None)
                         for phase in PHASES},
        'knownStageSecondsUnion': union_seconds(stage_times),
        'unclassifiedClaimedSeconds': (round(sum(c['unclassifiedSeconds'] for c in cycles), 6)
                                       if cycles and not issues else None),
        'firstReadyAt': first_ready.isoformat() if first_ready is not None else None,
        'submittedAt': latest_ready.isoformat() if latest_ready is not None else None,
        'submittedAgeSeconds': (seconds(latest_ready, as_of)
                                if latest_ready is not None and row['status'] == 'READY' else None),
        'readyToIntegrationSeconds': None,
        'timingIssues': issues,
    }, stage_times, phase_intervals


def summarize(rows, events, as_of, agent=None):
    grouped = {row['id']: [] for row in rows}
    for event in events:
        try:
            details = json.loads(event['details'])
            name = details.get('id')
            task_id = int(name[2:]) if isinstance(name, str) and name.startswith('T-') else None
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if task_id in grouped and event['action'].startswith('task-'):
            grouped[task_id].append({**event, 'details': details})
    tasks, all_intervals = [], []
    phases = {phase: [] for phase in PHASES}
    for row in rows:
        if agent is not None and row.get('owner') != agent:
            continue
        item, intervals, task_phases = task_timing(row, grouped[row['id']], as_of)
        tasks.append(item)
        all_intervals.extend(intervals)
        for phase in PHASES:
            phases[phase].extend(task_phases[phase])
    return {
        'asOf': as_of.isoformat(), 'agent': agent, 'tasks': tasks,
        'knownStageSecondsSum': round(sum(i['seconds'] for t in tasks for i in t['stageIntervals']), 6),
        'knownStageSecondsUnion': union_seconds(all_intervals),
        'phaseUnionSeconds': {phase: union_seconds(spans) if spans else None for phase, spans in phases.items()},
        'readyTasks': [t['id'] for t in tasks if t['status'] == 'READY'],
        'limitations': [
            'Stage intervals describe the main task activity observed by its owner, not quality proof.',
            'Concurrent SubAgent work inside one task is not captured; these are not total worker hours or complete phase durations.',
            'Intervals before the first stage or across missing lifecycle events are unknown.',
            'Submitted age may include integration; exact READY-to-integration time is unknown.',
            'The agent filter selects current ownership and retains earlier owners in that task history.',
        ],
    }


def read_status(path, agent=None):
    # mode=ro prevents creation. Avoid team.connect(), migrations and event writes.
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=10)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        rows = [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY id')]
        has_events = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
        events = ([dict(row) for row in db.execute('SELECT id,at,actor,action,details FROM events ORDER BY id')]
                  if has_events else [])
        return summarize(rows, events, datetime.datetime.now(datetime.timezone.utc), agent)
