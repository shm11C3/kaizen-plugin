#!/usr/bin/env python3
"""Compare two practice reports; checks submitted data, not the remote hosts.

Both variants use the same report format. Missing evidence is not a zero.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import statistics
import sys

CONDITIONS = ('problem', 'initialRevision', 'environmentSpec', 'models', 'agentCount',
              'durationMinutes', 'inferenceBudget', 'humanPolicy', 'externalHintsHash',
              'measurementHarnessRevision')


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(label + ' must be a finite nonnegative number')
    return value


def instant(value):
    time = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if time.tzinfo is None:
        raise ValueError('timestamps need a timezone')
    return time


def summarize(report):
    conditions = report['conditions']
    if any(key not in conditions or conditions[key] in (None, '', {}, []) for key in CONDITIONS):
        raise ValueError('all comparison conditions must be recorded')
    duration = number(conditions['durationMinutes'], 'durationMinutes')
    number(conditions['agentCount'], 'agentCount')
    if not duration or not conditions['agentCount'] or int(conditions['agentCount']) != conditions['agentCount']:
        raise ValueError('durationMinutes and agentCount must be positive')
    start = instant(report['startedAt'])
    first = report.get('firstVerifiedPromotion')
    first_minutes = None
    if first is not None:
        if not first.get('artifact'):
            raise ValueError('first promotion needs an evidence artifact')
        first_minutes = (instant(first['at']) - start).total_seconds() / 60
        if not 0 <= first_minutes <= duration:
            raise ValueError('first promotion is outside the trial deadline')
    end = report.get('finalVerification')
    final_score = None
    if end is not None:
        if not end.get('revision') or not end.get('artifact'):
            raise ValueError('final verification needs a revision and evidence artifact')
        selected_minutes = (instant(end['selectedAt']) - start).total_seconds() / 60
        if not 0 <= selected_minutes <= duration:
            raise ValueError('final revision must be selected before the deadline')
        if end.get('restartPassed') is True and end.get('correctnessPassed') is True:
            scores = [number(value, 'score') for value in end['scores']]
            if len(scores) < 2:
                raise ValueError('final verification needs at least two score samples')
            final_score = statistics.median(scores)
    interventions = report.get('humanInterventions')
    if interventions is not None:
        if not isinstance(interventions, list) or any(not e.get('artifact') for e in interventions):
            raise ValueError('human interventions need evidence; null means unrecorded')
        for event in interventions:
            elapsed = (instant(event['at']) - start).total_seconds() / 60
            if not 0 <= elapsed <= duration:
                raise ValueError('human intervention is outside the trial deadline')
    intervals = report.get('failureRecoveryIntervals')
    lost_minutes = None
    if intervals is not None:
        spans = []
        for event in intervals:
            begin, finish = instant(event['startedAt']), instant(event['endedAt'])
            if not event.get('artifact') or begin < start or finish < begin or (finish - start).total_seconds() > duration * 60:
                raise ValueError('failure/recovery intervals need evidence and must fit the trial')
            spans.append((begin, finish))
        # Union overlapping failure/recovery intervals; never double count.
        merged = []
        for begin, finish in sorted(spans):
            if merged and begin <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(finish, merged[-1][1]))
            else:
                merged.append((begin, finish))
        lost_minutes = sum((finish - begin).total_seconds() / 60 for begin, finish in merged)
    return dict(variant=report['variant'], final_valid_score_median=final_score,
                first_verified_promotion_minutes=first_minutes,
                human_interventions=len(interventions) if interventions is not None else None,
                failure_recovery_minutes=lost_minutes,
                final_verification_reported=end is not None)


def compare(left, right):
    results = [summarize(left), summarize(right)]
    differences = [key for key in CONDITIONS if left['conditions'][key] != right['conditions'][key]]
    if differences:
        raise ValueError('conditions differ: ' + ', '.join(differences))
    return dict(conditions_match=True, results=results,
                conclusion='Descriptive paired trial only. Artifacts and hosts are not verified by this tool; repeat trials before claiming an advantage.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left')
    parser.add_argument('right')
    args = parser.parse_args()
    try:
        print(json.dumps(compare(json.loads(Path(args.left).read_text()),
                                 json.loads(Path(args.right).read_text())), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
