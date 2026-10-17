# 運用ガイド

この文書とコマンドはプラグイン側にあります。`K` はインストール済みkaizenのルートです。競技用cloneへ管理スクリプトをコピーしません。

## 基本構成

人間3人と、それぞれのPC上で動くClaude・Codexの独立セッションで作業します。担当分野は固定しません。同じPCの複数セッションはworktreeを分けます。共有環境を操作する統合担当は同時に1セッションです。

各AIは[Discord](DISCORD.md)の現在の方針・関連スレッドと共有台帳を自分で読み、観測資料から課題を発見し、重複と依存関係を確認してタスクを登録します。取得後は仮説・実装・ローカル検証・候補提出まで進み、最新状況を読み直して次へ進みます。毎回の人間からの指示を待ちません。

| 情報 | 正本 |
|---|---|
| ソース・設定・候補・採用済み変更 | Private Gitリモート |
| タスクの担当と状態、環境占有 | 共通ホストのSQLite |
| 現在の配備・stable・実験・採否 | 統合用cloneのkaizen記録 |
| 議論・発見通知・人間の判断 | 非公開Discord。採否判断は実験記録にも保存 |
| ベンチの生ログ・観測資料 | 共通ホストのartifacts。小さな要約と参照先をGitへ保存 |

共通ホストの台帳は調整用です。台帳をDONEにするだけでは採用になりません。kaizenの正しさ・性能評価・復旧確認が必要です。

## タスクを進める

参加時はONBOARDINGのjoinを通し、作業の区切りで `control.py queue` を読む。READYが既定2件以上なら、既存候補のログ解析や計測不足の解消を優先する。役割を固定せず、未計測候補を積み上げない。

以下は各PCでの例です。ONBOARDINGで設定した`KAIZEN_GITHUB_USER`と`KAIZEN_SESSION`を使います。コマンドの結果はJSONです。証拠には共有ホスト上の観測ファイルなど、他のメンバーが確認できる参照先を指定します。

```bash
python3 "$K/scripts/team/control.py" task-list
python3 "$K/scripts/team/control.py" task-create --title '履歴クエリの総時間を削減する' \
  --evidence '/srv/isucon/artifacts/observe-001.txt:history-query' --priority 80 \
  --hypothesis history-query-index --kind implementation
python3 "$K/scripts/team/control.py" task-claim --agent "$KAIZEN_SESSION"
```

`task-claim`の成功が担当確定です。取得後にDiscordへ `CLAIM T-0001 by <実際のセッションID>` と通知します。別IDのタスクでも、同じDBテーブル・APIの意味・キャッシュ・設定へ影響するなら調整します。必要な前提変更が未採用なら待ち、無関係な作業を進めます。

```bash
git fetch origin
git switch -c "${KAIZEN_GITHUB_USER}/T-0001-query-index" origin/main
# 実装、適切なローカル検証、明示したファイルをstage
git add app/path/to/changed-file
git commit -m 'perf: reduce history query work'
git push -u origin HEAD
python3 "$K/scripts/team/control.py" task-ready --id T-0001 --agent "$KAIZEN_SESSION" \
  --base FULL_BASE_SHA --sha FULL_SOURCE_SHA --review auto \
  --reason '局所変更、振る舞いを維持、復旧方法と検証を候補票に記録'
```

`team/templates/CANDIDATE.md`を埋めて提出します。base SHAは作業開始点、source SHAは提出した変更、candidate SHAは統合後に実際に計測する変更です。候補票のSHAと参照先をDiscordに投稿します。タスク取得と提出は許可の申請ではありません。

## 統合と計測

```bash
python3 "$K/scripts/team/control.py" env-acquire --agent "$KAIZEN_SESSION" --purpose 'T-0001の統合・計測'
```

返されたtokenは、この占有世代の識別子です。同じ担当でも古いtokenは使えません。占有はコマンド終了や時間経過で消えません。

統合担当は共通ホストの `/srv/isucon/repo` で最新mainから候補を作り、提出コミットを取り込みます。kaizenの実験manifestに観測根拠と変更範囲を設定し、競技環境を変える操作は `scripts/team/target.py` から行います。ラッパーは対象未設定なら拒否します。

