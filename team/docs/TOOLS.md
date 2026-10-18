# 既存ツールで観測する

Go／Rustを対象とする。現在のボトルネックを区別する最小構成を選び、既存ツールの生データを使う。
全ツールの導入を参加条件にしない。
[profile Skill](../../skills/profile/SKILL.md)で、問いに合う道具の選択から出力確認・解析・
仮説への引き渡しまで行う。[既存ツールの実行例](../../skills/profile/references/tools.md)を使う。
Rustは[ビルド時間の運用](RUST_BUILD.md)も適用し、キャッシュ保持と実際の配備・復旧時間を確認する。

| 問い | Go | Rust | 保存する証拠 |
|---|---|---|---|
| 整形・静的解析 | gofmt、go vet | cargo fmt、Clippy | [Lint手順](LINT.md)のJSON・生ログ・指摘の対応理由・時間 |
| 契約・回帰・再現 | go test、必要箇所のrace検査 | cargo test、DB統合テスト | SHA・差分、コマンド、成否、時間、生ログ |
| CPU・割当・待ち | pprof、execution trace | perf／flamegraph、利用可能なallocator計測 | profile、ビルド設定、採取区間 |
| 処理区間の関連 | OpenTelemetryと対応するHTTP/DB計装 | tracingと対応するOpenTelemetry連携 | sampling率、静的span名、export先、欠落 |
| HTTP分布・時間 | alp等（言語共通） | 同左 | 実際のログ形式、route正規化、JSON等 |
| SQL負荷 | pt-query-digest、performance_schema、EXPLAIN | 同左 | fingerprint、呼出数、合計時間、実行計画 |

OpenTelemetryは収集・関連付けの仕組み。必要なら既存Collectorや可視化backendを使う。
既存ログやpprofで判断できるならbackend構築を先行させない。SDK／統合crateの対応状況は
使うバージョンで確認し、Go用計装をRustに流用できると扱わない。

実DBのfixtureも既存の仕組みを先に選ぶ。Goなら[Testcontainers for Go](https://golang.testcontainers.org/)、
Rustなら[Testcontainers for Rust](https://rust.testcontainers.org/)や、既にsqlxを使うプロジェクトの
[sqlx::test](https://docs.rs/sqlx/latest/sqlx/attr.test.html)等を検討する。
利用可能なcontainer runtime／接続先、対象と同じDB版、初期化、並行テスト間の隔離を確認する。
導入・起動費用を準備予算へ含め、計測用ホストと資源を競合させない。接続できずskipした
DBテストを合格扱いにせず、純粋関数やSQLiteでの比較だけでMySQLの可視性を証明しない。

## 実行と採否用スコアの分離

1. `--version`、小さな実入力、出力を確認する。導入失敗、空trace、未対応ログ形式は未計測。
   生ログ、ツール名・版・コマンドを保存する。アクセスログに時間がなければ時間分析はできない。
2. 依存／ビルド／設定の変更は通常の候補として統合し、復旧方法を持つ。
   対象環境の変更・採取開始停止は予約所有者がtarget wrapper経由で行う。
3. presetに`OBSERVE_START_CMD`／`OBSERVE_STOP_CMD`と`OBSERVE_TOOLS=otel,pprof`等を設定する。
   `observe start NAME` → reset／bench／dump → `observe stop`。start/stop失敗時はmarkerが残り、
   後続サンプルも観測扱いになる。markerを手で消さず、原因を直してstopを再実行する。
4. STOP_CMDは停止と実状態の確認が成功したときだけ終了0にする。
   ファイル・listener・サービス状態で実際の停止を確認する。全SQLログ・race build・profilerで
   負荷が変わる区間を採否に混ぜない。汎用markerまたはslowlogフラグが有効ならbenchは
   `observed`となり評価から除外される。通常ビルド・同じ条件でbaseline／candidateを測る。
5. 収集済みデータはローカルで既存ツールに渡せる。`OBSERVE_EXTRA_CMD`でdumpへ結果を追加できる。
   標準slowlog parserは簡易集計なので、詳細なSQL分析にはpt-query-digest等も使う。

Goは[計装テンプレート](../../templates/go-observation/README.md)でHTTPとdatabase/sqlを対応付け、
loopback限定pprofを使う。公式SDK・対応するHTTP/SQL計装の検証済み依存を固定し、既存driverと
request contextを保つ。flag削除後の再起動とshutdown/flushで実際に無効化する。
private JSONは`scripts/trace_summary.py`で親子関係・DBのsum/union・欠落を解析できる。
可視化サーバーは必須にしない。Rustは[対応版と実行例](../../skills/profile/references/rust.md)を参照し、
利用中のHTTP・DBライブラリの実計装とmock検証を区別する。Rust stdoutとGo JSONは同じ形式ではない。
認証情報、Cookie、本文、ユーザーID、SQL引数を記録せず、export先は規約で許可された私設経路に限定する。

一次資料: [Go diagnostics](https://go.dev/doc/diagnostics)、[race](https://go.dev/doc/articles/race_detector)、
[cargo test](https://doc.rust-lang.org/cargo/commands/cargo-test.html)、[flamegraph](https://github.com/flamegraph-rs/flamegraph)、
[OTel Go](https://opentelemetry.io/docs/languages/go/)、[OTel Rust](https://opentelemetry.io/docs/languages/rust/)、
[alp](https://github.com/tkuchiki/alp)、[pt-query-digest](https://docs.percona.com/percona-toolkit/pt-query-digest.html)。
