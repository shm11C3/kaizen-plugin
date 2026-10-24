#!/usr/bin/env python3
"""Static human dashboard: ledger queue, integrator state, experiments, budget.

Read-only observer. The ledger is opened with mode=ro and never through
team.connect() (that would migrate the schema). The only files written are
OUT_DIR/index.html and OUT_DIR/summary.json, each via a temp file + os.replace.
A missing or malformed source becomes an "unavailable: <reason>" note.
"""
import argparse
import datetime
import glob
import html
import json
import math
import os
import sqlite3
import statistics
import sys

UTC = datetime.timezone.utc
JST = datetime.timezone(datetime.timedelta(hours=9))
EPOCH = datetime.datetime(1970, 1, 1, tzinfo=UTC)
STATUS_ORDER = ('READY', 'CLAIMED', 'NEEDS_MEASUREMENT', 'NEEDS_HUMAN', 'TODO',
                'BLOCKED', 'ACCEPTED', 'REJECTED', 'DONE')
STATE_LABELS = {'idle': '待機', 'waiting': '待機中', 'working': '作業中', 'paused': '一時停止', 'error': 'エラー'}
UNAVAILABLE = '取得不可'
CSS = (':root{--bg:#ffffff;--fg:#222222;--muted:#666666;--card:#fafafa;--border:#bbbbbb;--rule:#dddddd;--th:#efefef;'
       '--q:#fff3cd;--bad:#c0392b;--ok:#1e8449;--accent:#2e6fd8;--idle:#7f8c8d;--waiting:#b7790a;--working:#2e6fd8;'
       '--paused:#8e44ad;--error:#c0392b}'
       '@media (prefers-color-scheme: dark){:root{--bg:#15171a;--fg:#e8e8e8;--muted:#a8a8a8;--card:#20242a;--border:#5a5f66;'
       '--rule:#3a3f46;--th:#2a2f36;--q:#5a4a10;--bad:#ff7b6e;--ok:#5fd68f;--accent:#7fb0ff;--idle:#a0a8ad;--waiting:#f1b640;'
       '--working:#7fb0ff;--paused:#c58cf0;--error:#ff7b6e}}'
       'body{font-family:-apple-system,"Hiragino Sans","Noto Sans JP",Helvetica,Arial,sans-serif;margin:0;padding:12px;'
       'background:var(--bg);color:var(--fg);font-size:14px}'
       'h1,h2,h3{color:var(--fg)}h1{font-size:20px;margin:0 0 4px}'
       'h2{font-size:16px;margin:20px 0 6px;border-bottom:1px solid var(--rule)}h3{font-size:13px;margin:12px 0 4px}'
       '.muted{color:var(--muted)}.cards{display:flex;flex-wrap:wrap;gap:8px}'
       '.card{background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 10px;'
       'min-width:120px;flex:1 1 140px}.state{border-width:3px;border-color:var(--st)}.state b{color:var(--st)}'
       '.st-idle{--st:var(--idle)}.st-waiting{--st:var(--waiting)}.st-working{--st:var(--working)}'
       '.st-paused{--st:var(--paused)}.st-error{--st:var(--error)}'
       '.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;color:var(--fg)}'
       'th,td{border-bottom:1px solid var(--rule);padding:3px 6px;text-align:left;vertical-align:top;word-break:break-word}'
       'th{background:var(--th)}.q{background:var(--q);color:var(--fg);padding:2px 4px;display:block;margin-top:2px}'
       'svg{width:100%;height:auto;max-width:800px;background:var(--card)}.axis{stroke:var(--muted)}.lbl{fill:var(--fg)}'
       '.step{stroke:var(--accent)}.base{fill:var(--card);stroke:var(--accent)}.cand{fill:var(--ok)}.fail{stroke:var(--bad)}'
       'pre{white-space:pre-wrap;font-size:12px}.bad{color:var(--bad)}.ok{color:var(--ok)}'
       'footer{margin-top:24px;font-size:12px;color:var(--muted)}')


def esc(value):
    return html.escape('' if value is None else str(value), quote=True)


