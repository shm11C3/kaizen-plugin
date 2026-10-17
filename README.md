# kaizen

ISUCON の改善ループを Claude Code・Codex のプラグインとして回すための道具です。2026 年の本番で使うことを前提に、競技ごとに変わる部分（ホスト、パス、ビルド、ベンチの起動方法）を設定ファイルに寄せ、ループの骨格（観測 → 仮説 → 変更 → 配備 → 計測 → 判定 → 記録 → 復旧）は変えずに使い回します。ISUCON14 は練習用のプリセットとして同梱しています。

## チームでの利用

各メンバーは [競技用リポジトリ](https://github.com/shm11C3/isucon-competition) をcloneし、このプラグインをインストールします。運用規約・共通ホスト管理・調整用コマンド・テンプレートはプラグインが持ちます。

- [設計レビュー（2026-10-18）](DESIGN_REVIEW.md)と[実測結果と次の改善案](NEXT.md)
- [参加・インストール手順](team/docs/ONBOARDING.md)
- [teamスキル](skills/team/SKILL.md)と[共通規約](team/POLICY.md)
- [運用ガイド](team/docs/OPERATIONS.md)と[当日の手順](team/docs/RUNBOOK.md)
- [共通ホストの管理](team/infra/README.md)と[構築記録](team/infra/DEPLOYMENT.md)
- [実験選択・停滞時の再検討](team/docs/STRATEGY.md)と[効果の比較手順](team/docs/COMPARISON.md)
- [資源を含む復旧](team/docs/RECOVERY.md)と[0.3.0のリハーサル反映](team/docs/REHEARSAL.md)
- [Go／Rustの既存ツール・観測モード](team/docs/TOOLS.md)
- [候補提出前のLint・指摘の扱い](team/docs/LINT.md)
- [Go／Rustの選択・ビルド時間・キャッシュ・終盤の予算](team/docs/RUST_BUILD.md)
- [初期テスト・整備フェーズ](team/docs/PHASES.md)、[prepare-tests](skills/prepare-tests/SKILL.md)・[refactor](skills/refactor/SKILL.md)
- [Discord連携とGitHubユーザー名による命名](team/docs/DISCORD.md)
- [規約・手動操作・並列検証](team/docs/REGULATIONS.md)
- [共通台帳での並列検証と品質保留の修正・再計測](team/docs/PARALLEL_QUALITY.md)
- 未解消の品質保留はtaskを越えてsourceへ引き継ぎ、全採用taskを公式記録と実測SHAに照合します。
- sandbox stableの追従は上記の`target.py stable-sync`で公式採用記録へ束縛し、レーン内で新baselineを取ります。
- [EC2並列レーンの設定例](team/templates/ec2-lanes.example.json)（`scripts/team/ec2_lanes.py`で準備・状態確認・停止）
- [繰り返し作業の改善](team/docs/WORKFLOW.md)と[improve-workflowスキル](skills/improve-workflow/SKILL.md)

チームで参加するときは、Claudeでは `/kaizen:team`、Codexではkaizenのteamスキルから開始します。各AIはタスク発見から候補提出・次の作業まで自走し、共有環境の操作は単一の統合担当が行います。

## 構成

```
skills/      setup, observe, plan, hypothesize, experiment, recover, status, knowledge, retro, team, improve-workflow, prepare-tests, refactor
scripts/     deploy, verify, bench, observe, evaluate, recover, experiment, stable, status, knowledge（決定論的な部分）
knowledge/   patterns/（シグネチャ・テンプレート・計測表）、signatures.py、match.py、records/、problems/
hooks/       guard.py: スクリプトを迂回する操作と、記録のない終了を止める
presets/     isucon14.sh（練習用）
templates/   config.sh.example, preset.sh.example（本番用に当日マニュアルから起こす）
tests/       偽リモートに対するループ全体のテスト
```

役割分担は次のとおりです。

| 誰が | 何を |
|---|---|
| Claude / Codex | 観測を読む、仮説を書く、コードを変える、判定結果を読んで次を決める |
| scripts/ | 配備と検証、ベンチの実行と記録、固定ルールでの判定、stable への復旧と再固定（記録を main にコミットした後の `stable.sh repin`）、予算と排他 |
| hooks/ | scripts/ を通さないベンチ・配備・記録の書き換えを拒否、未記録のまま終わらせない |
| 人間 | 設定、ルールの確認、いつでも停止、判定の上書き |

採否は固定ルール `plugin-rule-v2`（`evaluate.sh`）が `decision.json` に書き、AIがそれを読んで `experiment.sh record` で確定します。通常改善は自動採用し、計測不足はAIが調査を続けます。具体的な価値・リスク判断を人間へ渡します。性能判定をpromoteへ上書きする場合は実際の `--human-decision` 参照が必要です。正しさ違反・品質未確認・比較不能な条件は参照だけで免除できません。

## 実験の選択と停滞時の再検討（0.4.0）

`plan`は現在の採点への影響・観測根拠・不確実性・計測と復旧までの総所要時間で実験順を決めます。過去の採用率は参考情報です。保存した判断や独自の案を残しつつ、基準版の変更後に見直します。

`status.sh`と`experiment.sh record`は、品質・性能比較に合格しない通常計測の連続、同じ仮説の再試行、設定値の往復を履歴から通知します。比較の合格・実採用・未計測・observed-onlyを区別して表示し、比較に合格したが未採用の履歴を性能停滞と混同しません。品質問題は別に表示します。`strategy.sh review`の検討項目を使ってAIが原因を調べ、planを更新します。採否判定や人間判断の範囲を変える通知ではありません。共有キューは仮説の重複作成を防ぎ、READY滞留時の自動取得を調査・比較タスクへ向けます。

これらによる競技力の優位性は未検証です。[同条件の比較試験](team/docs/COMPARISON.md)で最終有効スコア・初回採用までの時間・人間の介入・失敗と復旧時間を確認します。

## 使い方

### インストール

```bash
claude --plugin-dir /path/to/kaizen-plugin
```

Claude Code からは `/kaizen:setup` `/kaizen:observe` `/kaizen:hypothesize` `/kaizen:experiment` `/kaizen:recover` `/kaizen:status` で呼べます。Codexも同じskillsをプラグインとして読み込みます。インストールは[参加手順](team/docs/ONBOARDING.md)を参照してください。現在のhook adapterはClaude用です。

### 本番（2026）

1. チームの repo（サーバーのアプリ一式を `go/` `sql/` などに置いたもの）を用意する
2. `/kaizen:setup`：`templates/preset.sh.example` を当日マニュアルから埋め、`.kaizen/config.sh` に `APP_HOSTS`（3 台）と `BENCH_MODE=manual` を書く。マニュアルで禁止されていることを `.kaizen/RULES.md` に書く
3. stable を固定して配備し、復旧ドリルを通す
4. `bench.sh baseline --reserve`で枠を確保してからポータルでベンチを回し、`bench.sh baseline --result 'pass=true score=... errors=...'`で記録する
5. `/kaizen:observe` → `/kaizen:hypothesize` → `/kaizen:experiment` を回す

### 練習（ISUCON14）

`templates/config.sh.example` をそのまま使い、`BENCH_HOST` とプライベート IP を書けば、ベンチも SSH で自動実行されます。

## ナレッジ（`knowledge/`）

計測つきのパターン集です。`knowledge.sh match <observe dump>` が観測ダンプに機械的なシグネチャ（`knowledge/signatures.py`、1 パターン 1 関数）を当て、該当するパターンを根拠行つきで並べます。各 `knowledge/patterns/<id>.md` には仮説と変更のテンプレート、壊れやすい点のチェックリスト、そして **Measured** 表があり、`experiment.sh record` のたびに `knowledge.sh ingest` が実験結果（baseline → candidate、差分、サンプル数、所要分、判定、エラー種別）を追記します。公式解説や write-up は読んで「何を試すか」を決めるために使い、本文・数値・スコアはコーパスに含めません（`sources:` はリンクのみ）。証拠として数えるのは、このループが自分で計測した Measured の行だけです。また、コーパスは候補を示すだけで判断はしません。観測の最大コストがどのパターンにも当てはまらなければ、それが次の仮説です。

`knowledge/problems/<problem>.md` は問題ごとに「公式解説が仕込んだボトルネックの順」と「実際に回した実験の順」を並べます。練習を重ねるほど、どのパターンを先にやると何分で何倍になるかが数字で残ります。

## 記録

`.kaizen/experiments/NNN-<slug>/` に `manifest.json`（仮説・観測根拠・変更範囲・期待効果）、`observe-*.txt`、`bench-*.json` と生ログ、`decision.json`、`record.json`、`timeline.tsv`（各フェーズの所要時間）が残ります。`.kaizen/log.md` は閉じた実験の一覧です。

## ルールと予算（`.kaizen/config.sh`）

| 変数 | 既定 | 意味 |
|---|---|---|
| `MIN_IMPROVEMENT_BP` | 300 | 中央値の改善がこれ未満なら inconclusive |
| `MAX_BENCH_PER_EXP` | 6 | 復旧・結果なし・実験終了後の追加復旧も含む物理試行上限 |
| `MAX_BENCH_TOTAL` / `MAX_BENCH_PER_HOUR` | 120 / 30 | project全体 / 直近1時間の物理試行上限 |
| `RECOVERY_BENCH_RESERVE` | 1 | 実験内で最後のstable計測用に残す枠 |
| `MIN_SAMPLES` | 2 | baseline/candidateそれぞれの最低サンプル数（v2） |
| `EVALUATION_RULE` | v2 | v2: 両側 2 本以上、エラー率はリクエスト分母で比較。v3: 逐次判定（1 本で幅を超えれば promote、全 baseline を下回れば reject、幅内なら追加）。v3 は実測比較が済むまで opt-in |
| `REQUEST_COUNT_CMD` | なし | 単一の非負整数を返す累積カウンター。SSHは実行前後、manualは予約時／結果登録時の差を分母にする。SSHの `parse_bench_requests` はこちらより優先 |
| `NGINX_HOST` | 最初のapp host | カウンターを読むSSHホスト。実際のログ／カウンターがあるホストに合わせる |
| `BASELINE_MAX_AGE_MINUTES` | 60 | 古いbaselineを判定から外す期限 |
| `MAX_EXP_MINUTES` | 30 | 1 実験の制限時間 |
| `MAX_EXP_PER_HOUR` | 6 | 1 時間に開ける実験数 |

stable bundle の同一性は計測条件（ホスト、配備・再起動・ヘルスチェック・復旧・ベンチのコマンド、資源の指紋）だけで決まります。予算や閾値、観測の設定、plugin 自体の更新では bundle は無効になりません。本番中に plugin を直す前提なので、どの plugin 版で測ったかは bundle と各サンプルの `pluginRevision` に記録します。

分母の取得コマンド・ホスト・解析関数も比較条件です。変更したら安定状態で`stable.sh capture`し直し、
新しいbaselineを取得します。manualの`--reserve`はカウンターと条件を保存し、`--result`で差分を記録します。
予約中の条件変更は結果登録を拒否し、予約を保持します。元に戻して登録するか、実行終了を確認してabandonします。
`--requests N`による明示入力は別の取得方法として記録し、自動取得との混在はv2／v3とも再計測へ戻します。
サンプルの`requestSource`に方法・ID・ホスト・カウンター前後値・状態が残ります。取得失敗・不正出力・
カウンター減少は分母不明です。ログ差分には予約から結果登録までの全通信が入るため、対象と計数範囲を揃え、
ローテーションや別通信が比較を汚さないことを確認します。
0.6.2への更新時は条件hashへ分母設定を追加したため、旧bundleも安定状態で再captureし、新baselineを取ります。

promoteは、同じstable bundleに紐付く新しいbaselineと固定candidateで品質を確認し、中央値が `MIN_IMPROVEMENT_BP` 以上改善し、最悪candidateが最良baselineを上回る場合です。非ゼロのerrorがある場合、v2 では比較可能なrequest分母がない・新種がある・率が増える候補を調査へ戻します。v3 では分母がなくても既知の種類は件数で比べ、急増（最悪 baseline の 2 倍かつ +5 件超）と新種だけを調査へ戻します。エラー要約は `map[k:v]`、`種別:METHOD:/path xN`、`key=value` の各形式を読みます。エラー種別を `CORRECTNESS_ERROR_TYPES` に指定した場合はpassフラグにかかわらず拒否します。

採用直前にも実資源のfingerprintを取得し、計測済みcandidateと照合します。人間判断待ちの
recover後はコード再deployだけで資源まで戻ったと扱わず、[候補資源の復元・再確認](team/docs/RECOVERY.md#採用直前の資源確認)を行います。

## テスト

```bash
tests/run.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

偽のリモート（ホスト 2 台、偽ベンチ）に対して、配備・検証・baseline・promote・正しさ違反からの復旧・override・予算・hook をひととおり通します。

Go／RustのLint検出と実行時間は`python3 tests/measure_lint.py --output .local/lint-validation-new`で
再測定できます。出力先は新規にし、native Go／Rustとfmt／Clippyを用意します。
[実測記録](knowledge/lessons/20261018-lint-validation.md)は小さなfixtureの結果です。
