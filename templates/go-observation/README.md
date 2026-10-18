# Go HTTP → SQL observation candidate

`observe.go` と `observe_sql.go` を、独立した観測用 `package main` 候補へコピーする。
公式 OTel SDK / `otelhttp` とコミュニティの `XSAM/otelsql` を利用する。
Collector や OTLP backend は不要。既存の pprof・SQL digest・access log で分かるなら
それらを先に使い、必要な因果関係だけをこの候補で追加観測する。

## 差し込む箇所

起動時に一度だけ初期化し、現在のエラー処理に合わせて失敗を処理する。

```go
observation, err := newKaizenObserver()
if err != nil { return err } // private listener / file の失敗も成功扱いにしない

rawDB, err := observation.Open("mysql", dsn) // 既存の mysql driver import を維持
if err != nil { return err }
db := sqlx.NewDb(rawDB, "mysql") // database/sql を直接使う場合は rawDB のままでよい

router.Handle("GET /api/rides/{id}", observation.Handler(
    "/api/rides/{id}", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        // 実アプリの既存 QueryContext / SelectContext / ExecContext にこの ctx を渡す。
        var count int
        if err := db.GetContext(r.Context(), &count, "SELECT 1"); err != nil {
            http.Error(w, "database error", http.StatusInternalServerError)
            return
        }
        w.WriteHeader(http.StatusNoContent)
    }),
))
```

`router` の API は実際の chi / ServeMux 等に合わせる。`Handler` の route は
登録済みの**静的パターン**で、実 URL・RequestURI・ID を渡さない。
HTTP middleware が渡す Context を SQL の `...Context` / sqlx `...Context` へ伝えると
DB span が HTTP span の子になる。既存 Context の伝達を維持し、計装だけのために
transaction・timeout・cancel の意味を変えない。既存 `Beginx()` 等が Background を
使う場合、begin/commit は root span になり得る。HTTP と結び付かない SQL は
別途 coverage を確認し、全てを欠陥とも検証済みとも扱わない。

HTTP の graceful shutdown でリクエストを drain し、DB を閉じた後に以下を実行する。
signal 処理を用意せずプロセスを強制終了すると、実行中 span は完了できない。

```go
ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
defer cancel()
if err := server.Shutdown(ctx); err != nil { /* 既存の停止方針で扱う */ }
if err := db.Close(); err != nil { /* 記録する */ }
if err := observation.Shutdown(ctx); err != nil { /* export/flush失敗として扱う */ }
```

観測区間を取得した後の `observation.Flush(ctx)` も error を確認する。
`Enabled()` と `ProfileAddress()` は起動確認用で、非空 trace・実 profile・必要な親子 span の
確認の代わりにはならない。Shutdown は複数回呼んでも同じ結果を返す。

## 起動・停止と private 出力

flag はプロセス起動時に一度読む。flag 作成/削除と restart を許可済みの
`OBSERVE_START_CMD` / `OBSERVE_STOP_CMD` に組み込み、共有 target の所有者が既存の
`target ... observe start/stop` を使う。設定・service・アプリを直接変更する代替手順ではない。

| 環境変数 | 既定値 |
|---|---|
| `KAIZEN_OBSERVE_FLAG` | `/var/tmp/kaizen-observation-enabled` |
| `KAIZEN_TRACE_FILE` | `/var/tmp/kaizen-observation-traces.jsonl` |
| `KAIZEN_TRACE_RATIO` | `0.01`（新しい root の1%。childは親のsampling判断を継承） |
| `KAIZEN_PPROF_ADDR` | `127.0.0.1:6060`（literal loopback IPのみ。fixtureはport0も可） |

flag が無ければ元の HTTP handler と `sql.Open` を使い、SDK/provider・trace file・
profile listener を作らない。公開 router や `http.DefaultServeMux` は変更しない。
flag があるのに sink / bind / sampling 設定が不正なら初期化を error にする。
既存ファイルも0600にし、symlink/deviceを sink に使わない。

