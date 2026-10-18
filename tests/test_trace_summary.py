import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import trace_summary as module

TRACE, OTHER_TRACE = '1' * 32, '2' * 32


def attr(key, value):
    return dict(Key=key, Value=dict(Type='STRING' if isinstance(value, str) else 'INT64', Value=value))


def span(number, start=0, end=100, parent=None, name='http.request', trace=TRACE, attributes=()):
    return dict(Name=name, SpanContext=dict(TraceID=trace, SpanID=f'{number:016x}'),
                Parent=dict(TraceID=trace if parent is not None else '0' * 32,
                            SpanID=f'{parent or 0:016x}'), SpanKind=2 if name.startswith('http') else 3,
                StartTime=f'2026-10-19T00:00:00.{start:03d}000000Z',
                EndTime=f'2026-10-19T00:00:00.{end:03d}000000Z',
                Attributes=list(attributes), Status=dict(Code='Unset', Description=''))


class TraceSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'trace.json'

    def summary(self, spans, **options):
        self.path.write_text('\n'.join(json.dumps(item, indent=2) for item in spans))
        original = self.path.read_bytes()
        result = module.summarize(self.path, 'observe-001/raw-trace', **options)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(result['source']['sha256'], hashlib.sha256(original).hexdigest())
        return result

    def test_nested_and_parallel_db_sum_is_distinct_from_union_and_http_duration(self):
        result = self.summary([span(1), span(2, 10, 60, 1, 'sql.conn.query'),
                               span(3, 40, 80, 1, 'sql.conn.exec'), span(4, 20, 30, 2, 'sql.stmt.query')])
        self.assertEqual(result['status'], 'ok')
        trace = result['traces'][0]
        self.assertEqual(trace['spanWindowNs'], 100000000)
        self.assertEqual(trace['spanDurationSumNs'], 200000000)
        self.assertEqual(trace['category']['db'], dict(spanCount=3, sumNs=100000000, unionNs=70000000))
        request = trace['httpRequests'][0]
        self.assertEqual(request['observedDbSpanCount'], 3)
        self.assertEqual(request['dbUnionWithinHttpNs'], 70000000)
        self.assertEqual(request['httpOutsideObservedDbNs'], 30000000)
        self.assertEqual(request['dbCoverage'], 'observed')

    def test_db_intervals_are_clipped_to_http_and_orphans_do_not_attach(self):
        result = self.summary([span(1), span(2, 90, 110, 1, 'sql.conn.query'),
                               span(3, 20, 40, 999, 'sql.conn.exec')])
        trace = result['traces'][0]
        self.assertEqual(trace['httpRequests'][0]['dbUnionWithinHttpNs'], 10000000)
        self.assertEqual(trace['httpRequests'][0]['observedDbSpanCount'], 1)
        self.assertEqual(trace['orphanSpanIds'], ['0000000000000003'])
        self.assertEqual(trace['category']['db']['unionNs'], 40000000)

    def test_no_db_is_unknown_instrumentation_or_sampling_not_zero_query_proof(self):
        result = self.summary([span(1)])
        self.assertEqual(result['summary']['httpWithoutObservedDbCount'], 1)
        self.assertEqual(result['traces'][0]['httpRequests'][0]['dbCoverage'], 'unknown')
        self.assertIn('not proof of zero queries', ' '.join(result['limitations']))

    def test_multiple_go_pretty_json_objects_and_arrays(self):
        first, second = span(1), span(2, trace=OTHER_TRACE)
        result = self.summary([first, second])
        self.assertEqual(result['summary']['traceCount'], 2)
        self.path.write_text(json.dumps([first, second]))
        self.assertEqual(module.summarize(self.path, 'observe-1')['summary']['spanCount'], 2)

    def test_missing_and_cross_trace_parents_remain_visible(self):
        first, second = span(1), span(2, parent=1, name='sql.conn.query', trace=OTHER_TRACE)
        missing = span(3)
        missing.pop('Parent')
        result = self.summary([first, second, missing])
        self.assertEqual(result['summary']['orphanSpanCount'], 2)

    def test_static_allowlist_drops_sql_urls_descriptions_events_and_unknown_names(self):
        raw = span(1, name='HTTP GET /customer/SECRET', attributes=[
            attr('http.request.method', 'GET'), attr('http.route', '/customer/{id}'),
            attr('url.full', 'https://SECRET'), attr('db.query.text', 'SELECT SECRET'),
            attr('password', 'SECRET')])
        raw.update(Status=dict(Code='Error', Description='SECRET'),
                   Events=[dict(Name='SECRET')], Links=[dict(SECRET='SECRET')],
                   Resource=[attr('service.name', 'SECRET')])
        result = self.summary([raw], allowed_routes=['/customer/{id}'])
        text = json.dumps(result)
        self.assertNotIn('SECRET', text)
        self.assertEqual(result['traces'][0]['spans'][0]['name'], 'HTTP GET /customer/{id}')
        self.assertEqual(result['summary']['errorSpanCount'], 1)
        without_routes = self.summary([raw])
        self.assertNotIn('/customer/', json.dumps(without_routes))
        self.assertEqual(without_routes['traces'][0]['spans'][0]['name'], 'http.request')

    def test_nanoseconds_and_timezone_offsets_are_exact(self):
        raw = span(1)
        raw['StartTime'] = '2026-10-19T09:00:00.123456789+09:00'
        raw['EndTime'] = '2026-10-19T00:00:00.123456792Z'
        result = self.summary([raw])
        self.assertEqual(result['traces'][0]['spans'][0]['durationNs'], 3)

    def test_empty_invalid_truncated_or_wrong_shape_fails_without_partial_summary(self):
        valid = json.dumps(span(1))
        for text in ('', ' ', '{}', '[]', 'not json SECRET', valid+'\n{"Name":', '[null]',
                     valid.replace('"SpanKind": 2', '"SpanKind": NaN')):
            with self.subTest(text=text[:10]):
                self.path.write_text(text)
                result = module.summarize(self.path, 'observe-1')
                self.assertEqual(result['status'], 'failed')
                self.assertNotIn('traces', result)
                self.assertNotIn('SECRET', json.dumps(result))
                self.assertEqual(self.path.read_text(), text)

    def test_invalid_and_missing_timestamps_fail(self):
        for value in (None, '2026-10-19T00:00:00', '2026-99-19T00:00:00Z', '0001-01-01T00:00:00Z'):
            with self.subTest(value=value):
                raw = span(1)
                raw['StartTime'] = value
                self.assertEqual(self.summary([raw])['status'], 'failed')
        raw = span(1, 90, 10)
        self.assertEqual(self.summary([raw])['status'], 'failed')

    def test_duplicate_identity_and_parent_cycles_fail(self):
        self.assertEqual(self.summary([span(1), span(1)])['status'], 'failed')
        self.assertEqual(self.summary([span(1, parent=2), span(2, parent=1)])['status'], 'failed')

    def test_cli_binds_source_observation_and_preserves_input_on_failure(self):
        self.path.write_text('broken SECRET')
        output = self.path.parent / 'summary.json'
        command = [sys.executable, str(ROOT/'scripts/trace_summary.py'), str(self.path),
                   '--observation', 'observe-1/trace', '--output', str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        summary = json.loads(output.read_text())
        self.assertEqual(summary['source']['observationRef'], 'observe-1/trace')
        self.assertEqual(self.path.read_text(), 'broken SECRET')
        command[-1] = str(self.path)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
        self.assertEqual(self.path.read_text(), 'broken SECRET')
        alias = self.path.parent / 'hardlink.json'
        os.link(self.path, alias)
        command[-1] = str(alias)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
        self.assertEqual(self.path.read_text(), 'broken SECRET')


if __name__ == '__main__':
    unittest.main()