統合用の実験は占有中に次の形式で開始します。GitHubユーザー名は現在の統合担当のものを渡します。

```bash
python3 "$K/scripts/team/control.py" target --agent "$KAIZEN_SESSION" --token TOKEN \
  experiment new query-index --github-user "$KAIZEN_GITHUB_USER"
```

ブランチは`<github-login>/exp/NNN-query-index`になります。task ID、実験ID、
workerのsource SHA、統合候補SHAを対応付け、既存候補は改名せず参照を維持します。
チーム用ラッパーでの実験開始には`--github-user`が必要です。
単独練習で直接scriptを呼び、引数を省略した場合だけ従来の`exp/NNN-summary`を使えます。

各PCからも `control.py target` を使って同じラッパーを呼べます。対話シェル用のSession Manager pluginは不要です。

```bash
python3 "$K/scripts/team/control.py" target --agent "$KAIZEN_SESSION" --token TOKEN deploy FULL_CANDIDATE_SHA
```

長い処理ではCommand IDが返り、クライアントの待機が先に終了する場合があります。`python3 "$K/scripts/team/control.py" result COMMAND_ID`で結果を再取得します。待機の終了を処理失敗とみなして同じ操作を重ねてはいけません。

```bash
# 共通ホスト上で実行。初期状態では対象操作は無効。
python3 "$K/scripts/team/target.py" --agent "$KAIZEN_SESSION" --token TOKEN deploy FULL_CANDIDATE_SHA
python3 "$K/scripts/team/target.py" --agent "$KAIZEN_SESSION" --token TOKEN bench candidate
python3 "$K/scripts/team/target.py" --agent "$KAIZEN_SESSION" --token TOKEN evaluate
python3 "$K/scripts/team/target.py" --agent "$KAIZEN_SESSION" --token TOKEN experiment record '採用条件を満たした'
```

ポータル方式では占有を取ったまま人間がベンチを開始し、終了後に `bench candidate --result 'pass=true score=... errors=none'` で記録します。記録コマンドの時間だけを占有期間にしてはいけません。ログのリセット・プロファイリング設定変更も同じ占有下で行います。

開始前に必ず `target ... bench candidate --reserve` を実行する。物理予算を消費し、結果の記録までdeploy/observe/占有解放・引継ぎを拒否する。終了したが結果を取得できない場合は、実行終了を確認して `target ... bench candidate --abandon '終了確認と理由'`。回数は返却されない。`--requests N`で比較可能なリクエスト総数を記録できる。SSH方式は任意の `parse_bench_requests <log>` で総数を返せる。

採用は計測したcandidateをmainへfast-forwardし、originへpushします。mainへのpushは統合担当だけが行います。更新競合なら止めて実状態を確認します。force-pushはしません。小さな実験要約を `records/` へ保存し、kaizenの手順で記録コミット後のstableを再固定します。却下・保留ならstableを復旧します。

タスクの採否も台帳へ反映します。`task-finish`の採否更新は環境占有者に限定され、人間判断対象の採用には実際の判断への参照が必要です。参照文字列の存在だけで承認の真偽を検証できる仕組みではありません。

```bash
python3 "$K/scripts/team/control.py" task-finish --id T-0001 --agent "$KAIZEN_SESSION" \
  --result ACCEPTED --reason '計測・採用記録: records/E-0001.md'
# 人間判断対象の場合は --human-decision 'Discordの判断メッセージURL等' を追加
```

採否の台帳更新は占有を解放する前に行います。

環境が採用済み版または復旧したstableに一致し、対象操作が終わってから解放します。

```bash
python3 "$K/scripts/team/control.py" env-release --agent "$KAIZEN_SESSION" --token TOKEN \
  --reason 'stableと全ホストの一致、実行中ベンチなしを確認'
```

`env-release`は実行中のラッパーがあれば拒否します。実際のサーバー状態とポータルベンチ終了の確認は統合担当の責任です。

## 自動採用と人間判断

独立sandboxでの並列検証と、品質保留になった候補の修正・再提出は
[並列検証と品質保留](PARALLEL_QUALITY.md)に従う。共通のタスク台帳を維持し、
保留の元SHA・原因・修正・公式再計測をつなげて記録する。

