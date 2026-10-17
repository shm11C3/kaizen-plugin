# kaizen

ISUCON の改善ループを Claude Code のプラグインとして回すための道具です。2026 年の本番で使うことを前提に、競技ごとに変わる部分（ホスト、パス、ビルド、ベンチの起動方法）を設定ファイルに寄せ、ループの骨格（観測 → 仮説 → 変更 → 配備 → 計測 → 判定 → 記録 → 復旧）は変えずに使い回します。ISUCON14 は練習用のプリセットとして同梱しています。

## 構成

```
skills/      setup, observe, hypothesize, experiment, recover, status, knowledge（Claude が読む手順）
scripts/     deploy, verify, bench, observe, evaluate, recover, experiment, status, knowledge（決定論的な部分）
knowledge/   patterns/（シグネチャ・テンプレート・計測表）、signatures.py、match.py、records/、problems/
hooks/       guard.py: スクリプトを迂回する操作と、記録のない終了を止める
presets/     isucon14.sh（練習用）
templates/   config.sh.example, preset.sh.example（本番用に当日マニュアルから起こす）
tests/       偽リモートに対するループ全体のテスト
```

役割分担は次のとおりです。

| 誰が | 何を |
|---|---|
| Claude | 観測を読む、仮説を書く、コードを変える、判定結果を読んで次を決める |
| scripts/ | 配備と検証、ベンチの実行と記録、固定ルールでの判定、stable への復旧、予算と排他 |
| hooks/ | scripts/ を通さないベンチ・配備・記録の書き換えを拒否、未記録のまま終わらせない |
| 人間 | 設定、ルールの確認、いつでも停止、判定の上書き |

採否は固定ルール `plugin-rule-v1`（`evaluate.sh`）が `decision.json` に書き、Claude か人間がそれを読んで `experiment.sh record` で確定します。ルールと違う判断をするときは `--override` で理由ごと記録します。正しさ違反だけは上書きできません。

## 使い方

### インストール

```bash
claude --plugin-dir /path/to/kaizen-plugin
```

Claude Code からは `/kaizen:setup` `/kaizen:observe` `/kaizen:hypothesize` `/kaizen:experiment` `/kaizen:recover` `/kaizen:status` で呼べます。Codex では `skills/` と `scripts/` を直接参照してください（`AGENTS.md`）。

### 本番（2026）

1. チームの repo（サーバーのアプリ一式を `go/` `sql/` などに置いたもの）を用意する
2. `/kaizen:setup`：`templates/preset.sh.example` を当日マニュアルから埋め、`.kaizen/config.sh` に `APP_HOSTS`（3 台）と `BENCH_MODE=manual` を書く。マニュアルで禁止されていることを `.kaizen/RULES.md` に書く
3. stable を固定して配備し、復旧ドリルを通す
4. ポータルでベンチを回し、結果を `bench.sh baseline --result 'pass=true score=... errors=...'` で記録する
5. `/kaizen:observe` → `/kaizen:hypothesize` → `/kaizen:experiment` を回す

### 練習（ISUCON14）

`templates/config.sh.example` をそのまま使い、`BENCH_HOST` とプライベート IP を書けば、ベンチも SSH で自動実行されます。

## ナレッジ（`knowledge/`）

計測つきのパターン集です。`knowledge.sh match <observe dump>` が観測ダンプに機械的なシグネチャ（`knowledge/signatures.py`、1 パターン 1 関数）を当て、該当するパターンを根拠行つきで並べます。各 `knowledge/patterns/<id>.md` には仮説と変更のテンプレート、壊れやすい点のチェックリスト、そして **Measured** 表があり、`experiment.sh record` のたびに `knowledge.sh ingest` が実験結果（baseline → candidate、差分、サンプル数、所要分、判定、エラー種別）を追記します。公式解説や write-up は `sources:` として種を蒔くだけで、証拠として数えるのは Measured の行だけです。

`knowledge/problems/<problem>.md` は問題ごとに「公式解説が仕込んだボトルネックの順」と「実際に回した実験の順」を並べます。練習を重ねるほど、どのパターンを先にやると何分で何倍になるかが数字で残ります。

## 記録

`.kaizen/experiments/NNN-<slug>/` に `manifest.json`（仮説・観測根拠・変更範囲・期待効果）、`observe-*.txt`、`bench-*.json` と生ログ、`decision.json`、`record.json`、`timeline.tsv`（各フェーズの所要時間）が残ります。`.kaizen/log.md` は閉じた実験の一覧です。

## ルールと予算（`.kaizen/config.sh`）

| 変数 | 既定 | 意味 |
|---|---|---|
| `MIN_IMPROVEMENT_BP` | 300 | 中央値の改善がこれ未満なら inconclusive |
| `MAX_BENCH_PER_EXP` | 6 | 1 実験あたりのサンプル数上限 |
| `MAX_EXP_MINUTES` | 30 | 1 実験の制限時間 |
| `MAX_EXP_PER_HOUR` | 6 | 1 時間に開ける実験数 |

promote の条件は「候補の中央値が baseline の中央値を `MIN_IMPROVEMENT_BP` 以上上回り、最悪の候補サンプルが最良の baseline サンプルを上回る」です。

## テスト

```bash
tests/run.sh
```

偽のリモート（ホスト 2 台、偽ベンチ）に対して、配備・検証・baseline・promote・正しさ違反からの復旧・override・予算・hook をひととおり通します。
