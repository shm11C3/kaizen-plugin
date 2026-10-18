# 常駐の統合Agent（制御ホスト・Claude Code on Amazon Bedrock）

共通ホストで動く無人の統合担当です。各メンバーのAIは調査・実装・ローカル検証・READY提出に集中し、
提出された候補の合成・計測・採否記録・push・台帳更新をこのサービスが直列に行います。
人間が見る状態は[ダッシュボード](#ダッシュボード)に出ます。

## 境界

- 対象操作はすべて `scripts/team/target.py` 経由です。占有、プロセスロック、kaizen各スクリプトの拒否条件は
  人間が統合するときと同じで、このサービスが新しい操作経路を増やすことはありません。
- 採否は固定ルール（`EVALUATION_RULE`）が決めます。モデルは候補1件につき1回、合成済み差分の契約レビュー
  （課題票と差分の整合、無関係な変更・検証の無効化・空差分の検出）にだけ呼ばれ、`proceed=false` なら
  ベンチ枠を使わずに `NEEDS_MEASUREMENT` で担当者へ返します。効果の大小やノイズはレビュー理由になりません。
- READYが無い間はsleepだけで、トークンを消費しません。`pause` ファイルがあると新しい候補を取りません。
- 合成できない候補（cherry-pick衝突、採用済み変更と同じファイルの合成、空差分）は計測せずに返します。
  衝突の自動解決はしません。担当者が現在の `main` にrebaseし、統合SHAを再提出します。
- `review=human` の候補は取りません（人間判断の参照が必要なため、従来どおり人が統合します）。
- 1候補が失敗すると、stable復旧・実験のinconclusive記録・タスクの返却を試み、`pause` して止まります。
  再開は人が状態を確認してからです（`resume`）。

処理の流れ（1候補）: `env-acquire` → `git fetch` → 一時worktreeで `base..source` をstableへcherry-pick（dry run）
→ 契約レビュー → 必要ならbaseline補充 → `experiment new` → 本番cherry-pick → manifest記入 → `deploy`
→ `bench`/`evaluate` をルールの `nextAction` が `remeasure` の間、予算内で繰り返す → `experiment record`
→ promoteなら `task-finish ACCEPTED --record --tested-sha` と `git push origin main`、正しさ失敗なら
`task-quality-hold --category correctness`（失敗したソースに保留が残り、修正・再提出の導線になる）、
スコア低下の reject なら `REJECTED`、品質不明なら `task-quality-hold`、ノイズならNEEDS_MEASUREMENT → `env-release`。
候補の標本数は `MAX_BENCH_PER_EXP`（0 なら plugin 側の上限なし）と `integrator.json` の
`max_candidate_samples`（既定 6）の小さい方で打ち切ります。baseline の補充は実験を開いてから
その実験の枠内で行う（閉じた実験の枠に課金されると次の候補が待ち続けるため）ので、`MAX_BENCH_PER_EXP` を
正の値にするなら `2×MIN_SAMPLES + RECOVERY_BENCH_RESERVE` 以上にします。stable の baseline に失敗サンプルがあれば
`stable.sh forget-baseline` で退避してから取り直します。
各段階は `/srv/isucon/state/integrator/ledger.jsonl` に時刻・所要・結果・モデル費用付きで残り、
担当者向けの短い結果票が `feedback/T-NNNN.md` に書かれます。

## 前提（当日前に済ませる）

| 項目 | 内容 | 確認方法 |
|---|---|---|
| Bedrockのモデル利用申請 | AWSアカウントごとに1回、Model catalogでAnthropicモデルのuse caseを送る（authorization）。**加えてモデルごとに Marketplace の利用規約（agreement）の受諾が要る**。2026-10-19 の実測: 申請後も 5.5 系は `agreementAvailability: NOT_AVAILABLE` で `not available for this account`、Sonnet 4.6 だけ利用可。`aws bedrock list-foundation-model-agreement-offers --model-id anthropic.claude-opus-5-5` の offerToken で `aws bedrock create-foundation-model-agreement` を実行すると PENDING → AVAILABLE になる（Opus/Sonnet/Haiku 5.5 の3件） | `aws bedrock get-foundation-model-availability --model-id anthropic.claude-opus-5-5 --region ap-northeast-1` の4項目が全て AVAILABLE/AUTHORIZED |
| IAM | EC2 role `isucon-competition-control-ssm` に [bedrock-policy.json](bedrock-policy.json) をinline policyとして付与 | 下のコマンド |
| 推論プロファイルID | `ap-northeast-1` には `jp.`（国内のみ）と `global.` のプロファイルがあり、5.5 系に `apac.` は無い（2026-10-18 実測）。Opus 5.5 `jp.anthropic.claude-opus-5-5`、Haiku 5.5 `jp.anthropic.claude-haiku-5-5`、Sonnet 5.5 は `global.` のみ。Claude Code の既定は `ap-*` を `apac.` に解決するので、全エイリアスを固定し `ANTHROPIC_BEDROCK_REGION_PREFIX=jp` を置く | `aws bedrock list-inference-profiles --region ap-northeast-1` |
| クォータ | Bedrockのモデル別TPM/RPMは新規アカウントで低い。当日前に引き上げ申請し、模擬運転で429が出ないことを見る | Service Quotas / 模擬運転 |
| 規約 | ISUCON2026規定はAI利用と外部での開発・テストを許可、競技ベンチ中の外部委譲を禁止（[REGULATIONS](../../docs/REGULATIONS.md)）。統合Agentはベンチを実行・肩代わりしない。当日マニュアルを優先 | 当日確認してRULESへ記録 |
| ハードウェア | Claude Code文書の要件は4 GB以上のRAM。共通ホストは t3.small（2 GiB）。文書上の対応OSにAmazon Linuxは無い（Ubuntu/Debian等） | 模擬運転で `claude --version` と1回の `-p` 呼び出し、メモリを見て必要なら t3.medium へ |

```bash
# 各自のPCで（管理者のAWS認証）
aws iam put-role-policy --role-name isucon-competition-control-ssm \
  --policy-name kaizen-integrator-bedrock \
  --policy-document "file://$K/team/infra/integrator/bedrock-policy.json"
```

## 構築

共通ホストへSSM Run Commandで（または `control.py shell` から root で）実行します。既存の設定は上書きしません。

```bash
sudo bash /srv/isucon/kaizen-plugin/team/infra/integrator/install.sh        # CLAUDE_VERSION=2.1.x で固定可
sudo -u isucon vi /srv/isucon/state/integrator.env                            # region・モデルID
sudo -u isucon vi /srv/isucon/state/integrator/integrator.json                # github_user・review・予算
```

疎通確認（ソースを送らない。`join.py` と同じ形の最小呼び出し）:

```bash
sudo -iu isucon bash -c 'set -a; . /srv/isucon/state/integrator.env; set +a; cd "$(mktemp -d)"; \
  claude -p --output-format json --no-session-persistence --tools "" --strict-mcp-config \
  --mcp-config "{\"mcpServers\":{}}" --permission-mode dontAsk --max-turns 1 --max-budget-usd 0.05 \
  "Reply with exactly KAIZEN_PROBE"' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("is_error"), d.get("result"), d.get("total_cost_usd"))'
```

Bedrock上の `claude -p` は、明示しないと `auto` 権限モードで始まります。設定ファイルの `llm.command` は
`--permission-mode dontAsk --tools ""` を必ず含めてください（既定値は含みます）。

## 起動・停止

対象が当日の手順（[RUNBOOK](../../docs/RUNBOOK.md)）で有効化され、`target.json` の3つの確認が `true`、
stable bundleとbaselineが揃い、`env-register` で `competition` 環境が登録された後に起動します。
`task-finish ACCEPTED` は登録済みの公式環境を要求するので、登録前の採用は失敗します。

```bash
sudo systemctl enable --now kaizen-integrator.service
sudo systemctl status kaizen-integrator.service
sudo journalctl -u kaizen-integrator.service -f
```

停止は `systemctl stop`（SIGTERM）で、進行中の候補を最後まで処理してから終了します（最大1時間待つ設定）。
新しい候補だけ止めたい場合は `pause` を使います。

各PCから（SSM Run Command経由、tokenは要りません）:

```bash
python3 "$K/scripts/team/control.py" integrator status
python3 "$K/scripts/team/control.py" integrator pause --reason '方針変更の相談中'
python3 "$K/scripts/team/control.py" integrator resume
python3 "$K/scripts/team/control.py" dashboard                  # summary.json
python3 "$K/scripts/team/control.py" dashboard --open           # http://localhost:18080/ をSSMポート転送で開く
```

`BENCH_MODE=manual`（ポータル方式）では、統合Agentが `bench LABEL --reserve` で物理枠を取ったあと
`waiting` 状態でポータル結果を待ちます。人間がポータルで走らせ、終了を確認してから結果を渡します。
時間切れでの自動abandonはしません。

```bash
python3 "$K/scripts/team/control.py" integrator result --experiment 003-T-0001-query-index --label candidate \
  --result 'pass=true score=12345 errors=none' --requests 240000 --seconds 65 --sha 2efb015
python3 "$K/scripts/team/control.py" integrator abandon --experiment 003-T-0001-query-index --label candidate-2 \
  --reason 'ポータル側でキャンセル確認済み'
```

`--experiment` と `--label` は待機状態の表示どおりに渡します（baseline 補充中は `--experiment baseline`）。
予約より前に投稿された結果、別の実験・label の結果、`--sha` が配備版と違う結果は取り込まず、
`inbox/*.stale-*` に退避して台帳に残します。遅延投稿や二重投稿が別の候補へ帰属することはありません。

## ダッシュボード

`scripts/team/dashboard.py` が台帳（読み取り専用）・統合Agentの状態・kaizen記録から静的な
`index.html` と `summary.json` を作り、`kaizen-dashboard.service` が `127.0.0.1:8080` で配ります。
共通ホストにインバウンドの口は無いので、各自 `control.py dashboard --open` のSSMポート転送で見ます。
30秒ごとに自動更新、統合Agentは候補ごと・ポーリングごとに再生成します。

表示: stable/配備状態、統合Agentの状態（idle/waiting/working/paused/error）、占有、スコア時系列
（baselineは白丸、candidateは黒丸、失敗は赤×、stableごとの中央値の階段線）、状態別タスク一覧と人間判断の質問、
統合履歴（実験ID・タスク・候補SHA・ルール/最終判定・スコア・所要）、物理ベンチ予算、モデル費用の合計、
直近イベント、担当者向け結果票。台帳のeventsにはtokenが含まれる行があるため、表示前に除いています。

## 費用

- モデル費用は候補1件あたり1回の `-p` 呼び出しで、差分サイズ（上限 `max_diff_bytes`、既定60 KB）＋固定文に比例します。
  各呼び出しに `--max-budget-usd`（既定1 USD）が付き、`total_cost_usd`（クライアント側推定）を台帳に記録します。
  Bedrockの請求はAWS側なので、AWS Budgetsのアラートをチームで設定してください。
- EC2は [共通ホスト](../README.md#料金と監査) のとおり。統合Agentの待機中はCPUをほぼ使いません。
- 公式ベンチの物理予算（`MAX_BENCH_*`）は従来どおりkaizenが数え、尽きると候補をREADYのまま `waiting` で待ちます。

## 検証状況

2026-10-18〜19 に制御ホスト（`isucon-competition-control`、AL2023 t3.small）と ISUCON14 練習環境（app1・bench を起動）で模擬運転した。

| 項目 | 結果 |
|---|---|
| Claude Code 導入 | ネイティブインストーラで 2.1.302 が AL2023 に入った（文書の対応 OS 一覧に無いが動作）。`install.sh` 経由、isucon ユーザーの `~/.local/bin` |
| Bedrock 疎通 | インスタンスロール＋inline policy で `claude -p` が応答。`jp.anthropic.claude-sonnet-4-6`: 2 秒、`total_cost_usd` 0.024（system prompt 約 6.3k トークンの cache 作成分が主） |
| 5.5 系モデル | 利用申請フォーム提出後も `anthropic.claude-{opus,sonnet,haiku}-5-5 is not available for this account`。原因はモデルごとの Marketplace agreement 未受諾（上の前提表）。2026-10-19 01:08 JST に 3 件の agreement を受諾し `agreementAvailability: AVAILABLE`（authorization / entitlement / region も全て可）になったが、その後 25 分間、Converse / InvokeModel とも東京・us-east-1・us-west-2 で同じ拒否が続いた。**アカウント側のゲート**（エラー文の「contact AWS Sales」）と判断し、制御ホストは `jp.anthropic.claude-sonnet-4-6` のまま運用する。5.5 を使うには AWS サポート/営業への申請が必要。利用不可のモデルを `ANTHROPIC_MODEL` に置くと `claude -p` は内部で再試行して約 4.5 分後に失敗する（`llm.timeout_seconds` 300 で打ち切られ、レビューは `unavailable` として進む）。Sonnet 4.6 は提出直後から利用可 |
| メモリ | 2 GiB のうち統合 Agent 常駐 10 MB、`claude -p` 実行中も空き 800 MB 以上。t3.small で足りた |
| 統合の流れ | READY → `env-acquire` → fetch → 合成 dry run → Bedrock 契約レビュー（proceed、日本語の理由・リスク、6.6 秒、$0.035）→ baseline 計測まで無人で到達 |
| エラー経路 | 再起動直後の app1 で unattended-upgrades がアプリを停止し、baseline ベンチが 502 で失敗。統合 Agent は復旧確認→タスクを NEEDS_MEASUREMENT で返却→`pause`→占有解放まで設計どおり。原因はホスト側（setup スキルの「Quiet hosts」未適用）で、`BENCH_PRECHECK_CMD` を preset に追加して再提出 |
| ダッシュボード | `kaizen-dashboard.service` が 127.0.0.1:8080 で配信。`control.py dashboard --open` には各 PC に Session Manager plugin が必要（未導入の PC では `control.py dashboard` の summary.json を使う） |
| ポータル方式 | `result`/`abandon` の受け渡しは fake remote のテストのみ（本番ポータルでは未実施） |

模擬運転の最終結果（T-0001 の再提出以降）は PR のコメントに記録する。
