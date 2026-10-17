#!/usr/bin/env python3
"""Measurement quality and physical-run accounting; no target operations."""
import argparse
import datetime
import json
from pathlib import Path
import re
import statistics
import sys
import uuid


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def error_counts(value):
    if value in (None, '', 'none', 'map[]', '{}'):
        return {} if value in ('none', 'map[]', '{}') else None
    if isinstance(value, dict):
        data = value
    elif isinstance(value, str) and value.startswith('map[') and value.endswith(']'):
        items = re.split(r'[ ,]+', value[4:-1].strip())
        try:
            data = dict(item.split(':', 1) for item in items)
        except ValueError:
            return None
    else:
        return None
    try:
        result = {str(k): int(v) for k, v in data.items()}
        return {k: v for k, v in result.items() if v} if all(v >= 0 for v in result.values()) else None
    except (ValueError, TypeError):
        return None


def quality(baseline, candidate, forbidden=()):
    b = [error_counts(s.get('errorCounts', s.get('errors'))) for s in baseline]
    c = [error_counts(s.get('errorCounts', s.get('errors'))) for s in candidate]
    if any(row is None for row in b + c):
        return {'status': 'unknown', 'reason': 'unparsed error summary; investigate before adoption'}
    if any(row.get(kind, 0) for row in c for kind in forbidden):
        return {'status': 'failed', 'reason': 'a configured correctness error occurred'}
    if any(row.get(kind, 0) for row in b for kind in forbidden):
        return {'status': 'unknown', 'reason': 'baseline contains a configured correctness error; fix comparison basis'}
    if not any(c):
        return {'status': 'pass', 'reason': 'candidate samples have no reported errors'}
    kinds = set().union(*b, *c)
    if set().union(*c) - set().union(*b):
        return {'status': 'unknown', 'reason': 'a new error type occurred; investigate'}
    # A higher request volume can increase counts; compare only known denominators.
    if not all(isinstance(s.get('requests'), int) and not isinstance(s['requests'], bool)
               and s['requests'] > 0 for s in baseline + candidate):
        return {'status': 'unknown', 'reason': 'nonzero errors need request denominators, types and latency investigation'}
    rates = []
    for samples, counts in ((baseline, b), (candidate, c)):
        denominator = sum(s['requests'] for s in samples)
        totals = {kind: sum(row.get(kind, 0) for row in counts) for kind in kinds}
        if any(n > denominator for n in totals.values()):
            return {'status': 'unknown', 'reason': 'an error count exceeds its request denominator'}
        rates.append({kind: n / denominator for kind, n in totals.items()})
    increased = [kind for kind in kinds if rates[1][kind] > rates[0][kind]]
    return {'status': 'unknown' if increased else 'pass',
            'reason': 'error rate increased; investigate' if increased else 'known error rates did not increase',
            'baselineRates': rates[0], 'candidateRates': rates[1]}