private listener は `runtime/pprof` の標準データを返す小さな adapter。
`net/http/pprof` の import 時に公開 DefaultServeMux へ handler を登録する副作用を避ける。

```bash
# 許可済み観測中に、そのホストから取得する。これらはCollectorを必要としない。
curl --fail 'http://127.0.0.1:6060/debug/pprof/profile?seconds=5' -o cpu.pprof
go tool pprof -top ./application cpu.pprof
curl --fail 'http://127.0.0.1:6060/debug/pprof/heap' -o heap.pprof
go tool pprof -top ./application heap.pprof
```

CPU profile は1〜30秒。heap / allocs / goroutine / block / mutex / threadcreate の
標準 protobuf profile と、`/debug/pprof/` の種類一覧を提供する。
mutex/block の計測 rate はこのテンプレートでは変更しない。execution trace / symbol の
HTTP endpoint は提供しない。profile と raw trace は private artifact として扱う。

停止時は flag 削除だけで完了とせず restart・listener消失・正常系疎通・export停止を確認する。
観測中の標本は既存 observe state で observed として記録し、採用得点に使わない。
同期 sampled file export にも費用がある。通常比較は観測停止後に条件を揃えて行い、
最終候補では不要な計装依存を取り除くことも選べる。

## 出す情報と出さない情報

公式 `stdouttrace` JSON stream の TraceID / SpanID / Parent と StartTime / EndTime を維持する。
HTTP span 名は method と宣言した route、SQL span 名は otelsql の固定 method。
保存する属性は `http.request.method` / `http.response.status_code` / `http.route` /
`db.system.name` / `db.operation.name` のみ。SQL operation は SELECT 等の固定集合へ分類する。
SQL本文・args・URL・query string・header・User-Agent・業務IDは書き出さない。
例外 event・error description・links・header由来TraceStateも保存せず、resource は固定名にする。
エラー状態の code は残るが詳細な SQL error の診断は既存の private tool と併用する。

SDK 内の export error を記録して Flush / Shutdown へ返す。
「HTTP spanだけ」「空file」「wrong parent」「flush error」を観測成功と記録しない。
少数リクエストを1%で実行して空になる場合は、時間・sampling ratioを調整した
診断区間で実際の出力を確認し、ratioを根拠とともに残す。100%の結果を1%の費用と混同しない。

## 実行確認した依存版

Go1.24.4 darwin/arm64 で次の組合せを compile / test / vet / build した。
アプリの go.mod / go.sum は上書きせず、観測候補で互換性を確認して両方を commit する。
新しい版・別toolchainも同じとは断定しない。

```bash
go get github.com/XSAM/otelsql@v0.34.0 \
  go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@v0.56.0 \
  go.opentelemetry.io/otel@v1.31.0 \
  go.opentelemetry.io/otel/sdk@v1.31.0 \
  go.opentelemetry.io/otel/exporters/stdout/stdouttrace@v1.31.0
```

fixtureの実DB driverは `github.com/go-sql-driver/mysql v1.8.1`、MySQL8.0.43。
HTTP→DB親子 span、Context を切った負例、SQL/args/error/header/ID の秘匿、offの無出力、
private profile・起動失敗・flush失敗・Shutdown後のlistener消失を実行確認した。
これは計装の機能確認で、アプリ得点や競技環境の構成を再現した主張ではない。

旧 `kaizenObserve(handler)` だけのテンプレートからは、**両ファイル**へ置き換え、
起動時 `newKaizenObserver`・DB `Open`・route別 `Handler`・終了時 `Shutdown` を差し込む。
旧 API を残したまま HTTP だけを計装して SQL も取れたとは扱わない。

一次資料: [otelhttp](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@v0.56.0)、
[otelsql](https://github.com/XSAM/otelsql/tree/v0.34.0)、
[OTel SDK](https://pkg.go.dev/go.opentelemetry.io/otel/sdk/trace@v1.31.0)、
[runtime/pprof](https://pkg.go.dev/runtime/pprof)。
