#!/usr/bin/env python3
"""Unattended integration owner for the shared competition environment.

Runs on the control host as the isucon user and takes the role a human-started
session held before: pick a READY candidate, compose it onto the current
stable, measure it with the kaizen scripts under the reservation, let the fixed
rule decide, record, push, release. Every target operation goes through
scripts/team/target.py, so the reservation, the process lock and every refusal
inside the kaizen scripts still apply; this file adds no new way to touch the
servers.

When explicitly enabled, the model is consulted for a bounded contract review of the
composed diff before any benchmark slot is spent (`claude -p` on the control
host, Amazon Bedrock credentials from the instance role). The rule, not the
model, decides adoption. While nothing is READY the loop sleeps and spends no
tokens; a `pause` file in the state directory stops it from taking new work.

Commands:
  run                      poll the ledger; one candidate at a time; idle otherwise
  once                     process at most one candidate, then exit
  status                   print the current status.json and pause state
  pause [--reason R] / resume
  result --label L --result 'pass=.. score=.. errors=..' [--requests N] [--seconds N]
                           hand a portal (BENCH_MODE=manual) result to the waiting integrator
  abandon --label L --reason R
  dashboard                regenerate the static dashboard now
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from candidate_checks import run_checks

ROOT = Path(__file__).resolve().parents[2]
TEAM = ROOT / 'scripts/team/team.py'
TARGET = ROOT / 'scripts/team/target.py'
DASHBOARD = ROOT / 'scripts/team/dashboard.py'
GIT_IDENTITY = ['-c', 'user.name=kaizen-integrator', '-c', 'user.email=integrator@control-host.invalid',
                '-c', 'commit.gpgsign=false']
DEFAULTS = {
    'agent': 'integrator-control-01',
    'github_user': '',
    'poll_seconds': 30,
    'review': 'none',
    'checks': [],
    'accept_human_review': False,
    'push': True,
    'remote': 'origin',
    'pause_on_error': True,
    'dashboard_dir': '',
    'llm': {
        'command': ['claude', '-p', '--output-format', 'json', '--no-session-persistence', '--tools', '',
                    '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--permission-mode', 'dontAsk',
                    '--max-turns', '1'],
        'model': '',
        'max_budget_usd': 1.0,
        'timeout_seconds': 300,
        'max_diff_bytes': 60000,
    },
}
REVIEW_PROMPT = '''You are the integration reviewer of an ISUCON team. One candidate is about to spend a benchmark slot on the shared competition environment. Decide whether it may proceed and describe it for the experiment manifest.

Answer with exactly one JSON object and nothing else, with these keys:
  "proceed": true or false
  "reasons": list of short strings (why it is returned, or the notable risks)
  "hypothesis": one sentence: what is slow, what the change does, which scoring path improves
  "changeSummary": one or two sentences describing what the diff actually does
  "expectedEffect": one sentence
  "scoringPath": a few words
  "risks": list of short strings

Write every string value in Japanese. Return the candidate (proceed=false) only for contract violations visible in the diff: it does something other than the task claims; it mixes unrelated hypotheses; it weakens or bypasses correctness checks, validation, or benchmark-facing behaviour; it hardcodes expected results; it edits files outside the application, configuration or SQL paths; it is empty. Doubts about the size of the effect, noise, or style are not reasons to return it: the fixed rule measures those.
'''


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')


def write_json(path, data):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def read_state(project):
    try:
        return dict(line.split('=', 1) for line in (project / '.kaizen/state.env').read_text().splitlines() if '=' in line)
    except OSError:
        return {}


def parse_json_object(text):
    """The model answers with one JSON object; tolerate fences and prose around it."""
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('no JSON object in the model answer')
    return json.loads(text[start:end + 1])


def hold_category(decision):
    reason = (decision.get('quality') or {}).get('reason', '') + ' ' + decision.get('reason', '')
    reason = reason.lower()
    if 'timeout' in reason or 'timed out' in reason:
        return 'timeout'
    if 'warning' in reason or 'warn' in reason:
        return 'warning'
    if any(word in reason for word in ('denominator', 'fresh', 'stale', 'comparable', 'bundle', 'condition')):
        return 'conditions'
    return 'unknown'


class StepError(Exception):
    pass


class BudgetExhausted(StepError):
    pass


class SampleAbandoned(StepError):
    pass


class Integrator:
    def __init__(self, args):
        self.db = Path(args.db)
        self.config_path = Path(args.config)
        self.state_dir = Path(args.state) if args.state else self.db.parent / 'integrator'
        settings_path = Path(args.settings) if args.settings else self.state_dir / 'integrator.json'
        self.settings = dict(DEFAULTS)
        self.settings['llm'] = dict(DEFAULTS['llm'])
        if settings_path.is_file():
            loaded = json.loads(settings_path.read_text())
            self.settings['llm'].update(loaded.pop('llm', {}) or {})
            self.settings.update(loaded)
        self.agent = self.settings['agent']
        for name in ('inbox', 'feedback'):
            (self.state_dir / name).mkdir(parents=True, exist_ok=True)
        self.token = None
        self.stopping = False
        self.project = None
        self.plugin_root = None
        self.config = {}
        self.processed = 0
        self.last_state = None
        if (self.state_dir / 'status.json').is_file():
            try:
                self.processed = int(json.loads((self.state_dir / 'status.json').read_text()).get('candidatesProcessed') or 0)
            except (ValueError, OSError):
                self.processed = 0

    # -- bookkeeping -----------------------------------------------------------------

    def ledger(self, event, **fields):
        entry = {'at': now(), 'event': event}
        entry.update(fields)
        with (self.state_dir / 'ledger.jsonl').open('a') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def status(self, state, detail, **fields):
        previous = {}
        path = self.state_dir / 'status.json'
        if path.is_file():
            try:
                previous = json.loads(path.read_text())
            except ValueError:
                previous = {}
        data = {'agent': self.agent, 'state': state, 'detail': detail, 'task': fields.get('task'),
                'experiment': fields.get('experiment'), 'step': fields.get('step'),
                'since': previous.get('since') if previous.get('state') == state and previous.get('task') == fields.get('task') else now(),
                'updatedAt': now(), 'lastError': fields.get('lastError', previous.get('lastError')),
                'candidatesProcessed': self.processed}
        write_json(path, data)
        self.last_state = state

    def paused(self):
        return (self.state_dir / 'pause').exists()

    def pause(self, reason):
        (self.state_dir / 'pause').write_text(now() + ' ' + reason + '\n')
        self.ledger('pause', reason=reason)

    def dashboard(self):
        out = Path(self.settings['dashboard_dir'] or (self.state_dir / 'dashboard'))
        if not DASHBOARD.is_file() or self.project is None:
            return
        result = subprocess.run([sys.executable, str(DASHBOARD), '--db', str(self.db), '--project', str(self.project),
                                 '--state', str(self.state_dir), '--out', str(out)], capture_output=True, text=True)
        if result.returncode:
            self.ledger('error', message='dashboard: ' + result.stderr.strip()[-500:])

    # -- subprocess helpers ----------------------------------------------------------

    def team(self, *args):
        result = subprocess.run([sys.executable, str(TEAM), '--db', str(self.db), *args], capture_output=True, text=True)
        if result.returncode:
            raise StepError('team ' + args[0] + ': ' + result.stderr.strip()[-800:])
        return json.loads(result.stdout)

    def target(self, action, *args):
        if not self.token:
            raise StepError('no reservation token for target ' + action)
        result = subprocess.run([sys.executable, str(TARGET), '--agent', self.agent, '--token', self.token,
                                 '--db', str(self.db), '--config', str(self.config_path), action, *args],
                                capture_output=True, text=True)
        if result.returncode:
            message = (result.stderr.strip() + '\n' + result.stdout.strip()).strip()[-1500:]
            if 'budget' in message.lower():
                raise BudgetExhausted('target ' + action + ': ' + message)
            raise StepError('target ' + action + ' ' + ' '.join(args[:2]) + ': ' + message)
        return result

    def git(self, *args, cwd=None):
        result = subprocess.run(['git', '-C', str(cwd or self.project), *args], capture_output=True, text=True)
        if result.returncode:
            raise StepError('git ' + ' '.join(args[:3]) + ': ' + result.stderr.strip()[-800:])
        return result.stdout

    def blob(self, revision, path, cwd=None):
        result = subprocess.run(['git', '-C', str(cwd or self.project), 'rev-parse', '-q', '--verify', revision + ':' + path],
                                capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None

    # -- configuration ---------------------------------------------------------------

    def load_target(self):
        if not self.config_path.is_file():
            raise StepError('対象が未設定です（' + str(self.config_path) + '）')
        config = json.loads(self.config_path.read_text())
        if not all(config.get(key) is True for key in ('enabled', 'confirmed_rules', 'confirmed_recovery_drill')):
            raise StepError('対象のルール確認・復旧ドリルが未確認のため操作は無効')
        self.project = Path(config['project']).resolve()
        self.plugin_root = Path(config['plugin_root']).resolve()
        if not (self.project / '.kaizen/config.sh').is_file():
            raise StepError('プロジェクトの preset がありません: ' + str(self.project / '.kaizen/config.sh'))
        script = ('. "$KAIZEN_PLUGIN_ROOT/scripts/lib.sh"; load_config; printf "%s\\n" "$STABLE_BRANCH" "$MIN_SAMPLES" '
                  '"$MAX_BENCH_PER_EXP" "$BASELINE_MAX_AGE_MINUTES" "$BENCH_MODE" "$RESOURCE_PATHS" "$OVERLAY_DIR" "$EVALUATION_RULE"')
        result = subprocess.run(['bash', '-c', script], cwd=str(self.project), capture_output=True, text=True,
                                env=dict(os.environ, KAIZEN_PROJECT=str(self.project), KAIZEN_PLUGIN_ROOT=str(self.plugin_root)))
        if result.returncode:
            raise StepError('kaizen 設定を読めません: ' + result.stderr.strip()[-500:])
        values = result.stdout.splitlines()
        keys = ('stable_branch', 'min_samples', 'max_bench_per_exp', 'baseline_max_age_minutes', 'bench_mode',
                'resource_paths', 'overlay_dir', 'evaluation_rule')
        self.config = dict(zip(keys, values + [''] * (len(keys) - len(values))))
        self.config['min_samples'] = int(self.config['min_samples'] or 2)
        self.config['max_bench_per_exp'] = int(self.config['max_bench_per_exp'] or 6)
        self.config['baseline_max_age_minutes'] = int(self.config['baseline_max_age_minutes'] or 60)
        if not self.settings['github_user']:
            raise StepError('integrator.json に github_user（exp/ ブランチの所有者ログイン）が必要です')

    def preflight(self):
        """Return None when a candidate may be processed, else the reason to wait."""
        if self.paused():
            return 'paused'
        try:
            self.load_target()
        except StepError as error:
            return str(error)
        status = self.team('status')
        reservation = status.get('environment')
        if reservation and reservation.get('owner') != self.agent:
            return '環境は ' + reservation['owner'] + ' が占有中（' + reservation.get('purpose', '') + '）'
        if reservation and reservation.get('owner') == self.agent:
            return self.recover_reservation(reservation)
        state = read_state(self.project)
        if state.get('CURRENT_EXPERIMENT'):
            return '実験 ' + state['CURRENT_EXPERIMENT'] + ' が統合Agent外で開いています。先に記録してください'
        if state.get('REVERT_PENDING') == '1':
            return '失敗した候補が配備されたままです。先に復旧してください'
        if not state.get('STABLE_REV'):
            return 'STABLE_REV が未設定です。対象を初期化してください'
        if not (self.project / '.kaizen/stable-bundle.json').is_file():
            return 'stable bundle がありません。先に stable.sh capture'
        if (self.project / '.kaizen/manual-bench.json').exists():
            return '統合Agent外でポータルベンチが予約中です'
        return None

    def recover_reservation(self, reservation):
        """After a restart the ledger may still name this agent; release only a proven idle target."""
        token_file = self.state_dir / 'reservation.json'
        if not token_file.is_file():
            return 'この統合Agentが占有を持っていますが token を失っています。管理者が env-handoff してください'
        saved = json.loads(token_file.read_text())
        state = read_state(self.project)
        if state.get('CURRENT_EXPERIMENT') or state.get('REVERT_PENDING') == '1' or (self.project / '.kaizen/manual-bench.json').exists():
            self.pause('再起動時に未完了の実験または復旧待ちがありました。対象を確認してから resume')
            return '再起動時に未完了の対象操作を検出したため一時停止'
        self.token = saved['token']
        self.release('統合Agent再起動: 実験なし・対象は idle')
        return '再起動後に残っていた占有を解放'

    # -- candidate selection ---------------------------------------------------------

    def next_candidate(self):
        rows = [row for row in self.team('task-list') if row['status'] == 'READY' and row.get('base_sha') and row.get('source_sha')]
        rows = [row for row in rows if row.get('review') != 'human' or self.settings['accept_human_review']]
        rows.sort(key=lambda row: (-int(row.get('priority') or 0), int(row['id'][2:])))
        return rows[0] if rows else None

    # -- the candidate ---------------------------------------------------------------

    def run_once(self):
        reason = self.preflight()
        if reason:
            self.status('paused' if reason == 'paused' else 'waiting', '一時停止中（pause ファイル）' if reason == 'paused' else reason)
            return False
        task = self.next_candidate()
        if task is None:
            self.status('idle', 'READY の候補なし')
            return False
        self.process(task)
        return True

    def process(self, task):
        tid = task['id']
        self.ledger('pick', task=tid, title=task['title'], priority=task.get('priority'), owner=task.get('owner'),
                    source=task['source_sha'], base=task['base_sha'])
        experiment = None
        try:
            self.status('working', '環境を占有中', task=tid, step='acquire')
            self.acquire(tid)
            self.status('working', '提出ソースを取得中', task=tid, step='fetch')
            self.fetch_sources(task)
            self.status('working', 'stable へ合成（dry run）', task=tid, step='compose')
            composed = self.dry_compose(task)
            self.ledger('compose', task=tid, status=composed['status'], files=composed['files'], message=composed.get('message'))
            if composed['status'] != 'ok':
                self.return_task(task, composed['message'])
                return
            self.status('working', '契約レビュー', task=tid, step='review')
            verdict = self.review(task, composed)
            if verdict and not verdict.get('proceed'):
                self.return_task(task, 'レビュー: ' + '; '.join(str(r) for r in verdict.get('reasons') or ['理由なし']))
                return
            self.status('working', 'baseline 計測', task=tid, step='baseline')
            self.ensure_baseline(tid)
            self.status('working', '実験を開始', task=tid, step='open')
            experiment = self.open_experiment(task)
            self.status('working', 'stable へ合成', task=tid, experiment=experiment, step='compose')
            candidate = self.compose(task)
            self.fill_manifest(experiment, task, composed, verdict, candidate)
            self.status('working', '統合SHAの既存テスト・Lint', task=tid, experiment=experiment, step='checks')
            if not self.check_candidate(task, experiment, candidate):
                return
            if self.stopping:
                self.target('evaluate')
                self.target('experiment', 'record', '--override', 'inconclusive', '停止要求: 配備前の確認を終えてstableを維持')
                self.return_task(task, '停止要求のため配備せず返却。実施済みQAの記録は保持')
                return
            self.status('working', candidate[:7] + ' を配備中', task=tid, experiment=experiment, step='deploy')
            started = time.monotonic()
            self.target('deploy', candidate)
            self.ledger('deploy', task=tid, experiment=experiment, sha=candidate, durationSeconds=round(time.monotonic() - started, 1))
            decision = self.measure(tid, experiment)
            self.status('working', '記録中: ' + decision['decision'], task=tid, experiment=experiment, step='record')
            record = self.record(experiment, decision)
            self.finish(task, experiment, record, candidate)
            self.processed += 1
        except BudgetExhausted as error:
            self.ledger('budget', task=tid, experiment=experiment, message=str(error)[-500:])
            self.status('waiting', 'ベンチ予算が尽きたため候補は READY のまま待機', task=tid, experiment=experiment)
        except Exception as error:  # noqa: BLE001 - one candidate must never take the loop down silently
            self.handle_error(task, experiment, error)
        finally:
            self.release('候補 ' + tid + ' の処理終了。対象は stable または採用版')
            if self.last_state == 'working':
                self.status('idle', tid + ' の処理を終えました')
            self.dashboard()

    def check_candidate(self, task, experiment, candidate):
        """Reuse native check.py receipts; no model or new testing framework."""
        receipts, error = [], None
        try:
            receipts = run_checks(self.project, candidate, self.settings['checks'], self.state_dir)
        except (ValueError, OSError, subprocess.SubprocessError) as failure:
            error = str(failure)[-1000:]
        if not receipts and not error:
            self.ledger('checks', task=task['id'], experiment=experiment, revision=candidate,
                        status='not_configured', checks=[])
            return True

        def infrastructure(receipt):
            native = receipt.get('nativeResult') or {}
            return (receipt.get('launcherError') or not receipt.get('sourceIntegrityPassed')
                    or native.get('timedOut') or native.get('interrupted')
                    or native.get('exitCode') in (124, 127, 130)
                    or (native.get('diagnosticsComplete') is False and not compiler_error(receipt)))

        def compiler_error(receipt):
            return any(item.get('level') in ('error', 'failure-note')
                       for item in (receipt.get('nativeResult') or {}).get('diagnostics', []))

        blocking = [receipt for receipt in receipts if infrastructure(receipt) or compiler_error(receipt)
                    or (receipt['status'] == 'failed' and not receipt['declaredAdvisory'])]
        untriaged = [receipt for receipt in receipts
                     if receipt['status'] == 'needs_review' and not receipt['declaredAdvisory']]
        state = ('failed' if error or blocking else
                 'needs_review' if any(receipt['status'] != 'passed' for receipt in receipts) else 'passed')
        directory = self.state_dir / 'checks' / candidate
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='suite-', suffix='.json',
                                         dir=directory, delete=False) as stream:
            record_path = Path(stream.name)
            json.dump({'revision': candidate, 'task': task['id'], 'experiment': experiment,
                       'at': now(), 'status': state, 'checks': receipts, 'error': error}, stream,
                      ensure_ascii=False, indent=2)
            stream.write('\n')
        self.ledger('checks', task=task['id'], experiment=experiment, revision=candidate, status=state,
                    record=str(record_path), checks=[{'label': row['label'], 'status': row['status'],
                                                     'record': row['record']} for row in receipts])
        manifest_path = self.project / '.kaizen/experiments' / experiment / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['team']['checksRecord'] = str(record_path)
        write_json(manifest_path, manifest)
        if state != 'failed' and not untriaged:
            return True
        # Close without deploying or consuming candidate benchmark slots. The
        # source-bound hold keeps failed QA alive for repair and a fresh retest.
        reason = ('統合SHAの既存QA失敗: ' if state == 'failed' else '統合SHAの警告はAIによる調査が必要: ') + (
            error or ', '.join(row['label'] for row in blocking or untriaged))
        self.target('evaluate')
        self.target('experiment', 'record', '--override', 'inconclusive', reason[:400])
        category = ('conditions' if error or any(infrastructure(row) for row in blocking) else
                    'correctness' if blocking else 'warning')
        self.team('task-quality-hold', '--id', task['id'], '--agent', self.agent, '--token', self.token,
                  '--category', category, '--evidence', str(record_path), '--reason', reason[:400])
        self.ledger('hold', task=task['id'], experiment=experiment, category=category, reason=reason[:400])
        self.ledger('finish', task=task['id'], experiment=experiment, result='NEEDS_MEASUREMENT', reason=reason[:400])
        self.feedback(task, experiment, None, reason[:400],
                      '品質保留: 生のQA記録を確認し、task-resume → 修正 → task-ready。未実行やadvisoryをPASSへ変更しない')
        self.processed += 1
        return False

    def acquire(self, tid):
        reservation = self.team('env-acquire', '--agent', self.agent, '--purpose', 'integrate ' + tid)
        self.token = reservation['token']
        token_file = self.state_dir / 'reservation.json'
        token_file.write_text(json.dumps({'token': self.token, 'task': tid, 'at': now()}) + '\n')
        token_file.chmod(0o600)

    def release(self, reason):
        if not self.token:
            return
        try:
            self.team('env-release', '--agent', self.agent, '--token', self.token, '--reason', reason)
            self.ledger('release', reason=reason)
            self.token = None
            (self.state_dir / 'reservation.json').unlink(missing_ok=True)
        except StepError as error:
            self.ledger('error', message='release refused: ' + str(error)[-500:])

    def fetch_sources(self, task):
        self.git('fetch', '--prune', self.settings['remote'])
        for name in ('base_sha', 'source_sha'):
            if subprocess.run(['git', '-C', str(self.project), 'cat-file', '-e', task[name] + '^{commit}'],
                              capture_output=True).returncode:
                raise StepError(name + ' ' + task[name][:7] + ' が ' + self.settings['remote'] + ' から取得できません。ブランチを push してください')

    def dry_compose(self, task):
        """Cherry-pick base..source onto the stable tip in a throwaway worktree.

        Returns status ok | conflict | empty | overlap with the changed files and the
        composed diff; nothing of this touches the project checkout.
        """
        stable_tip = self.git('rev-parse', self.config['stable_branch']).strip()
        base, source = task['base_sha'], task['source_sha']
        if subprocess.run(['git', '-C', str(self.project), 'merge-base', '--is-ancestor', base, source], capture_output=True).returncode:
            return {'status': 'conflict', 'files': [], 'message': 'base ' + base[:7] + ' が source ' + source[:7] + ' の祖先ではありません。同じブランチの base と source で再提出してください'}
        files = [line for line in self.git('diff', '--name-only', base, source).splitlines() if line]
        if not files:
            return {'status': 'empty', 'files': [], 'message': 'source ' + source[:7] + ' は base ' + base[:7] + ' から何も変更していません'}
        worktree = Path(tempfile.mkdtemp(prefix='kaizen-compose-', dir=str(self.state_dir)))
        try:
            self.git('worktree', 'add', '--detach', '-q', str(worktree), stable_tip)
            pick = subprocess.run(['git', '-C', str(worktree), *GIT_IDENTITY, 'cherry-pick', '--keep-redundant-commits', base + '..' + source],
                                  capture_output=True, text=True)
            if pick.returncode:
                subprocess.run(['git', '-C', str(worktree), 'cherry-pick', '--abort'], capture_output=True)
                conflicted = [line.split('\t', 1)[1] for line in subprocess.run(
                    ['git', '-C', str(worktree), 'diff', '--name-only', '--diff-filter=U'], capture_output=True, text=True).stdout.splitlines() if '\t' in line]
                lines = (pick.stdout + '\n' + pick.stderr).splitlines()
                detail = [line for line in lines if line.startswith(('CONFLICT', 'error:'))] or [line for line in lines if line.strip()] or ['']
                return {'status': 'conflict', 'files': files, 'message': self.config['stable_branch'] + ' ' + stable_tip[:7] + ' への cherry-pick が失敗（'
                        + detail[0][:200] + '）。現在の ' + self.config['stable_branch'] + ' に rebase して統合SHAを再提出してください'}
            composed = self.git('rev-parse', 'HEAD', cwd=worktree).strip()
            overlapping = [path for path in files if self.blob(composed, path, cwd=worktree) != self.blob(source, path)]
            if overlapping:
                return {'status': 'overlap', 'files': files, 'message': ', '.join(overlapping[:5]) + ' への変更が採用済みの変更と重なります。現在の '
                        + self.config['stable_branch'] + ' に rebase して統合SHAを再提出してください'}
            if not self.git('diff', '--name-only', stable_tip, composed, cwd=worktree).strip():
                return {'status': 'empty', 'files': files, 'message': '提出された変更はすでに ' + self.config['stable_branch'] + ' に含まれています'}
            diff = self.git('diff', stable_tip, composed, cwd=worktree)
            return {'status': 'ok', 'files': files, 'diff': diff, 'stable': stable_tip}
        finally:
            subprocess.run(['git', '-C', str(self.project), 'worktree', 'remove', '--force', str(worktree)], capture_output=True)
            subprocess.run(['git', '-C', str(self.project), 'worktree', 'prune'], capture_output=True)

    def review(self, task, composed):
        if self.settings['review'] != 'llm':
            return None
        llm = self.settings['llm']
        limit = int(llm['max_diff_bytes'])
        diff = composed['diff']
        if len(diff.encode()) > limit:
            diff = diff.encode()[:limit].decode(errors='ignore') + '\n[diff truncated at ' + str(limit) + ' bytes]\n'
        card = {key: task.get(key) for key in ('id', 'title', 'reason', 'evidence', 'hypothesis_key', 'work_kind', 'review', 'owner')}
        prompt = (REVIEW_PROMPT + '\nTask (from the shared ledger):\n' + json.dumps(card, ensure_ascii=False, indent=2)
                  + '\n\nFiles changed base..source:\n' + '\n'.join(composed['files'])
                  + '\n\nDiff of the composed candidate against stable ' + composed['stable'][:7] + ':\n' + diff)
        command = list(llm['command']) + ['--max-budget-usd', str(llm['max_budget_usd'])]
        if llm.get('model'):
            command += ['--model', llm['model']]
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='kaizen-review-') as directory:
            try:
                result = subprocess.run([*command, prompt], cwd=directory, stdin=subprocess.DEVNULL, capture_output=True,
                                        text=True, timeout=int(llm['timeout_seconds']))
            except (OSError, subprocess.TimeoutExpired) as error:
                self.ledger('review', task=task['id'], verdict='unavailable', reasons=[type(error).__name__], model=llm.get('model'))
                return None
        duration = round(time.monotonic() - started, 1)
        try:
            data = json.loads(result.stdout)
            if result.returncode or data.get('is_error'):
                raise ValueError(str(data.get('result', ''))[:300] or result.stderr.strip()[-300:])
            verdict = parse_json_object(str(data.get('result', '')))
            if not isinstance(verdict.get('proceed'), bool):
                raise ValueError('proceed must be true or false')
        except (ValueError, TypeError) as error:
            self.ledger('review', task=task['id'], verdict='unavailable', reasons=[str(error)[:300]], model=llm.get('model'),
                        durationSeconds=duration)
            return None
        usage = data.get('usage') or {}
        self.ledger('review', task=task['id'], verdict='proceed' if verdict['proceed'] else 'return',
                    reasons=verdict.get('reasons') or [], risks=verdict.get('risks') or [], model=llm.get('model'),
                    costUsd=data.get('total_cost_usd'), inputTokens=usage.get('input_tokens'),
                    outputTokens=usage.get('output_tokens'), cacheReadTokens=usage.get('cache_read_input_tokens'),
                    durationSeconds=duration)
        return verdict

    def return_task(self, task, reason):
        self.team('task-finish', '--id', task['id'], '--agent', self.agent, '--result', 'NEEDS_MEASUREMENT',
                  '--reason', 'integrator: ' + reason)
        self.ledger('finish', task=task['id'], result='NEEDS_MEASUREMENT', reason=reason)
        self.feedback(task, None, None, 'ベンチなしで返却: ' + reason,
                      'task-resume → 修正 → task-ready で再提出')
        self.processed += 1

    def baseline_samples(self):
        state = read_state(self.project)
        folder = self.project / '.kaizen/baseline' / state.get('STABLE_REV', '')
        fresh = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=self.config['baseline_max_age_minutes'])
        count = 0
        for path in folder.glob('*.json'):
            try:
                sample = json.loads(path.read_text())
                finished = datetime.datetime.fromisoformat(sample['finishedAt'].replace('Z', '+00:00'))
            except (ValueError, KeyError, OSError):
                continue
            if sample.get('pass') and not sample.get('observed') and finished >= fresh:
                count += 1
        return count

    def ensure_baseline(self, tid):
        while self.baseline_samples() < self.config['min_samples']:
            label = 'baseline-' + stamp()
            self.bench(tid, None, label)

    def open_experiment(self, task):
        title = re.sub(r'[^A-Za-z0-9_-]+', '-', task['title']).strip('-')[:24]
        slug = (task['id'] + ('-' + title if title else '')).replace('--', '-')
        self.target('experiment', 'new', slug, '--github-user', self.settings['github_user'])
        name = read_state(self.project).get('CURRENT_EXPERIMENT')
        if not name:
            raise StepError('experiment new が実験を開きませんでした')
        self.ledger('open', task=task['id'], experiment=name)
        return name

    def compose(self, task):
        pick = subprocess.run(['git', '-C', str(self.project), *GIT_IDENTITY, 'cherry-pick', '--keep-redundant-commits',
                               task['base_sha'] + '..' + task['source_sha']], capture_output=True, text=True)
        if pick.returncode:
            subprocess.run(['git', '-C', str(self.project), 'cherry-pick', '--abort'], capture_output=True)
            raise StepError('dry run では成功した合成が失敗: ' + (pick.stderr.strip() or pick.stdout.strip())[-400:])
        return self.git('rev-parse', 'HEAD').strip()

    def fill_manifest(self, experiment, task, composed, verdict, candidate):
        path = self.project / '.kaizen/experiments' / experiment / 'manifest.json'
        manifest = json.loads(path.read_text())
        verdict = verdict or {}
        changes = []
        for line in self.git('diff', '--name-status', composed['stable'], candidate).splitlines():
            kind, _, name = line.partition('\t')
            changes.append({'path': name, 'changeKind': {'A': 'add', 'D': 'delete'}.get(kind[:1], 'modify'),
                            'reason': task['id'] + ' の提出変更'})
        resources = [change['path'] for change in changes if any(
            change['path'] == root or change['path'].startswith(root.rstrip('/') + '/')
            for root in self.config['resource_paths'].split() + [self.config['overlay_dir']] if root)]
        manifest.update({
            'patternId': task.get('hypothesis_key') or '',
            'hypothesisId': task.get('hypothesis_key') or task['id'],
            'hypothesis': verdict.get('hypothesis') or task['title'],
            'observations': [{'summary': task.get('reason') or task['title'], 'artifact': task.get('evidence') or 'ledger:' + task['id']}],
            'allowedChanges': changes,
            'changeSummary': verdict.get('changeSummary') or ('提出ソース ' + task['source_sha'][:7] + ' を ' + composed['stable'][:7] + ' へ合成'),
            'expectedEffect': verdict.get('expectedEffect') or task.get('reason') or task['id'] + ' が主張するスコア改善',
            'review': task.get('review') or 'auto',
            'humanQuestion': task.get('human_question') or '',
            'changedResources': resources,
        })
        strategy = manifest.get('strategy') or {}
        strategy.update({'mechanism': task.get('hypothesis_key') or '', 'scoringPath': verdict.get('scoringPath') or '',
                         'scoringEvidence': task.get('evidence') or ''})
        manifest['strategy'] = strategy
        manifest['team'] = {'task': task['id'], 'owner': task.get('owner'), 'sourceRevision': task['source_sha'],
                            'baseRevision': task['base_sha'], 'integrator': self.agent,
                            'review': {'mode': self.settings['review'], 'risks': verdict.get('risks') or []}}
        write_json(path, manifest)

    def bench(self, tid, experiment, label):
        """One sample through target bench; returns the sample's pass flag."""
        started = time.monotonic()
        if self.config['bench_mode'] == 'manual':
            self.target('bench', label, '--reserve')
            self.status('waiting', 'ポータル: ' + label + ' の公式ベンチを開始し、終了を確認してから '
                        '"integrator result --label ' + label + ' --result \'pass=.. score=.. errors=..\'" で結果を渡してください',
                        task=tid, experiment=experiment, step='portal')
            inbox = self.state_dir / 'inbox' / (label + '.json')
            while not inbox.exists():
                time.sleep(5)
            data = json.loads(inbox.read_text())
            inbox.rename(self.state_dir / 'inbox' / (label + '.used-' + stamp()))
            if data.get('abandon'):
                self.target('bench', label, '--abandon', data['abandon'])
                self.ledger('bench', task=tid, experiment=experiment, label=label, abandoned=data['abandon'])
                raise SampleAbandoned('ポータル実行 ' + label + ' を放棄: ' + data['abandon'])
            args = ['--result', data['result']]
            if data.get('requests') is not None:
                args += ['--requests', str(data['requests'])]
            if data.get('seconds') is not None:
                args += ['--seconds', str(data['seconds'])]
            run = subprocess.run([sys.executable, str(TARGET), '--agent', self.agent, '--token', self.token, '--db', str(self.db),
                                  '--config', str(self.config_path), 'bench', label, *args], capture_output=True, text=True)
        else:
            self.status('working', 'ベンチ ' + label, task=tid, experiment=experiment, step='bench')
            run = subprocess.run([sys.executable, str(TARGET), '--agent', self.agent, '--token', self.token, '--db', str(self.db),
                                  '--config', str(self.config_path), 'bench', label], capture_output=True, text=True)
        state = read_state(self.project)
        duration = round(time.monotonic() - started, 1)
        if state.get('LAST_RUN') != label:
            message = (run.stderr.strip() + '\n' + run.stdout.strip()).strip()[-800:]
            if 'budget' in message.lower():
                raise BudgetExhausted('bench ' + label + ': ' + message)
            raise StepError('ベンチ ' + label + ' のサンプルが記録されませんでした: ' + message)
        passed = state.get('LAST_PASS') == 'true'
        self.ledger('baseline' if label.startswith('baseline') else 'bench', task=tid, experiment=experiment, label=label,
                    score=int(state.get('LAST_SCORE') or 0), **{'pass': passed}, durationSeconds=duration)
        return passed

    def evaluate(self, experiment):
        self.target('evaluate')
        return json.loads((self.project / '.kaizen/experiments' / experiment / 'decision.json').read_text())

    def measure(self, tid, experiment):
        count = 0
        decision = None
        while count < self.config['max_bench_per_exp']:
            count += 1
            label = 'candidate' if count == 1 else 'candidate-' + str(count)
            try:
                passed = self.bench(tid, experiment, label)
            except (BudgetExhausted, SampleAbandoned) as error:
                self.ledger('budget', task=tid, experiment=experiment, message=str(error)[-300:])
                break
            decision = self.evaluate(experiment)
            self.ledger('evaluate', task=tid, experiment=experiment, decision=decision['decision'],
                        nextAction=decision.get('nextAction'), reason=decision.get('reason'))
            if not passed or decision.get('nextAction') != 'remeasure':
                break
        if decision is None:
            decision = self.evaluate(experiment)
        return decision

    def record(self, experiment, decision):
        reason = (decision.get('reason') or decision['decision'])[:300]
        try:
            self.target('experiment', 'record', reason)
        except StepError as error:
            if 'quality hold' not in str(error):
                raise
            self.target('experiment', 'record', '--override', 'inconclusive', reason + ' (' + str(error)[-200:] + ')')
        record = json.loads((self.project / '.kaizen/experiments' / experiment / 'record.json').read_text())
        self.ledger('record', experiment=experiment, final=record['finalDecision'], reason=record.get('reason'),
                    stableAfter=record.get('stableAfter'), rule=record['ruleDecision'].get('decision'))
        return record

    def finish(self, task, experiment, record, candidate):
        tid = task['id']
        decision = record['ruleDecision']
        final = record['finalDecision']
        quality = (decision.get('quality') or {}).get('status', 'pass')
        reason = (final + '（' + decision.get('ruleVersion', 'rule') + '）: ' + (record.get('reason') or ''))[:400]
        record_path = self.project / '.kaizen/experiments' / experiment / 'record.json'
        if final == 'promote':
            self.team('task-finish', '--id', tid, '--agent', self.agent, '--result', 'ACCEPTED', '--reason', reason,
                      '--record', str(record_path), '--tested-sha', candidate)
            result, advice = 'ACCEPTED', '採用。進行中の作業は新しい ' + self.config['stable_branch'] + ' に rebase'
            if self.settings['push']:
                # The adoption is recorded; a push failure is an operations problem, not a measurement.
                try:
                    self.git('push', self.settings['remote'], self.config['stable_branch'])
                    self.ledger('push', experiment=experiment, sha=candidate)
                except StepError as error:
                    self.ledger('error', task=tid, experiment=experiment, message='push: ' + str(error)[-400:])
                    advice += '。push 失敗: ' + self.settings['remote'] + ' を手動で同期'
                    if self.settings['pause_on_error']:
                        self.pause('採用した ' + self.config['stable_branch'] + ' の push が失敗: ' + str(error)[-200:])
        elif final == 'reject':
            self.team('task-finish', '--id', tid, '--agent', self.agent, '--result', 'REJECTED', '--reason', reason)
            result, advice = 'REJECTED', 'stable を復旧済み。再試行には新しい根拠か別の機構が必要'
        elif quality != 'pass':
            category = hold_category(decision)
            self.team('task-quality-hold', '--id', tid, '--agent', self.agent, '--token', self.token, '--category', category,
                      '--evidence', str(record_path.with_name('decision.json')), '--reason', reason)
            self.ledger('hold', task=tid, experiment=experiment, category=category, reason=reason)
            result, advice = 'NEEDS_MEASUREMENT', '品質保留（' + category + '）: task-resume → 再現付きで修正 → task-ready'
        else:
            self.team('task-finish', '--id', tid, '--agent', self.agent, '--result', 'NEEDS_MEASUREMENT', '--reason', reason)
            result, advice = 'NEEDS_MEASUREMENT', '予算内でノイズと分離できず。task-resume し、より強い機構か新しい根拠で再提出'
        self.ledger('finish', task=tid, experiment=experiment, result=result, reason=reason)
        self.feedback(task, experiment, record, result + ': ' + reason, advice)

    def feedback(self, task, experiment, record, summary, advice):
        lines = ['# ' + task['id'] + ': ' + task['title'], '', '- 担当: ' + str(task.get('owner')),
                 '- source: ' + task['source_sha'] + '（base ' + task['base_sha'][:7] + '）', '- 結果: ' + summary, '- 次: ' + advice]
        if record:
            decision = record['ruleDecision']
            lines += ['- 実験: ' + str(experiment) + ' candidate ' + str(record.get('candidateRevision'))[:7],
                      '- スコア: baseline ' + str(decision.get('baselineScores')) + ' → candidate ' + str(decision.get('candidateScores')),
                      '- 品質: ' + json.dumps(decision.get('quality'), ensure_ascii=False),
                      '- stable: ' + str(record.get('stableBefore'))[:7] + ' -> ' + str(record.get('stableAfter'))[:7]]
        lines += ['', 'Discord: `' + task['id'] + ' ' + summary[:160] + '`', '']
        (self.state_dir / 'feedback' / (task['id'] + '.md')).write_text('\n'.join(lines))

    def handle_error(self, task, experiment, error):
        tid = task['id']
        message = str(error)[-1200:]
        self.ledger('error', task=tid, experiment=experiment, message=message)
        cleanup = []
        try:
            state = read_state(self.project)
            if state.get('CURRENT_EXPERIMENT'):
                if state.get('REVERT_PENDING') == '1' or state.get('DEPLOYED_REV') != state.get('STABLE_REV'):
                    self.target('recover')
                    cleanup.append('stable を復旧')
                folder = self.project / '.kaizen/experiments' / state['CURRENT_EXPERIMENT']
                if list(folder.glob('bench-candidate*.json')):
                    self.target('evaluate')
                    self.target('experiment', 'record', '--override', 'inconclusive', '統合Agentのエラー: ' + message[:200])
                    cleanup.append('実験を inconclusive で記録')
                else:
                    cleanup.append('実験 ' + state['CURRENT_EXPERIMENT'] + ' をサンプルなしで開いたままです。手動で閉じてください')
            if self.token:
                self.team('task-finish', '--id', tid, '--agent', self.agent, '--result', 'NEEDS_MEASUREMENT',
                          '--reason', 'integrator: エラー ' + message[:300])
                cleanup.append('タスクを NEEDS_MEASUREMENT で返却')
        except Exception as second:  # noqa: BLE001 - report both, never hide the first
            cleanup.append('後始末に失敗: ' + str(second)[-300:])
        self.ledger('error', task=tid, experiment=experiment, message='cleanup: ' + '; '.join(cleanup))
        self.status('error', message[:300] + ' | ' + '; '.join(cleanup), task=tid, experiment=experiment, lastError=message[:300])
        self.feedback(task, experiment, None, '統合Agentのエラー: ' + message[:300], '; '.join(cleanup))
        if self.settings['pause_on_error']:
            self.pause(tid + ' の統合中にエラー: ' + message[:200])

    # -- loop -------------------------------------------------------------------------

    def run(self):
        def stop(signum, frame):
            self.stopping = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        self.ledger('start', agent=self.agent, review=self.settings['review'])
        while not self.stopping:
            try:
                self.run_once()
            except Exception as error:  # noqa: BLE001 - the loop itself must survive
                self.ledger('error', message='loop: ' + str(error)[-800:])
                self.status('error', str(error)[-300:], lastError=str(error)[-300:])
                if self.settings['pause_on_error']:
                    self.pause('ループのエラー: ' + str(error)[-200:])
            self.dashboard()
            waited = 0
            while waited < int(self.settings['poll_seconds']) and not self.stopping:
                time.sleep(1)
                waited += 1
        self.ledger('stop', agent=self.agent)
        self.status('idle', '停止')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--db', default='/srv/isucon/state/team.sqlite3')
    p.add_argument('--config', default='/srv/isucon/state/target.json')
    p.add_argument('--state', help='state directory (default: <db dir>/integrator)')
    p.add_argument('--settings', help='integrator.json (default: <state>/integrator.json)')
    commands = p.add_subparsers(dest='command', required=True)
    for name in ('run', 'once', 'status', 'resume', 'dashboard'):
        commands.add_parser(name)
    pause = commands.add_parser('pause')
    pause.add_argument('--reason', default='paused by an operator')
    result = commands.add_parser('result')
    result.add_argument('--label', required=True)
    result.add_argument('--result', required=True, help="'pass=<true|false> score=<n> errors=<text>' from the portal")
    result.add_argument('--requests', type=int)
    result.add_argument('--seconds', type=int)
    abandon = commands.add_parser('abandon')
    abandon.add_argument('--label', required=True)
    abandon.add_argument('--reason', required=True)
    args = p.parse_args()
    try:
        integrator = Integrator(args)
        if args.command == 'run':
            integrator.run()
        elif args.command == 'once':
            processed = integrator.run_once()
            integrator.dashboard()
            print(json.dumps({'processed': processed, 'status': json.loads((integrator.state_dir / 'status.json').read_text())},
                             ensure_ascii=False, indent=2))
        elif args.command == 'status':
            path = integrator.state_dir / 'status.json'
            data = json.loads(path.read_text()) if path.is_file() else None
            pause_file = integrator.state_dir / 'pause'
            print(json.dumps({'status': data, 'paused': pause_file.read_text().strip() if pause_file.exists() else None,
                              'stateDir': str(integrator.state_dir)}, ensure_ascii=False, indent=2))
        elif args.command == 'pause':
            integrator.pause(args.reason)
            print('一時停止: ' + args.reason)
        elif args.command == 'resume':
            (integrator.state_dir / 'pause').unlink(missing_ok=True)
            integrator.ledger('resume')
            print('再開')
        elif args.command in ('result', 'abandon'):
            if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label):
                raise ValueError('label must be [A-Za-z0-9_-]')
            data = ({'abandon': args.reason} if args.command == 'abandon'
                    else {'result': args.result, 'requests': args.requests, 'seconds': args.seconds})
            data['at'] = now()
            write_json(integrator.state_dir / 'inbox' / (args.label + '.json'), data)
            print('待機中の統合Agentへ渡しました: ' + args.label)
        elif args.command == 'dashboard':
            integrator.load_target()
            integrator.dashboard()
            print('ダッシュボードを出力: ' + (integrator.settings['dashboard_dir'] or str(integrator.state_dir / 'dashboard')))
        return 0
    except (StepError, ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
