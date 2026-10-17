#!/usr/bin/env python3
"""Read experiment evidence and flag reasons to reconsider the next experiment.

Advisory only: never changes a decision, deploys, or requests human approval.
"""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys


def timestamp(value):
    time = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if time.tzinfo is None:
        raise ValueError('history timestamp needs a timezone')
    return time


def analyze(project, window=3, minutes=30):
    root = Path(project) / '.kaizen'
    records, warnings = [], []
    state = {}
    if (root / 'state.env').exists():
        state = dict(line.split('=', 1) for line in (root / 'state.env').read_text().splitlines() if '=' in line)
    for path in sorted((root / 'experiments').glob('*/record.json')):
        try:
            record = json.loads(path.read_text())
            if not isinstance(record['experimentId'], str):
                raise ValueError('experimentId must be a string')
            metadata = record['manifest'].get('strategy') or {}
            if not isinstance(metadata, dict) or not isinstance(metadata.get('parameters') or {}, dict):
                raise ValueError('strategy and parameters must be objects')
            if not isinstance(record.get('ruleDecision'), dict):
                raise ValueError('ruleDecision is missing')
            if record['manifest'].get('hypothesisId') and not isinstance(record['manifest']['hypothesisId'], str):
                raise ValueError('hypothesisId must be a string')
            record['manifest']['strategy'] = metadata
            start = timestamp(record['manifest']['startedAt'])
            end = timestamp(record['closedAt'])
            if end < start:
                raise ValueError('closedAt precedes startedAt')
            if state.get('LOOP_STARTED_AT') and start < timestamp(state['LOOP_STARTED_AT']):
                continue
            record['_start'], record['_end'] = start, end
            record['_path'] = str(path.relative_to(Path(project)))
            records.append(record)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            warnings.append(f'{path}: unusable history ({error})')
    records.sort(key=lambda r: (r['_end'], r['experimentId']))
    signals = []
    since_gain = []
    for record in records:
        # A discretionary promotion is not evidence that the fixed score rule passed.
        if record.get('finalDecision') == 'promote' and record.get('ruleDecision', {}).get('decision') == 'promote':
            since_gain = []
        else:
            since_gain.append(record)
    spent = sum((r['_end'] - r['_start']).total_seconds() / 60 for r in since_gain)
    if len(since_gain) >= window or (since_gain and spent >= minutes):
        signals.append(dict(kind='no_verified_gain', experiments=[r['experimentId'] for r in since_gain],
                            experiment_minutes=round(spent, 1),
                            action='Separate noise/quality/recovery problems from a wrong bottleneck; compare another mechanism before another small tweak.'))
    groups = defaultdict(list)
    for record in records:
        manifest = record['manifest']
        key = manifest.get('hypothesisId')
        if key:
            stable = record.get('stableBefore') or manifest.get('stableRevision')
            if stable:
                groups[(stable, key)].append(record)
    for (_, key), group in groups.items():
        if group[-1] is not records[-1]:
            continue  # Old reviewed mechanisms must not keep every later task in review.
        if len(group) >= 2:
            signals.append(dict(kind='repeated_hypothesis', hypothesis=key,
                                experiments=[r['experimentId'] for r in group],
                                action='State the new evidence or changed mechanism; unchanged retries have no new information.'))
        parameters = defaultdict(list)
        for record in group:
            for name, value in (record['manifest'].get('strategy', {}).get('parameters') or {}).items():
                parameters[name].append((record['experimentId'], value))
        for name, values in parameters.items():
            if len(values) >= 3 and values[-3][1] == values[-1][1] != values[-2][1]:
                signals.append(dict(kind='parameter_oscillation', hypothesis=key, parameter=name,
                                    trials=values[-3:], action='Explain the limiting resource and a bounded comparison before changing this parameter again.'))
    return dict(schemaVersion='v1', closed_experiments=len(records),
                rule_verified_promotions=sum(r.get('finalDecision') == 'promote' and r.get('ruleDecision', {}).get('decision') == 'promote' for r in records),
                review_needed=bool(signals), signals=signals, warnings=warnings,
                advice='Reconsider the plan at a stable boundary; continue AI investigation. Escalate only a concrete risk/tradeoff choice.' if signals else 'Use current evidence and scoring impact to choose the next experiment.')


def render_review(summary):
    lines = ['# Strategy review', '', 'Advisory signals, not proof of a plateau or permission to waive quality.', '']
    for signal in summary['signals']:
        lines += [f"- {signal['kind']}: {json.dumps(signal, ensure_ascii=False)}"]
    if not summary['signals']:
        lines += ['- No automatic signal. A new observation or disproved prediction can still justify review.']
    lines += ['', '## AI investigation', '',
              '- Current stable/bundle and scoring term affected:',
              '- Observation: processing time versus waiting; CPU/DB/lock/network limit:',
              '- Why the previous prediction failed; noise/quality/restore versus mechanism:',
              '- Options: continue/refine, different mechanism, structural change, stop/freeze:',
              '- For each: evidence, expected score effect (uncertain), total minutes including measurement/recovery, dependencies, risk:',
              '- Cheapest observation that distinguishes the leading explanations:',
              '- Selected next task and disproof/stop condition:',
              '- Human choice only if needed: concrete options, completed comparisons, recommendation:',
              '', '## Allocation', '',
              '- Inspect shared queue; merge duplicate hypotheses and retire stale assumptions.',
              '- With READY backlog: claim investigation/comparison work against existing artifacts.',
              '- Keep roles dynamic; only the integration owner performs shared target actions.',
              '- Record the revised order and reason in plan.md; preserve the human strategy.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--window', type=int, default=3)
    parser.add_argument('--minutes', type=float, default=30)
    parser.add_argument('command', choices=('status', 'review'))
    args = parser.parse_args()
    if args.window < 2 or args.minutes <= 0:
        parser.error('window must be >=2 and minutes must be positive')
    try:
        summary = analyze(args.project, args.window, args.minutes)
        print(json.dumps(summary, ensure_ascii=False, indent=2) if args.command == 'status' else render_review(summary))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
