#!/usr/bin/env python3
"""Measure real Go/Rust linters on isolated, dependency-free fixtures (no servers)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new directory for clones, caches and raw evidence')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, GOCACHE=str(output/'go-cache'), GOTOOLCHAIN='local', GOFLAGS='',
                       CARGO_NET_OFFLINE='true', RUSTFLAGS='', CARGO_ENCODED_RUSTFLAGS='',
                       CARGO_BUILD_WARNINGS='warn', RUSTC_WRAPPER='', RUSTC_WORKSPACE_WRAPPER='',
                       CARGO_TARGET_DIR=str(output/'rust-target'), CARGO_BUILD_BUILD_DIR=str(output/'rust-build'))
    started = time.time()
    report = dict(startedAtEpoch=started, platform=platform.platform(), machine=platform.machine(),
                  cpuCount=os.cpu_count(), cachePolicy='empty dedicated GOCACHE / Cargo target and build-dir; installed toolchain standard libraries retained',
                  environment={key: environment.get(key) for key in ['GOTOOLCHAIN', 'GOFLAGS', 'RUSTFLAGS',
                               'CARGO_ENCODED_RUSTFLAGS', 'CARGO_BUILD_WARNINGS', 'CARGO_INCREMENTAL',
                               'CARGO_NET_OFFLINE', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER',
                               'CARGO_TARGET_DIR', 'CARGO_BUILD_BUILD_DIR']},
                  versions={}, fixtureHashes={},
                  runnerHashes={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in [ROOT/'scripts/check.py', Path(__file__).resolve()]}, runs=[])
    for name, command in [('go', ['go', 'version']), ('cargo', ['cargo', '--version']),
                          ('rustc', ['rustc', '--version']), ('clippy', ['cargo', 'clippy', '--version']),
                          ('rustfmt', ['rustfmt', '--version'])]:
        report['versions'][name] = subprocess.check_output(command, env=environment, text=True).strip()

    def save():
        report['wallSeconds'] = round(time.time()-started, 6)
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')

    def commit(project, message):
        subprocess.run(['git', '-C', str(project), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(project), '-c', 'commit.gpgsign=false',
                        'commit', '-qm', message], check=True)

    def check(language, case, tool, command, mode=None, expected='passed'):
        project = output/language
        env = environment
        invocation = [sys.executable, str(ROOT/'scripts/check.py'), '--project', str(project),
                      '--label', case+'-'+tool, '--timeout', '120']
        if mode:
            invocation += ['--diagnostics', mode]
        begin = time.monotonic()
        process = subprocess.run(invocation+['--']+command, env=env, capture_output=True, text=True)
        record = json.loads(process.stdout)
        raw = Path(record['log']).read_text()
        row = dict(language=language, case=case, tool=tool, command=command,
                   wrapperExitCode=process.returncode, wrapperWallSeconds=round(time.monotonic()-begin, 6),
                   check=record, nativeOutput=raw)
        report['runs'].append(row)
        save()
        print(f"{language} {case} {tool}: {record['status']} native={record['exitCode']} {record['durationSeconds']:.3f}s", flush=True)
        assert record['status'] == expected, (language, case, tool, record['status'], raw)
        assert record['sourceBefore'] == record['sourceAfter'], 'source changed during command'
        return row

    def lint(language, case, format_status='passed', lint_status='passed'):
        if language == 'go':
            check(language, case, 'format', ['gofmt', '-l', 'main.go', 'main_test.go'], 'gofmt', format_status)
            return check(language, case, 'vet', ['go', 'vet', './...'], expected=lint_status)
        check(language, case, 'format', ['cargo', 'fmt', '--check'], expected=format_status)
        return check(language, case, 'clippy', ['cargo', 'clippy', '--locked', '--all-targets',
                     '--message-format=json', '--', '--no-deps'], 'cargo', lint_status)

    for language in ['go', 'rust']:
        project = output/language
        shutil.copytree(ROOT/'tests/fixtures/lint'/language, project)
        (project/'.gitignore').write_text('.kaizen/\ntarget/\n')
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
        subprocess.run(['git', '-C', str(project), 'config', 'user.name', 'lint fixture'], check=True)
        subprocess.run(['git', '-C', str(project), 'config', 'user.email', 'fixture@example.test'], check=True)
        commit(project, 'initial formatted fixture')
        for file in sorted((ROOT/'tests/fixtures/lint'/language).rglob('*')):
            if file.is_file():
                report['fixtureHashes'][str(file.relative_to(ROOT))] = hashlib.sha256(file.read_bytes()).hexdigest()
        source = project/('main.go' if language == 'go' else 'src/lib.rs')
        original = source.read_text()
        lint(language, 'initial')
        for number in range(1, 4):
            lint(language, f'warm-{number}')

        changed = (original.replace('"fare",', '"computed fare",') if language == 'go'
                   else original.replace('distance <= limit', 'limit >= distance'))
        source.write_text(changed); commit(project, 'small valid source edit')
        lint(language, 'edited')

        source.write_text(original.replace('func main() {', 'func main(){') if language == 'go'
                          else original.replace('distance: u64', 'distance:u64'))
        commit(project, 'intentional formatting defect')
        lint(language, 'unformatted', 'needs_review' if language == 'go' else 'failed')

        broken = (original.replace('"value", fare', 'fare') if language == 'go'
                  else original.replace('distance <= limit', 'distance == distance'))
        source.write_text(broken); commit(project, 'intentional lint defect that compiles')
        check(language, 'defect', 'build', ['go', 'build', '-o', str(output/'go-fixture'), '.']
              if language == 'go' else ['cargo', 'build', '--locked'])
        lint(language, 'defect', lint_status='failed')

        if language == 'rust':
            source.write_text(original.replace('distance <= limit', 'return distance <= limit;'))
            commit(project, 'intentional advisory warning')
            warning = lint(language, 'advisory', lint_status='needs_review')
            assert warning['check']['exitCode'] == 0
            assert any((item.get('code') or {}).get('code') == 'clippy::needless_return'
                       for item in warning['check']['diagnostics'])

        source.write_text(original); commit(project, 'repair formatting and lint defects')
        lint(language, 'repaired')
        check(language, 'repaired', 'tests', ['go', 'test', '-count=1', './...'] if language == 'go'
              else ['cargo', 'test', '--locked'])
    report['allAssertionsPassed'] = True
    save()
    print(str(output/'report.json'))


if __name__ == '__main__':
    main()