def assess(baseline, candidate, stable, bundle, min_bp=300, minimum=2, max_age=60, forbidden=()):
    if minimum < 1 or max_age < 1 or min_bp < 0:
        raise ValueError('sample count/age must be positive and improvement threshold nonnegative')
    ignored = sum(bool(s.get('observed')) for s in baseline + candidate)
    baseline = [s for s in baseline if s.get('deployedRevision') == stable and not s.get('observed')]
    candidate = [s for s in candidate if not s.get('observed')]
    def fresh(s):
        try:
            age = (now() - datetime.datetime.fromisoformat(s['finishedAt'].replace('Z', '+00:00'))).total_seconds()
            return 0 <= age <= max_age * 60
        except (ValueError, KeyError, TypeError):
            return False
    retired = sum(not fresh(s) for s in baseline)
    baseline = [s for s in baseline if fresh(s)]
    b = sorted(s['score'] for s in baseline)
    c = sorted(s['score'] for s in candidate)
    bp = None
    q = {'status': 'unknown', 'reason': 'missing comparable samples'}
    blocked = True
    if any(s.get('pass') is not True for s in candidate):
        decision, reason, action = 'reject', 'a candidate sample failed correctness (pass=false)', 'reject'
    elif not baseline or not candidate or any(s.get('pass') is not True for s in baseline):
        decision, reason, action = 'inconclusive', 'need passing baseline and candidate samples', 'remeasure'
    elif len({s.get('deployedRevision') for s in candidate}) != 1 or any(not s.get('deployedRevision') for s in candidate):
        decision, reason, action = 'inconclusive', 'candidate revisions differ; measure one fixed candidate', 'remeasure'
    elif any(s.get('stableBundleId') != bundle for s in baseline + candidate):
        decision, reason, action = 'inconclusive', 'stable bundle/measurement conditions differ; take fresh samples', 'remeasure'
    elif len({json.dumps(s.get('resourceFingerprints'), sort_keys=True) for s in candidate}) != 1:
        decision, reason, action = 'inconclusive', 'candidate resources changed between samples', 'remeasure'
    else:
        q = quality(baseline, candidate, forbidden)
        blocked = q['status'] != 'pass'
        if q['status'] == 'failed':
            decision, reason, action = 'reject', q['reason'], 'reject'
        elif blocked:
            decision, reason, action = 'inconclusive', q['reason'], 'investigate'
        elif len(b) < minimum or len(c) < minimum or statistics.median(b) <= 0:
            decision, reason, action = 'inconclusive', f'need {minimum} comparable samples per revision and a positive baseline', 'remeasure'
        else:
            bm, cm = statistics.median(b), statistics.median(c)
            bp = int((cm - bm) * 10000 // bm)
            if bp <= 0:
                decision, reason, action = 'reject', f'candidate median {cm} does not beat baseline {bm}', 'reject'
            elif bp < min_bp or c[0] <= b[-1]:
                decision, reason, action = 'inconclusive', 'improvement/noise not separated; remeasure within the physical-run budget', 'remeasure'
            else:
                decision, reason, action = 'promote', f'median improved {bp} bp and worst candidate {c[0]} > best baseline {b[-1]}', 'promote'
    if ignored:
        reason += f' ({ignored} observed under the slow log were left out)'
    return {'ruleVersion': 'plugin-rule-v2', 'decision': decision, 'reason': reason, 'nextAction': action,
            'quality': q, 'qualityBlockPromotion': blocked, 'minimumImprovementBasisPoints': min_bp,
            'minimumSamples': minimum, 'improvementBasisPoints': bp, 'baselineScores': b, 'candidateScores': c,
            'baselineRevisions': sorted({s.get('deployedRevision', '') for s in baseline}),
            'candidateRevisions': sorted({s.get('deployedRevision', '') for s in candidate}),
            'observedSamplesIgnored': ignored, 'staleBaselineSamplesIgnored': retired,
            'stableBundleId': bundle, 'decidedAt': now().isoformat()}


def attempts(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def reserve(path, experiment, label, revision, per_exp, total, per_hour, recovery_reserve, candidate):
    rows = attempts(path)
    if min(per_exp, total, per_hour) <= 0 or not 0 <= recovery_reserve < per_exp:
        raise ValueError('budgets must be positive and 0 <= RECOVERY_BENCH_RESERVE < MAX_BENCH_PER_EXP')
    recent = sum((now() - datetime.datetime.fromisoformat(r['startedAt'])).total_seconds() < 3600 for r in rows)
    count = sum(r['experiment'] == experiment for r in rows) if experiment else 0
    if len(rows) >= total or recent >= per_hour:
        raise ValueError('physical-run total/hour budget exhausted, including baseline, recovery and no-result attempts')
    if experiment and count >= per_exp - (recovery_reserve if candidate else 0):
        raise ValueError('experiment physical-run budget exhausted or final recovery slot reserved')
    row = {'id': uuid.uuid4().hex, 'experiment': experiment or None, 'label': label,
           'revision': revision, 'startedAt': now().isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        f.write(json.dumps(row) + '\n')
        f.flush()
        import os
        os.fsync(f.fileno())
    return row


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='action', required=True)
    e = sub.add_parser('evaluate')
    e.add_argument('out'); e.add_argument('stable'); e.add_argument('bundle')
    e.add_argument('min_bp', type=int); e.add_argument('minimum', type=int); e.add_argument('max_age', type=int)
    e.add_argument('forbidden'); e.add_argument('samples', nargs=argparse.REMAINDER)
    b = sub.add_parser('reserve')
    for name in ('path', 'experiment', 'label', 'revision'):
        b.add_argument(name)
    for name in ('per_exp', 'total', 'per_hour', 'recovery_reserve', 'candidate'):
        b.add_argument(name, type=int)
    s = sub.add_parser('summary'); s.add_argument('path')
    a = p.parse_args()
    if a.action == 'evaluate':
        split = a.samples.index('--')
        def load(paths):
            return [json.loads(Path(path).read_text()) for path in paths if Path(path).is_file()]
        result = assess(load(a.samples[:split]), load(a.samples[split + 1:]), a.stable, a.bundle,
                        a.min_bp, a.minimum, a.max_age, tuple(filter(None, a.forbidden.split(','))))
        Path(a.out).write_text(json.dumps(result, indent=2) + '\n')
    elif a.action == 'reserve':
        result = reserve(Path(a.path), a.experiment or None, a.label, a.revision,
                         a.per_exp, a.total, a.per_hour, a.recovery_reserve, a.candidate)
    else:
        rows = attempts(Path(a.path))
        result = {'physicalRuns': len(rows), 'lastHour': sum((now() - datetime.datetime.fromisoformat(r['startedAt'])).total_seconds() < 3600 for r in rows)}
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        sys.exit(str(error))
