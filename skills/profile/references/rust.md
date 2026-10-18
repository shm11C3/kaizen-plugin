# Rust: tracing、OpenTelemetryとCPU観測

既存のログ・tracing・profilerを先に確認する。Rustアプリ全体の移植やCollector構築を
観測の前提にしない。導入費用には依存取得、compile/link、通常版への復旧も含める。
既存テスト・formatter/Lint一式は基本として実行し、重い検査だけ実測から調整する。
新しいcoverageや独立レビューを作る費用とは分ける。

## 互換性を確認して短い経路を作る

既にtracingがあれば、対応する`tracing-opentelemetry`のlayerを使う。
crateの版番号は同期していないので、Cargo.lockと依存宣言を照合する。
今回確認した組合せはAPI/SDK `=0.33.1`、`tracing-opentelemetry =0.34.0`、
stdout exporter `=0.33.0`、tracing `=0.1.44`、subscriber `=0.3.23`。
既存アプリへこの組合せを無条件に上書きしない。
[対応依存](https://docs.rs/crate/tracing-opentelemetry/0.34.0)と
[layerのAPI](https://docs.rs/tracing-opentelemetry/0.34.0/tracing_opentelemetry/)を確認する。

providerはプロセス寿命で保持し、起動時の明示flagが無効ならprovider/exporter/layerを
作らない。既存のapplication log subscriberまで無効にしない。
SDK初期化をrequestごとに行わず、動作確認は少数リクエストから始める。
同期scopeでの基本形は次のとおり（エラーは呼び出し側へ返す）。

```rust
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_sdk::trace::SdkTracerProvider;
use tracing_subscriber::layer::SubscriberExt;

let provider = SdkTracerProvider::builder()
    .with_batch_exporter(opentelemetry_stdout::SpanExporter::default())
    .build();
let subscriber = tracing_subscriber::registry()
    .with(tracing_opentelemetry::layer().with_tracer(provider.tracer("app")));
tracing::subscriber::with_default(subscriber, || {
    let request = tracing::info_span!("HTTP GET /route", otel.kind = "server");
    let _entered = request.enter();
    let query = tracing::info_span!("db.operation", otel.kind = "client");
    let _query_entered = query.enter();
    // この同期scopeで実処理を行う。
});
provider.force_flush()?;
provider.shutdown_with_timeout(std::time::Duration::from_secs(3))?;
```

これは同期scopeの形であり、別thread/taskへsubscriberやcontextが自動伝播する証明ではない。
async処理ではenter guardを`.await`を越えて保持せず、futureの`.instrument(span)`等を使う。
既存のsubscriber/dispatcher・middlewareへ組み込み、実際のhandler→DB呼出しで親子関係を確認する。
[tracingのasync注意事項](https://docs.rs/tracing/latest/tracing/struct.Span.html#in-asynchronous-code)
と[context連携API](https://docs.rs/tracing-opentelemetry/0.34.0/tracing_opentelemetry/trait.OpenTelemetrySpanExt.html)を参照する。
同一プロセス内の親子span成功を、HTTP越しの伝播や実DB計装の成功と呼ばない。

## 出力、終了、無効化を確認する

- 少数リクエストで、routeのrootとDB等のchildが同じTraceIdを持ち、childのParentSpanIdが
  rootのSpanIdを指すこと、時刻と件数が妥当なことを確認する。
- 静的route/操作名を使い、URL query、本文、Cookie、認証情報、SQL引数や個人IDを記録しない。
  `#[instrument]`を使う場合も、引数の自動記録がこの条件を満たすか確認する。
- in-flight処理とspanの終了後にflush/shutdownを行い、成功・timeout・残った件数を記録する。
  起動時に保持したproviderから終了し、requestごとのflushや存在しない旧global shutdown APIを使わない。
  [provider終了API](https://docs.rs/opentelemetry_sdk/0.33.1/opentelemetry_sdk/trace/struct.SdkTracerProvider.html)に従う。
- flag無効で再起動し、同じリクエストでspan出力・export用worker/接続が残らないことを確認する。
  exporterの宛先を消しただけ、samplerを変えただけで通常状態へ戻ったとは判断しない。
  実装固有のflagと無効化確認方法を候補に残す。

公式[stdout exporter](https://docs.rs/opentelemetry-stdout/0.33.0/opentelemetry_stdout/struct.SpanExporter.html)の
出力はRust向けのconsole textであり、Go stdout exporterのJSONやOTLP JSONとは別形式。
無理にGo用parserへ入力しない。rawを保持し、既存の対応exporter/backendがあればその形式を使う。
console出力だけではOTLP転送・Collector受信・可視化の成功は未検証である。

## 費用と採否用計測を分ける

同じsource・負荷・通常profileで、flag無効/有効/無効へ戻した状態のwall time、CPU、
出力量、drop、flush費用を比べる。stdout I/O込みの負荷をOTLP exporter全般の負荷率へ
一般化しない。spanのwall durationはCPU時間ではなく、待ち時間も含む。
親子のinclusive durationを足してrequest時間にしない。
診断ビルド・収集中のsampleは観測扱いにし、無効化を確認した通常状態で採否を測る。

buildは依存取得、空の専用targetでの初回compile、warm無変更、実変更後を区別する。
Cargo.lock、toolchain、features、profile、RUSTFLAGS、RUSTC_WRAPPER、target/build-dirを記録し、
共有cacheを消さずに測る。[Cargo cacheの範囲](https://doc.rust-lang.org/cargo/reference/build-cache.html)を確認する。
既存設定に合わせて`cargo test --workspace`、`cargo fmt --all -- --check`、
`cargo clippy --workspace --all-targets`を実行し、恣意的なall-featuresは足さない。
check/buildのcompile重複も総費用へ含める。

## CPU profileが必要なとき

spanで待ちと処理区間を絞れない、またはCPU上限が観測された場合は既存profilerを使う。
[cargo-flamegraphの一次資料](https://github.com/flamegraph-rs/flamegraph)ではLinuxにperf、
macOSにxctraceが必要。対象OS・kernelとperfの対応、権限、symbol/unwind情報を先に確認する。
権限不足を理由にシステム全体のperf設定を自動変更しない。
release用のsymbol/debug情報追加がbuild・配備・復旧費用を変える点も記録する。
ツールの存在確認と、対象プロセスから有効なstack/profileを得た実証は区別する。
未導入・未実行なら未検証とし、導入を全候補の待ち条件にしない。