def unavailable(notes, source, reason):
    notes.append('{}: {}: {}'.format(UNAVAILABLE, source, reason))


def parse_time(value):
    """ISO8601 ('Z' accepted, naive = UTC) -> aware UTC datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def fmt_time(value, now):
    at = value if isinstance(value, datetime.datetime) else parse_time(value)
    if at is None:
        return '-'
    local = at.astimezone(JST)
    pattern = '%H:%M:%S' if local.date() == now.astimezone(JST).date() else '%m-%d %H:%M:%S'
    return local.strftime(pattern)


def fmt_dur(seconds):
    if seconds is None or seconds < 0:
        return ''
    s = int(seconds)
    if s < 60:
        return '{}秒'.format(s)
    if s < 3600:
        return '{}分{:02d}秒'.format(s // 60, s % 60)
    if s < 86400:
        return '{}時間{:02d}分'.format(s // 3600, (s % 3600) // 60)
    return '{}日{}時間'.format(s // 86400, (s % 86400) // 3600)


def age(value, now):
    at = parse_time(value)
    if at is None:
        return '-'
    return fmt_dur((now - at).total_seconds()) or '0秒'


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def median(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return statistics.median(values) if values else None


def short(sha):
    return sha[:7] if isinstance(sha, str) else ''


def clip(text, limit):
    text = '' if text is None else str(text)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def strip_tokens(value):
    """Reservation tokens appear inside event details; never render them."""
    if isinstance(value, dict):
        return {k: strip_tokens(v) for k, v in value.items() if k != 'token'}
    if isinstance(value, list):
        return [strip_tokens(v) for v in value]
    return value


def load_json(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def load_jsonl(path):
    rows = []
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def compact(event):
    """Key fields of a ledger event, 'k=v' joined, without the fixed columns."""
    parts = []
    for key, value in event.items():
        if key in ('at', 'event', 'task', 'experiment'):
            continue
        if isinstance(value, list):
            value = ','.join(str(v) for v in value)
        elif isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        elif isinstance(value, float):
            value = round(value, 4)
        parts.append('{}={}'.format(key, value))
    return clip(' '.join(parts), 120)


def read_db(path, notes):
    data = {'tasks': [], 'reservation': None, 'holds': [], 'events': []}
    if not os.path.isfile(path):
        unavailable(notes, '台帳DB', path + ' が存在しません')
        return data
    try:
        db = sqlite3.connect('file:' + path + '?mode=ro', uri=True, timeout=5)
    except sqlite3.Error as error:
        unavailable(notes, '台帳DB', error)
        return data
    db.row_factory = sqlite3.Row
    queries = {
        'tasks': 'SELECT * FROM tasks ORDER BY priority DESC, id',
        'reservation': 'SELECT owner, purpose, acquired_at FROM reservation',
        'holds': "SELECT id, task_id, category, state, reason, opened_at FROM quality_holds "
                 "WHERE state IN ('OPEN','RETEST_PENDING') ORDER BY id",
        'events': 'SELECT at, actor, action, details FROM events ORDER BY id DESC LIMIT 30',
    }
    try:
        for key, sql in queries.items():
            try:
                rows = [dict(r) for r in db.execute(sql)]
            except sqlite3.Error as error:
                unavailable(notes, '台帳テーブル ' + key, error)
                continue
            data[key] = (rows[0] if rows else None) if key == 'reservation' else rows
    finally:
        db.close()
    for task in data['tasks']:
        task['id'] = 'T-{:04d}'.format(number(task.get('id')))
    for event in data['events']:
        try:
            details = strip_tokens(json.loads(event.get('details') or 'null'))
            event['excerpt'] = clip(json.dumps(details, ensure_ascii=False, separators=(',', ':')), 120)
        except ValueError:
            event['excerpt'] = clip(event.get('details'), 120)
    return data


def read_state(path, notes):
    data = {'status': None, 'events': [], 'paused': False, 'feedback': [],
            'llm': {'calls': 0, 'inputTokens': 0, 'outputTokens': 0, 'costUsd': 0.0, 'lastCall': None}}
    if not os.path.isdir(path):
        unavailable(notes, '状態ディレクトリ', path + ' がディレクトリではありません')
        return data
    status = os.path.join(path, 'status.json')
    try:
        data['status'] = load_json(status)
        if not isinstance(data['status'], dict):
            raise ValueError('JSONオブジェクトではありません')
    except (OSError, ValueError) as error:
        data['status'] = None
        unavailable(notes, 'status.json', error)
    try:
        data['events'] = load_jsonl(os.path.join(path, 'ledger.jsonl'))
    except OSError as error:
        unavailable(notes, 'ledger.jsonl', error)
    data['paused'] = os.path.exists(os.path.join(path, 'pause'))
    try:
        files = glob.glob(os.path.join(path, 'feedback', '*.md'))
        for name in sorted(files, key=os.path.getmtime, reverse=True)[:10]:
            with open(name, encoding='utf-8') as handle:
                data['feedback'].append({'name': os.path.basename(name), 'line': handle.readline().strip(),
                                         'at': datetime.datetime.fromtimestamp(os.path.getmtime(name), UTC)})
    except OSError as error:
        unavailable(notes, 'feedback', error)
    llm = data['llm']
    for event in data['events']:
        if event.get('event') in ('review', 'llm'):
            llm['calls'] += 1
            llm['inputTokens'] += int(number(event.get('inputTokens')))
            llm['outputTokens'] += int(number(event.get('outputTokens')))
            llm['costUsd'] += float(number(event.get('costUsd')))
            if (parse_time(event.get('at')) or EPOCH) >= (parse_time(llm['lastCall']) or EPOCH):
                llm['lastCall'] = event.get('at')
    llm['costUsd'] = round(llm['costUsd'], 6)
    return data


def timeline_seconds(timeline):
    times = [parse_time(line.split('\t', 1)[0]) for line in (timeline if isinstance(timeline, list) else [])
             if isinstance(line, str) and '\t' in line]
    times = [t for t in times if t is not None]
    return (times[-1] - times[0]).total_seconds() if len(times) >= 2 else None


def read_project(path, now, notes):
    data = {'state': {}, 'closed': [], 'open': [], 'baseline': [], 'points': [],
            'attempts': {'lastHour': 0, 'total': 0}, 'plan': []}
    kaizen = os.path.join(path, '.kaizen')
    if not os.path.isdir(kaizen):
        unavailable(notes, 'プロジェクト', kaizen + ' がディレクトリではありません')
        return data
    try:
        with open(os.path.join(kaizen, 'state.env'), encoding='utf-8') as handle:
            for line in handle:
                if '=' in line and not line.startswith('#'):
                    key, _, value = line.rstrip('\n').partition('=')
                    data['state'][key.strip()] = value.strip()
    except OSError as error:
        unavailable(notes, 'state.env', error)
    points = {}

    def add_point(sample, from_baseline_dir=False):
        if not isinstance(sample, dict) or sample.get('observed'):
            return
        at, score = parse_time(sample.get('finishedAt')), sample.get('score')
        if at is None or isinstance(score, bool) or not isinstance(score, (int, float)):
            return
        stable = from_baseline_dir or str(sample.get('label') or '').startswith('baseline')
        key = (sample.get('deployedRevision'), at, score)
        if key in points:
            points[key]['stable'] = points[key]['stable'] or stable
            return
        points[key] = {'t': at, 'score': score, 'pass': sample.get('pass'), 'stable': stable,
                       'rev': sample.get('deployedRevision') or '', 'kind': 'baseline' if stable else 'candidate'}

    for directory in sorted(glob.glob(os.path.join(kaizen, 'experiments', '*', ''))):
        exp = os.path.basename(os.path.dirname(directory))
        record = os.path.join(directory, 'record.json')
        if os.path.isfile(record):
            try:
                rec = load_json(record)
                if not isinstance(rec, dict):
                    raise ValueError('JSONオブジェクトではありません')
            except (OSError, ValueError) as error:
                unavailable(notes, exp + '/record.json', error)
                continue
            rule = rec.get('ruleDecision') if isinstance(rec.get('ruleDecision'), dict) else {}
            manifest = rec.get('manifest') if isinstance(rec.get('manifest'), dict) else {}
            for sample in rec.get('samples') if isinstance(rec.get('samples'), list) else []:
                add_point(sample)
            scores = {k: rule.get(k) if isinstance(rule.get(k), list) else [] for k in ('baselineScores', 'candidateScores')}
            data['closed'].append({
                'experiment': rec.get('experimentId') or exp, 'candidate': rec.get('candidateRevision'),
                'rule': rule.get('decision'), 'final': rec.get('finalDecision'), 'reason': rec.get('reason'),
                'baselineScores': scores['baselineScores'], 'candidateScores': scores['candidateScores'],
                'closedAt': rec.get('closedAt'), 'hypothesis': manifest.get('hypothesis'),
                'duration': timeline_seconds(rec.get('timeline'))})
            continue
        item = {'experiment': exp, 'hypothesis': None, 'decision': None, 'benches': 0}
        try:
            item['hypothesis'] = load_json(os.path.join(directory, 'manifest.json')).get('hypothesis')
        except (OSError, ValueError, AttributeError):
            pass
        if os.path.isfile(os.path.join(directory, 'decision.json')):
            try:
                item['decision'] = load_json(os.path.join(directory, 'decision.json'))
            except (OSError, ValueError) as error:
                unavailable(notes, exp + '/decision.json', error)
        for name in sorted(glob.glob(os.path.join(directory, 'bench-*.json'))):
            item['benches'] += 1
            try:
                add_point(load_json(name))
            except (OSError, ValueError) as error:
                unavailable(notes, exp + '/' + os.path.basename(name), error)
        data['open'].append(item)
    data['closed'].sort(key=lambda c: (parse_time(c['closedAt']) or EPOCH, c['experiment']), reverse=True)
    # Every revision directory, including earlier and retired ones (<rev>.retired-*): those samples
    # are still evidence of that revision's score at the time. The current median uses only <STABLE_REV>/.
    stable = data['state'].get('STABLE_REV', '')
    for name in sorted(glob.glob(os.path.join(kaizen, 'baseline', '*', '*.json'))):
        try:
            sample = load_json(name)
        except (OSError, ValueError) as error:
            unavailable(notes, os.path.relpath(name, kaizen), error)
            continue
        if isinstance(sample, dict) and not sample.get('observed'):
            if stable and os.path.basename(os.path.dirname(name)) == stable:
                data['baseline'].append(sample)
            add_point(sample, True)
    data['points'] = sorted(points.values(), key=lambda p: p['t'])
    attempts = os.path.join(kaizen, 'bench-attempts.jsonl')
    if os.path.isfile(attempts):
        try:
            rows = load_jsonl(attempts)
            data['attempts'] = {'total': len(rows), 'lastHour': sum(
                1 for r in rows if (now - (parse_time(r.get('startedAt')) or EPOCH)).total_seconds() < 3600)}
        except OSError as error:
            unavailable(notes, 'bench-attempts.jsonl', error)
    try:
        with open(os.path.join(kaizen, 'plan.md'), encoding='utf-8') as handle:
            for line in handle:
                if len(data['plan']) >= 40:
                    break
                data['plan'].append(line.rstrip('\n'))
    except OSError:
        pass
    return data


def nice_floor(value):
    """Floor to two significant digits: 2042 -> 2000, 13500 -> 13000, 900 -> 900."""
    if value <= 0:
        return 0
    unit = 10 ** (math.floor(math.log10(value)) - 1)
    return math.floor(value / unit) * unit


def render_svg(points, now):
    width, height, left, right, top, bottom = 800, 260, 60, 15, 15, 35
    if len(points) < 2:
        return '<p class="muted">スコア時系列: ベンチ標本が2件未満のため描画なし</p>'
    t0, t1 = points[0]['t'], points[-1]['t']
    positive = [p['score'] for p in points if p['score'] > 0]
    s0 = nice_floor(0.9 * min(positive)) if positive else 0
    s1 = max(p['score'] for p in points)
    span_t, span_s = max((t1 - t0).total_seconds(), 1.0), max(s1 - s0, 1.0)

    def x(t):
        return left + (t - t0).total_seconds() / span_t * (width - left - right)

    def y(s):  # scores under the axis start (failed samples) sit on the axis line
        return top + (s1 - max(s, s0)) / span_s * (height - top - bottom)

    def label(value):
        return esc(int(value) if float(value).is_integer() else value)

    out = ['<svg viewBox="0 0 {} {}" xmlns="http://www.w3.org/2000/svg" font-size="11">'.format(width, height),
           '<line class="axis" x1="{0}" y1="{1}" x2="{0}" y2="{2}"/>'.format(left, top, height - bottom),
           '<line class="axis" x1="{0}" y1="{1}" x2="{2}" y2="{1}"/>'.format(left, height - bottom, width - right),
           '<text class="lbl" x="{}" y="{}" text-anchor="end">{}</text>'.format(left - 4, top + 4, label(s1)),
           '<text class="lbl" x="{}" y="{}" text-anchor="end">{}</text>'.format(left - 4, height - bottom, label(s0)),
           '<text class="lbl" x="{}" y="{}">{}</text>'.format(left, height - bottom + 14, fmt_time(t0, now)),
           '<text class="lbl" x="{}" y="{}" text-anchor="end">{}</text>'.format(width - right, height - bottom + 14, fmt_time(t1, now)),
           '<text class="lbl" x="{}" y="{}">○ baseline標本  ● 候補標本  ✕ 失敗  ─ stable中央値</text>'.format(
               left, height - bottom + 28)]
    revisions = {}
    for p in points:
        if p['stable']:
            revisions.setdefault(p['rev'], []).append(p)
    groups = sorted(revisions.values(), key=lambda ps: ps[0]['t'])
    path = []
    for i, group in enumerate(groups):
        m = statistics.median([p['score'] for p in group])
        end = groups[i + 1][0]['t'] if i + 1 < len(groups) else t1
        path.append('{}{:.1f},{:.1f} L{:.1f},{:.1f}'.format('M' if not path else 'L', x(group[0]['t']), y(m), x(end), y(m)))
    if path:
        out.append('<path class="step" d="{}" fill="none" stroke-width="1.5" stroke-dasharray="4 3"/>'.format(' '.join(path)))
    for p in points:
        px, py = x(p['t']), y(p['score'])
        title = '<title>{} {} {}</title>'.format('baseline' if p['kind'] == 'baseline' else '候補', esc(p['score']), esc(short(p['rev'])))
        if p['pass'] is False:
            out.append('<g class="fail" stroke-width="2"><line x1="{0:.1f}" y1="{1:.1f}" x2="{2:.1f}" y2="{3:.1f}"/>'
                       '<line x1="{0:.1f}" y1="{3:.1f}" x2="{2:.1f}" y2="{1:.1f}"/>{4}</g>'.format(px - 4, py - 4, px + 4, py + 4, title))
        elif p['kind'] == 'baseline':
            out.append('<circle class="base" cx="{:.1f}" cy="{:.1f}" r="4" stroke-width="1.5">{}</circle>'.format(px, py, title))
        else:
            out.append('<circle class="cand" cx="{:.1f}" cy="{:.1f}" r="4">{}</circle>'.format(px, py, title))
    out.append('</svg>')
    return ''.join(out)


def table(headers, rows):
    out = ['<div class="wrap"><table><tr>' + ''.join('<th>{}</th>'.format(esc(h)) for h in headers) + '</tr>']
    out.extend('<tr>' + ''.join('<td>{}</td>'.format(cell) for cell in row) + '</tr>' for row in rows)
    return ''.join(out) + '</table></div>'


def render_html(now, summary, db, state, project, picks, notes, paths):
    env, status = project['state'], state['status'] or {}
    code = status.get('state')
    state_word = code if code in STATE_LABELS else 'idle'
    if not state['status']:
        state_label = UNAVAILABLE
    elif code in STATE_LABELS:
        state_label = '{} ({})'.format(STATE_LABELS[code], code)
    else:
        state_label = '不明 ({})'.format(code)
    out = ['<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta http-equiv="refresh" content="30">',
           '<meta name="viewport" content="width=device-width, initial-scale=1"><title>kaizen ダッシュボード</title>',
           '<style>{}</style></head><body><h1>kaizen ダッシュボード</h1>'.format(CSS),
           '<p class="muted">生成時刻 {} (Asia/Tokyo) · 30秒ごとに自動更新</p><div class="cards">'.format(fmt_time(now, now)),
           '<div class="card"><b>stable</b><br>{}</div>'.format(esc(short(env.get('STABLE_REV')) or '-')),
           '<div class="card"><b>配備</b><br>{} 正常={}</div>'.format(
               esc(short(env.get('DEPLOYED_REV')) or '-'), esc(env.get('DEPLOYED_HEALTHY', '-'))),
           '<div class="card"><b>復旧待ち</b><br><span class="{}">{}</span></div>'.format(
               'bad' if env.get('REVERT_PENDING') == '1' else 'ok', esc(env.get('REVERT_PENDING', '-'))),
           '<div class="card"><b>現在の実験</b><br>{}</div>'.format(esc(env.get('CURRENT_EXPERIMENT') or 'なし')),
           '<div class="card state st-{}"><b>統合Agent: {}</b><br>{}<br>'
           '<span class="muted">手順 {} · タスク {} · 実験 {} · 開始 {}</span>{}</div>'.format(
               state_word, esc(state_label),
               esc(status.get('detail') or '-'), esc(status.get('step') or '-'), esc(status.get('task') or '-'),
               esc(status.get('experiment') or '-'), fmt_time(status.get('since'), now),
               '<br><span class="bad">直近のエラー: {}</span>'.format(esc(clip(status.get('lastError'), 120)))
               if status.get('lastError') else '')]
    res = db['reservation']
    out.append('<div class="card"><b>占有</b><br>{}</div>'.format(
        '{} — {} (開始 {})'.format(esc(res['owner']), esc(res['purpose']), fmt_time(res.get('acquired_at'), now)) if res else '空き'))
    out.append('<div class="card"><b>一時停止</b><br><span class="{}">{}</span></div></div>'.format(
        'bad' if state['paused'] else 'ok', 'あり (pauseファイルが存在)' if state['paused'] else 'なし'))
    out.append('<h2>スコア時系列</h2>' + render_svg(project['points'], now))
    out.append('<h2>キュー</h2>')
    grouped = {}
    for task in db['tasks']:
        grouped.setdefault(task.get('status') or '?', []).append(task)
    if not grouped:
        out.append('<p class="muted">タスクなし</p>')
    for status_name in list(STATUS_ORDER) + sorted(set(grouped) - set(STATUS_ORDER)):
        tasks = grouped.get(status_name, [])
        if not tasks and not (status_name == 'NEEDS_MEASUREMENT' and db['holds']):
            continue
        out.append('<h3>{} ({}件)</h3>'.format(esc(status_name), len(tasks)))
        rows = []
        for t in tasks:
            title = esc(t.get('title'))
            if status_name == 'NEEDS_HUMAN':
                title += '<span class="q">質問: {}</span>'.format(esc(t.get('human_question') or '(質問が未記録)'))
            rows.append([esc(t['id']), title, esc(t.get('owner') or ''), esc(t.get('priority')), esc(t.get('review') or ''),
                         esc(age(t.get('updated_at'), now)), esc(clip(t.get('reason'), 80))])
        if rows:
            out.append(table(['ID', 'タイトル', '担当', '優先度', 'レビュー', '経過', '理由'], rows))
        if status_name == 'NEEDS_MEASUREMENT' and db['holds']:
            out.append('<ul>' + ''.join('<li>品質保留 H-{} {} T-{:04d} [{}] {}</li>'.format(
                esc(h['id']), esc(h.get('category')), number(h.get('task_id')), esc(h.get('state')),
                esc(clip(h.get('reason'), 100))) for h in db['holds']) + '</ul>')
    out.append('<h2>統合履歴</h2><p>採用 {} / 却下 {} / 判定保留 {} · 現在のstable中央値 {} vs 最初のbaseline中央値 {}{}</p>'.format(
        summary['promoted'], summary['rejected'], summary['inconclusive'],
        esc('-' if summary['baselineMedian'] is None else summary['baselineMedian']),
        esc('-' if summary['firstBaselineMedian'] is None else summary['firstBaselineMedian']),
        ' · 上昇率 {:+.1f}%'.format(summary['gainPercent']) if summary['gainPercent'] is not None else ''))
    for item in project['open']:
        decision = item['decision'] if isinstance(item['decision'], dict) else {}
        quality = decision.get('quality') if isinstance(decision.get('quality'), dict) else {}
        out.append('<p><b>進行中 {}</b>: {} · ベンチ標本 {}件{}</p>'.format(
            esc(item['experiment']), esc(clip(item['hypothesis'] or '(仮説が未記入)', 160)), item['benches'],
            ' · ルール判定 {} → {} (品質 {}): {}'.format(esc(decision.get('decision')), esc(decision.get('nextAction')),
                                                       esc(quality.get('status')), esc(clip(decision.get('reason'), 120)))
            if decision else ''))
    rows = []
    for c in project['closed']:
        bm, cm = median(c['baselineScores']), median(c['candidateScores'])
        delta = '{:+.1f}%'.format((cm - bm) / bm * 100) if bm and cm is not None else ''
        rows.append([esc(c['experiment']), esc(picks.get(c['experiment'], '')), esc(short(c['candidate'])), esc(c['rule']),
                     esc(c['final']), esc('{} → {}'.format(','.join(map(str, c['baselineScores'])), ','.join(map(str, c['candidateScores'])))),
                     esc(delta), esc(fmt_time(c['closedAt'], now)), esc(fmt_dur(c['duration'])), esc(clip(c['reason'], 100))])
    out.append(table(['実験', 'タスク', '候補SHA', 'ルール判定', '最終判定', 'スコア (baseline → 候補)', '中央値Δ', '終了時刻', '所要', '理由'], rows)
               if rows else '<p class="muted">終了した実験なし</p>')
    if project['plan']:
        out.append('<details><summary>plan.md (先頭40行)</summary><pre>{}</pre></details>'.format(esc('\n'.join(project['plan']))))
    llm = state['llm']
    out.append('<h2>予算</h2><div class="cards"><div class="card"><b>ベンチ試行</b><br>直近1時間 {}回 · 累計 {}回</div>'.format(
        project['attempts']['lastHour'], project['attempts']['total']))
    out.append('<div class="card"><b>LLM費用</b><br>呼出 {}回 · 入力 {}トークン · 出力 {}トークン · ${:.4f}<br>'
               '<span class="muted">最終呼出 {}</span></div></div>'.format(
                   llm['calls'], llm['inputTokens'], llm['outputTokens'], llm['costUsd'], fmt_time(llm['lastCall'], now)))
    out.append('<h3>統合Agentの記録 (直近20件)</h3>' + table(['時刻', 'イベント', 'タスク', '実験', '内容'], [
        [esc(fmt_time(e.get('at'), now)), esc(e.get('event')), esc(e.get('task') or ''), esc(e.get('experiment') or ''), esc(compact(e))]
        for e in reversed(state['events'][-20:])]))
    if db['events']:
        out.append('<h3>台帳DBイベント (直近30件)</h3>' + table(['時刻', '実行者', '操作', '詳細'], [
            [esc(fmt_time(e.get('at'), now)), esc(e.get('actor')), esc(e.get('action')), esc(e['excerpt'])] for e in db['events']]))
    if state['feedback']:
        out.append('<h3>フィードバック (最新10件)</h3><ul>' + ''.join('<li>{} <span class="muted">{}</span>: {}</li>'.format(
            esc(f['name']), fmt_time(f['at'], now), esc(clip(f['line'], 160))) for f in state['feedback']) + '</ul>')
    out.append('<footer><div>台帳DB {} · プロジェクト {} · 状態ディレクトリ {}</div>{}</footer></body></html>'.format(
        esc(paths['db']), esc(paths['project']), esc(paths['state']),
        ''.join('<div class="bad">{}</div>'.format(esc(n)) for n in notes)))
    return ''.join(out)

def write_atomic(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        handle.write(text)
    os.replace(tmp, path)


def main(argv=None):
    p = argparse.ArgumentParser(description='Render a static dashboard from the team ledger, integrator state and project records.')
    p.add_argument('--db', required=True, help='team ledger SQLite path (opened read-only)')
    p.add_argument('--project', required=True, help='project root containing .kaizen/')
    p.add_argument('--state', required=True, help='integrator state dir (status.json, ledger.jsonl, pause, feedback/)')
    p.add_argument('--out', required=True, help='output dir for index.html and summary.json')
    args = p.parse_args(argv)
    now, notes = datetime.datetime.now(UTC), []
    db = read_db(args.db, notes)
    state = read_state(args.state, notes)
    project = read_project(args.project, now, notes)
    picks = {}
    for event in state['events']:
        exp, task = event.get('experiment'), event.get('task')
        if isinstance(exp, str) and isinstance(task, str) and (event.get('event') == 'pick' or exp not in picks):
            picks[exp] = task
    finals = [c['final'] for c in project['closed']]
    first = [median(c['baselineScores']) for c in reversed(project['closed']) if median(c['baselineScores']) is not None]
    env, res = project['state'], db['reservation']
    summary = {
        'generatedAt': now.isoformat(), 'stable': env.get('STABLE_REV') or None, 'deployed': env.get('DEPLOYED_REV') or None,
        'healthy': env.get('DEPLOYED_HEALTHY') == '1', 'revertPending': env.get('REVERT_PENDING') == '1',
        'currentExperiment': env.get('CURRENT_EXPERIMENT') or None, 'integrator': state['status'], 'paused': state['paused'],
        'reservation': {'owner': res['owner'], 'purpose': res['purpose'], 'acquiredAt': res.get('acquired_at')} if res else None,
        'counts': {}, 'ready': [t['id'] for t in db['tasks'] if t.get('status') == 'READY'],
        'needsHuman': [{'id': t['id'], 'question': t.get('human_question')} for t in db['tasks'] if t.get('status') == 'NEEDS_HUMAN'],
        'integrations': [{'experiment': c['experiment'], 'task': picks.get(c['experiment']), 'candidate': c['candidate'],
                          'rule': c['rule'], 'final': c['final'], 'baselineScores': c['baselineScores'],
                          'candidateScores': c['candidateScores'], 'closedAt': c['closedAt']} for c in project['closed']],
        'promoted': finals.count('promote'), 'rejected': finals.count('reject'),
        'inconclusive': len(finals) - finals.count('promote') - finals.count('reject'),
        'baselineMedian': median([s.get('score') for s in project['baseline']]), 'firstBaselineMedian': first[0] if first else None,
        'llm': {k: state['llm'][k] for k in ('calls', 'inputTokens', 'outputTokens', 'costUsd')},
        'benchAttempts': project['attempts'], 'gainPercent': None, 'unavailable': notes,
    }
    for task in db['tasks']:
        summary['counts'][task.get('status') or '?'] = summary['counts'].get(task.get('status') or '?', 0) + 1
    if summary['baselineMedian'] and summary['firstBaselineMedian']:
        summary['gainPercent'] = (summary['baselineMedian'] - summary['firstBaselineMedian']) / summary['firstBaselineMedian'] * 100
    paths = {'db': args.db, 'project': args.project, 'state': args.state}
    page = render_html(now, summary, db, state, project, picks, notes, paths)
    try:
        os.makedirs(args.out, exist_ok=True)
        write_atomic(os.path.join(args.out, 'index.html'), page)
        write_atomic(os.path.join(args.out, 'summary.json'), json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    except OSError as error:
        print('dashboard: cannot write {}: {}'.format(args.out, error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
