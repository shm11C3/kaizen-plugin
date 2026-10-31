import importlib.util
import json
from pathlib import Path
import subprocess
import _git_test_env  # Keep fixture Git commands independent of the invoking repository.
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_remote_go', ROOT / 'scripts/check_remote_go.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class RemoteCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / 'go').mkdir()
        (self.project / 'sql').mkdir()
        (self.project / 'go/go.mod').write_text('module example\ngo 1.24\n')
        (self.project / 'go/main_test.go').write_text('package main\n')
        (self.project / 'sql/1-schema.sql').write_text('CREATE TABLE fixture (id INT);\n')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=test', '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        self.calls = []
        self.test_exit = 0
        self.test_output = b'--- PASS: TestFixture (0.01s)\nPASS\n'
        self.temp_path = '/var/tmp/kaizen-check.ABC123'

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args], text=True)

    def runner(self, arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        code, output = 0, b''
        if arguments[:2] == ['go', 'version']:
            output = b'go version go1.24 linux/amd64\n'
        elif arguments[:3] == ['go', 'test', '-c']:
            self.assertEqual(kwargs['env']['CGO_ENABLED'], '0')
            self.assertEqual(kwargs['env']['GOOS'], 'linux')
            self.assertEqual(kwargs['env']['GOARCH'], 'amd64')
            Path(arguments[4]).write_bytes(b'cross-compiled-test-binary')
        elif arguments[0] == 'ssh':
            command = arguments[-1]
            if command.startswith('mktemp'):
                output = (self.temp_path + '\n').encode()
            elif 'sudo -n python3' in command:
                self.assertNotIn('secret-password', command)
                payload = json.loads(kwargs['input'])
                self.assertEqual(payload['env']['TEST_DSN'], 'user:secret-password@unix(/test)')
                code, output = self.test_exit, self.test_output
        else:
            self.fail(str(arguments))
        return subprocess.CompletedProcess(arguments, code, output)

    def execute(self, revision=None, includes=('sql/1-schema.sql',)):
        return checker.execute(self.project, revision or self.revision, 'fixture', 'TestFixture',
                               'lane-a-app', '/path/ssh_config', {'TEST_DSN': 'user:secret-password@unix(/test)'},
                               includes=includes, runner=self.runner)

    def test_source_hashes_env_redaction_and_cleanup(self):
        self.test_output += b'user:secret-password@unix(/test) secret-password\n'
        result = self.execute()
        self.assertTrue(result['passed'])
        self.assertEqual(result['sourceRevision'], self.revision)
        self.assertEqual(result['sourceTree'], self.git('rev-parse', 'HEAD^{tree}').strip())
        self.assertEqual(result['artifactSha256']['sql/1-schema.sql'], checker.checksum((self.project / 'sql/1-schema.sql').read_bytes()))
        self.assertEqual(result['binarySha256'], checker.checksum(b'cross-compiled-test-binary'))
        self.assertTrue(result['cleanupPassed'])
        self.assertNotIn('secret-password', Path(result['log']).read_text())
        self.assertNotIn('secret-password', Path(result['record']).read_text())
        self.assertEqual(self.calls[-1][0][-1], 'rm -rf -- /var/tmp/kaizen-check.ABC123')
        self.assertTrue(all('/home/isucon/webapp' not in str(item) for item in self.calls))

    def test_failure_remains_failure_and_cleans_up(self):
        self.test_exit, self.test_output = 1, b'--- FAIL: TestFixture (0.01s)\nFAIL\n'
        result = self.execute()
        self.assertFalse(result['passed'])
        self.assertEqual(result['exitCode'], 1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failedTests'], ['TestFixture'])
        self.assertTrue(result['cleanupPassed'])

    def test_wrong_ref_and_missing_include_never_contact_remote(self):
        for revision, includes in [('main', ('sql/1-schema.sql',)), ('f' * 40, ('sql/1-schema.sql',)),
                                   (self.revision, ('sql/missing.sql',))]:
            result = self.execute(revision, includes)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(self.calls, [])

    def test_cleanup_refuses_untrusted_temp_path(self):
        self.temp_path = '/home/isucon/webapp'
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(any(call[0][-1].startswith('rm ') for call in self.calls))
        for path in ('/var/tmp/kaizen-check.ABC123/..', '/var/tmp/kaizen-check.x;rm', '/var/tmp/other.ABC123'):
            with self.assertRaises(ValueError):
                checker.remote_path(path)

    def test_skips_and_empty_selection_are_not_hidden(self):
        self.test_output = b'--- SKIP: TestFixture (0.00s)\nPASS\n'
        result = self.execute()
        self.assertFalse(result['passed'])
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['skippedTests'], ['TestFixture'])
        self.test_output = b'testing: warning: no tests to run\nPASS\n'
        self.assertEqual(self.execute()['status'], 'no_tests')

    def test_outside_sync_paths_and_no_test_sources_fail(self):
        result = self.execute(includes=('outside/file.sql',))
        self.assertEqual(result['status'], 'failed')
        (self.project / 'go/main_test.go').unlink()
        self.git('add', '-u')
        self.git('-c', 'user.name=test', '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'no tests')
        result = self.execute(self.git('rev-parse', 'HEAD').strip())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.calls, [])

    def test_successful_build_without_binary_fails(self):
        def no_binary(arguments, **kwargs):
            if arguments[:3] == ['go', 'test', '-c']:
                return subprocess.CompletedProcess(arguments, 0, b'[no test files]\n')
            return self.runner(arguments, **kwargs)
        result = checker.execute(self.project, self.revision, 'missing-binary', None,
                                 'lane-a-app', '', {}, includes=('sql/1-schema.sql',), runner=no_binary)
        self.assertFalse(result['passed'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['exitCode'], 2)


if __name__ == '__main__':
    unittest.main()