計測不足や原因未解明のエラーは `task-finish --result NEEDS_MEASUREMENT`。元の担当が `task-resume --id T-0001 --agent SESSION --reason '調査を再開'` してCLAIMEDへ戻し、追加検証・再提出を行う。人間判断待ちは `--result NEEDS_HUMAN --question '判断してほしい選択'` とし、reasonに根拠・選択肢・推奨を記す。

integratorは人間判断対象をmanifest.review=humanに設定する。採用時は `experiment record --human-decision ACTUAL_REF '理由'` とtask-finishの両方に実際の参照を記録する。質が不明な計測や正しさの問題は、この参照でも免除しない。

通常の改善は、観測根拠・正しさ・現在のstableとの比較・性能評価・復旧可能性が揃い、人間判断条件に当てはまらなければAIが採用します。小さい差やノイズは計測を追加するか保留します。

人間が判断するのは、採否が悩ましいもの、修正範囲が大きくリスクを伴うもの、重要なトレードオフがあるもの、構成や方針に複数の有力案があるものです。細かな実装方法の選択はAIが進めます。行数だけでリスクを決めません。

AIは安全な調査・実装・検証・比較を終え、`team/templates/HUMAN_DECISION.md`で推奨案まで示します。危険な環境操作は実行前に相談します。承認は対象SHAまたは具体的な操作範囲と結び付けます。人間待ち候補はstableへ戻して計測枠を空け、他の改善を続けます。待っている間にstableが変わったら取り込み直して再計測します。

正しさ違反や競技ルール違反は採用できません。コードの再配備だけでDB・インデックス・設定・データまで戻るとみなしてはいけません。

## Discord

[Discord連携手順](DISCORD.md)で読取・投稿・再開時の確認を行います。`#ops`（占有・障害）、`#discoveries`（観測）、`#tasks`（タスクごとのスレッド）、`#benchmarks`（SHA・条件・結果）、`#decisions`（人間判断）を使います。開始・有用な発見・候補提出・採否・障害を簡潔に通知します。実装の逐語的な実況は不要です。

Bot・MCPは接続後に利用します。読む手段があることと、新着でAIが起動することは別です。現在の構成は各自が起動したセッションが区切りごとに状態を確認する運用です。未接続なら投稿用文章を人間へ渡し、通知済みと偽ってはいけません。

## 計測待ちの作業と方針の再検討

[戦略手順](STRATEGY.md)に従う。`queue`はREADY滞留、候補タスク、担当者が再開するNEEDS_MEASUREMENTを返す。自動`task-claim`はREADYが2件以上ならimplementationを選ばない（`--ready-limit`で指定可）。進める理由がある実装は明示`--id`で取得できる。タスクIDが違っても意味上の重複は自分で確認する。

```bash
python3 "$K/scripts/team/control.py" task-create --title '既存traceでlock待ちとCPUを比較' \
  --evidence '/srv/isucon/artifacts/trace-001' --kind investigation \
  --hypothesis distinguish-lock-from-cpu --priority 85
python3 "$K/scripts/team/control.py" task-claim --agent "$KAIZEN_SESSION"
python3 "$K/scripts/team/control.py" task-complete --id T-0002 --agent "$KAIZEN_SESSION" \
  --reason '比較結果: artifactへの参照、反証した説明、推奨する次の実験'
```

`task-complete`は担当者のCLAIMEDな調査・比較専用でDONEにする。実装の採用や共有環境の操作権限は与えない。`--hypothesis`の同一キーを持つ未完了タスクの作成は原子的に拒否する。別の比較作業は目的を表す別キーを付け、関連候補をevidenceへ記す。過去の完了済み仮説を再試行するときは、新しい根拠を明記する。

統合担当は`control.py target --agent SESSION --token TOKEN strategy status`を作業の区切りで確認する。`strategy review`は検討テンプレートを出力する。現行の採点経路・待ち時間・予測が外れた原因・別機構の選択肢を揃えてplanを更新する。通知は採否や品質検証を免除しない。
