# kaizen

ISUCON の改善ループを Claude Code・Codex のプラグインとして回すための道具です。2026 年の本番で使うことを前提に、競技ごとに変わる部分（ホスト、パス、ビルド、ベンチの起動方法）を設定ファイルに寄せ、ループの骨格（観測 → 仮説 → 変更 → 配備 → 計測 → 判定 → 記録 → 復旧）は変えずに使い回します。ISUCON14 は練習用のプリセットとして同梱しています。

## チームでの利用

各メンバーは [競技用リポジトリ](https://github.com/shm11C3/isucon-competition) をcloneし、このプラグインをインストールします。運用規約・共通ホスト管理・調整用コマンド・テンプレートはプラグインが持ちます。

- [参加・インストール手順](team/docs/ONBOARDING.md)
- [teamスキル](skills/team/SKILL.md)と[共通規約](team/POLICY.md)
- [運用ガイド](team/docs/OPERATIONS.md)と[当日の手順](team/docs/RUNBOOK.md)
- [共通ホストの管理](team/infra/README.md)と[構築記録](team/infra/DEPLOYMENT.md)
- [実験選択・停滞時の再検討](team/docs/STRATEGY.md)と[効果の比較手順](team/docs/COMPARISON.md)
- [資源を含む復旧](team/docs/RECOVERY.md)と[0.3.0のリハーサル反映](team/docs/REHEARSAL.md)
- [Discord連携とGitHubユーザー名による命名](team/docs/DISCORD.md)
- [規約・手動操作・並列検証](team/docs/REGULATIONS.md)
- [共通台帳での並列検証と品質保留の修正・再計測](team/docs/PARALLEL_QUALITY.md)
- [繰り返し作業の改善](team/docs/WORKFLOW.md)と[improve-workflowスキル](skills/improve-workflow/SKILL.md)

チームで参加するときは、Claudeでは `/kaizen:team`、Codexではkaizenのteamスキルから開始します。各AIはタスク発見から候補提出・次の作業まで自走し、共有環境の操作は単一の統合担当が行います。

## 構成

```
skills/      setup, observe, plan, hypothesize, experiment, recover, status, knowledge, retro, team, improve-workflow
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

`status.sh`と`experiment.sh record`は、改善採用に至らない実験の連続、同じ仮説の再試行、設定値の往復を履歴から通知します。`strategy.sh review`の検討項目を使ってAIが原因を調べ、planを更新します。採否判定や人間判断の範囲を変える通知ではありません。共有キューは仮説の重複作成を防ぎ、READY滞留時の自動取得を調査・比較タスクへ向けます。

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
| `MIN_SAMPLES` | 2 | baseline/candidateそれぞれの最低サンプル数 |
| `BASELINE_MAX_AGE_MINUTES` | 60 | 古いbaselineを判定から外す期限 |
| `MAX_EXP_MINUTES` | 30 | 1 実験の制限時間 |
| `MAX_EXP_PER_HOUR` | 6 | 1 時間に開ける実験数 |

promoteは、同じstable bundleに紐付く新しいbaselineと固定candidateで品質を確認し、中央値が `MIN_IMPROVEMENT_BP` 以上改善し、最悪candidateが最良baselineを上回る場合です。非ゼロのerrorがある場合、比較可能なrequest分母がない・新種がある・率が増える候補は調査へ戻します。エラー種別を `CORRECTNESS_ERROR_TYPES` に指定した場合はpassフラグにかかわらず拒否します。

## テスト

```bash
tests/run.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

偽のリモート（ホスト 2 台、偽ベンチ）に対して、配備・検証・baseline・promote・正しさ違反からの復旧・override・予算・hook をひととおり通します。
