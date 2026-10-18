#!/usr/bin/env python3
"""Summarize Go stdouttrace artifacts without emitting SQL, URLs or event data."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

METHODS = {'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT', 'OPTIONS', 'TRACE', 'PATCH', 'OTHER'}
OPERATIONS = {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CALL', 'BEGIN', 'COMMIT', 'ROLLBACK',
              'CONNECT', 'QUERY', 'EXEC', 'PREPARE', 'PING', 'OTHER'}
SYSTEMS = {'mysql', 'mariadb', 'postgresql', 'sqlite', 'mssql', 'oracle', 'other_sql'}
SQL_NAMES = {'sql.' + owner + '.' + operation for owner, operations in {
    'conn': ('query', 'exec', 'begin', 'begin_tx', 'prepare', 'ping', 'reset_session', 'close', 'connect'),
    'tx': ('commit', 'rollback'), 'stmt': ('query', 'exec', 'prepare', 'close'),
    'rows': ('next', 'close'), 'connector': ('connect',),
}.items() for operation in operations}
NAMES = SQL_NAMES | {'http.request', 'http.server', 'db.query', 'db.exec'}
LIMITATIONS = [
    'Span duration sums include nesting and parallel work; they are not wall time or CPU time.',
    'DB union within HTTP is clipped to that HTTP interval; its remainder is not a CPU attribution.',
    'Missing DB spans mean unknown instrumentation/sampling coverage, not proof of zero queries.',
    'Orphan parents may be unsampled, remote or missing from the artifact; coverage is not assumed complete.',
    'Only declared static names/routes and allowlisted operation attributes are emitted. Raw artifacts are retained.',
]


class TraceInputError(ValueError):
    pass


def timestamp_ns(value):
    if not isinstance(value, str):
        raise TraceInputError('timestamp must be an RFC3339 string')
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)', value)
    if not match:
        raise TraceInputError('timestamp must include a valid timezone and at most nanosecond precision')
    try:
        base = datetime.datetime.fromisoformat(match[1] + match[3].replace('Z', '+00:00'))
        if base.year == 1:
            raise ValueError('zero Go time')
        delta = base - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    except ValueError:
        raise TraceInputError('invalid or unfinished timestamp') from None
    return (delta.days * 86400 + delta.seconds) * 1000000000 + int((match[2] or '').ljust(9, '0') or '0')


def parse_stream(text):
    def invalid_constant(value):
        raise TraceInputError('non-finite JSON number')
    decoder, offset, spans = json.JSONDecoder(parse_constant=invalid_constant), 0, []
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        try:
            value, offset = decoder.raw_decode(text, offset)
        except json.JSONDecodeError:
            raise TraceInputError('invalid or truncated JSON stream') from None
        values = value if isinstance(value, list) else [value]
        if any(not isinstance(span, dict) for span in values):
            raise TraceInputError('each stdouttrace span must be an object')
        spans.extend(values)
    if not spans:
        raise TraceInputError('empty trace artifact')
    return spans


def identifier(value, length, zero=False):
    if not isinstance(value, str) or not re.fullmatch('[a-fA-F0-9]{' + str(length) + '}', value):
        raise TraceInputError('missing or invalid trace/span identifier')
    result = value.lower()
    if not zero and result == '0' * length:
        raise TraceInputError('zero trace/span identifier')
    return result


def attributes(raw, allowed_routes):
    output = {}
    items = raw.get('Attributes') or []
    if not isinstance(items, list):
        raise TraceInputError('Attributes must be an array')
    for item in items:
        if not isinstance(item, dict):
            raise TraceInputError('attribute entries must be objects')
        key, value = item.get('Key'), item.get('Value')
        value = value.get('Value') if isinstance(value, dict) else None
        if key == 'http.request.method' and isinstance(value, str) and value in METHODS:
            output[key] = value
        elif key == 'http.route' and isinstance(value, str) and value in allowed_routes:
            output[key] = value
        elif key == 'http.response.status_code' and type(value) is int and 100 <= value <= 599:
            output[key] = value
        elif key in ('db.system.name', 'db.system') and isinstance(value, str) and value in SYSTEMS:
            output['db.system.name'] = value
        elif key in ('db.operation.name', 'db.operation') and isinstance(value, str):
            output['db.operation.name'] = value.upper() if value.upper() in OPERATIONS else 'OTHER'
    return output


def normalize(raw, allowed_routes, allowed_names):
    context = raw.get('SpanContext')
    if not isinstance(context, dict) or not isinstance(raw.get('Name'), str):
        raise TraceInputError('span needs Name and SpanContext')
    trace, span = identifier(context.get('TraceID'), 32), identifier(context.get('SpanID'), 16)
    start, end = timestamp_ns(raw.get('StartTime')), timestamp_ns(raw.get('EndTime'))
    if end < start:
        raise TraceInputError('span ends before it starts')
    parent, parent_trace, parent_state = None, None, 'missing'
    if isinstance(raw.get('Parent'), dict):
        parent_trace = identifier(raw['Parent'].get('TraceID'), 32, zero=True)
        parent = identifier(raw['Parent'].get('SpanID'), 16, zero=True)
        if parent == '0' * 16:
            parent, parent_state = None, 'root'
        else:
            parent_state = 'referenced'
    attrs = attributes(raw, allowed_routes)
    name = raw['Name']
    kind = raw.get('SpanKind')
    category = ('db' if name in SQL_NAMES or name.startswith('db.') or 'db.system.name' in attrs or 'db.operation.name' in attrs
                else 'http' if kind == 2 or name.startswith('HTTP ') or name.startswith('http.') or 'http.request.method' in attrs
                else 'internal')
    safe_name = name if name in NAMES | allowed_names else None
    if category == 'http' and attrs.get('http.request.method') and attrs.get('http.route'):
        safe_name = 'HTTP ' + attrs['http.request.method'] + ' ' + attrs['http.route']
    if safe_name is None:
        safe_name = {'db': 'db.operation', 'http': 'http.request', 'internal': '<redacted>'}[category]
    status = raw.get('Status')
    code = status.get('Code') if isinstance(status, dict) else None
    state = ({0: 'unset', 1: 'ok', 2: 'error', 'Unset': 'unset', 'Ok': 'ok', 'Error': 'error'}.get(code, 'unknown')
             if type(code) in (int, str) else 'unknown')
    return dict(traceId=trace, spanId=span, parentSpanId=parent, parentTraceId=parent_trace,
                parentState=parent_state, name=safe_name, nameRedacted=safe_name != name, category=category,
                startNs=start, endNs=end, durationNs=end-start, status=state,
                error=state == 'error' or attrs.get('http.response.status_code', 0) >= 500, attributes=attrs)


def union_ns(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum(end-start for start, end in merged)


def trace_group(trace, spans):
    by_id = {span['spanId']: span for span in spans}
    if len(by_id) != len(spans):
        raise TraceInputError('duplicate span identity in one trace')
    for span in spans:
        if span['parentState'] == 'referenced':
            span['parentState'] = ('connected' if span['parentTraceId'] == trace and span['parentSpanId'] in by_id else 'orphan')
        seen, current = set(), span
        while current is not None:
            if current['spanId'] in seen:
                raise TraceInputError('parent cycle in trace')
            seen.add(current['spanId'])
            current = by_id.get(current['parentSpanId']) if current['parentTraceId'] == trace else None
    def descends(span, ancestor):
        while span['parentState'] == 'connected':
            if span['parentSpanId'] == ancestor:
                return True
            span = by_id[span['parentSpanId']]
        return False
    http = []
    for request in (span for span in spans if span['category'] == 'http'):
        database = [span for span in spans if span['category'] == 'db' and descends(span, request['spanId'])]
        clipped = [(max(span['startNs'], request['startNs']), min(span['endNs'], request['endNs']))
                   for span in database if span['startNs'] < request['endNs'] and span['endNs'] > request['startNs']]
        observed = union_ns(clipped)
        http.append(dict(spanId=request['spanId'], name=request['name'], durationNs=request['durationNs'],
                         observedDbSpanCount=len(database), dbSpanDurationSumNs=sum(span['durationNs'] for span in database),
                         dbUnionWithinHttpNs=observed, httpOutsideObservedDbNs=request['durationNs']-observed,
                         dbCoverage='observed' if database else 'unknown'))
    categories = {kind: dict(spanCount=len(selected), sumNs=sum(s['durationNs'] for s in selected),
                             unionNs=union_ns([(s['startNs'], s['endNs']) for s in selected]))
                  for kind in ('http', 'db', 'internal')
                  for selected in [[s for s in spans if s['category'] == kind]]}
    return dict(traceId=trace, rootSpanIds=[s['spanId'] for s in spans if s['parentState'] == 'root'],
                orphanSpanIds=[s['spanId'] for s in spans if s['parentState'] in ('orphan', 'missing')],
                spanWindowNs=max(s['endNs'] for s in spans)-min(s['startNs'] for s in spans),
                observedSpanUnionNs=union_ns([(s['startNs'], s['endNs']) for s in spans]),
                spanDurationSumNs=sum(s['durationNs'] for s in spans), category=categories,
                httpRequests=http, spans=spans)


def summarize(path, observation, allowed_routes=(), allowed_names=()):
    path = Path(path).resolve()
    source = dict(artifact=str(path), sha256=None, observationRef=observation)
    try:
        raw = path.read_bytes()
        source['sha256'] = hashlib.sha256(raw).hexdigest()
        try:
            parsed = parse_stream(raw.decode('utf-8'))
        except UnicodeDecodeError:
            raise TraceInputError('trace artifact is not UTF-8 JSON') from None
        spans = [normalize(span, set(allowed_routes), set(allowed_names)) for span in parsed]
        groups = {}
        for span in spans:
            groups.setdefault(span['traceId'], []).append(span)
        traces = [trace_group(trace, grouped) for trace, grouped in sorted(groups.items())]
        summary = dict(traceCount=len(traces), spanCount=len(spans), errorSpanCount=sum(s['error'] for s in spans),
                       orphanSpanCount=sum(len(trace['orphanSpanIds']) for trace in traces),
                       redactedNameCount=sum(s['nameRedacted'] for s in spans),
                       unknownStatusCount=sum(s['status'] == 'unknown' for s in spans),
                       httpWithoutObservedDbCount=sum(h['dbCoverage'] == 'unknown' for t in traces for h in t['httpRequests']))
        return dict(status='ok', source=source, summary=summary, traces=traces, limitations=LIMITATIONS)
    except (TraceInputError, OSError) as error:
        return dict(status='failed', source=source, errors=[dict(kind='invalid-artifact',
                    message=str(error) if isinstance(error, TraceInputError) else 'trace artifact cannot be read')], limitations=LIMITATIONS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact', type=Path)
    parser.add_argument('--observation', required=True, help='observation artifact or immutable reference')
    parser.add_argument('--allow-route', action='append', default=[], help='declared static route pattern, never a request URL')
    parser.add_argument('--allow-name', action='append', default=[], help='additional declared static span name')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = summarize(args.artifact, args.observation, args.allow_route, args.allow_name)
    text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        if (args.output.resolve() == args.artifact.resolve()
                or (args.output.exists() and args.artifact.exists() and args.output.samefile(args.artifact))):
            parser.error('output must not overwrite the original trace artifact')
        args.output.write_text(text)
    else:
        sys.stdout.write(text)
    return 0 if result['status'] == 'ok' else 2


if __name__ == '__main__':
    sys.exit(main())
