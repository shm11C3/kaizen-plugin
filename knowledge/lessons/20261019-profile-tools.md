# OTelと既存ツールを改善判断へつなぐ（2026-10-19）

[profile Skill](../../skills/profile/SKILL.md)とGo HTTP→SQLテンプレートを作成した。
[機械可読の検証記録](../validation/profile-tools-20261019.json)にコマンド、版、集計、
source/lock hashと未検証範囲を保存した。これはpracticeの汎用Skill改善で、
以下のISUCON14固有の発見はknowledgeに留める。公式ベンチの新スコアは取得していない。

## 実アプリで確認できたこと

ISUCON14 `53f8b627e040c30ebec600457c6c97da008b84b0` を隔離cloneに取り、
Go1.24.4 / MySQL8.0.43をローカルDockerで動かした。元cloneのdirtyファイル、
競技用repo、既存EC2は変更していない。500台の初期chairsのうち8台だけをactiveにし、
実APIでユーザー登録後、nearby-chairsを逐次呼び出した。公式負荷の再現ではない。
HTTP/SQL計装、loopback listen、graceful shutdownと、初期コード由来のslog key/valueの
vet診断修正をこのcloneに加えた。修正前test/vet失敗と修正後成功は別々に記録した。
このアプリには既存Goテストがなく、`go test ./...`成功だけを回帰coverageと呼ばない。

- 全件診断でHTTP171件（登録1、nearby170）、計17007 spansを保存し、全HTTPでDBの
  接続を確認。error/orphanは0。nearbyの94 DB spansはconn/stmt/rowsの重複を含み、
  **94クエリではない**。観測されたDB区間のunionはHTTP時間の中央値77.50%。
- 認証middlewareのSQLはhandler計装より前、既存`Beginx()`もBackground Contextを
  使うため、別root traceになる。orphan0でも全処理のcoverageを証明していない。
  この差を隠すために既存transactionの意味を変更していない。
- 全件診断のCPU profileは5.11秒窓・1.33秒samplesを実`go tool pprof`で解析した。
  macOSのruntime/syscallが上位で、これだけでアプリCPUの改善箇所は断定しない。
  heapのalloc_spaceも解析できたが、JSON/SDK/otelsql自身の割当を含む。
- 別の区切ったslowlogをpt-query-digest3.7.0へ入力した。595 recordsにはPrepare/
  Close等のprotocol操作、登録/startup/metadata probeも入る。HTTP件数と混同しない。
  最新位置検索は48回、Query_time計123.025ms、Rows_examined計1018080。
  EXPLAINは`ALL`、keyなし、`Using filesort`。chair_id/created_at索引は次の仮説に
  できるが、今回は索引を実装・採用していない。HTTP traceとSQL digestは別の負荷窓である。

20リクエスト×3回の壁時計中央値は次のとおり。通常の全SQL slowlogも全区間ONであり、
観測全体の費用ではなく、同条件下での追加OTel計装の差である。

| 起動状態 | 中央値 | trace出力 |
|---|---:|---:|
| flagなし | 840.929ms | 0B、pprof listenerなし |
| 1% root sampling | 858.646ms | 96049B、nearby trace 1件 |
| 100% | 935.322ms | 16668745B（後続profile負荷109件も含む） |

off→1%→100%の固定順、ローカルDocker、少数試行なので、2.1%/11.2%の差を一般的な
OTel overheadや競技得点へ換算しない。1%は少数リクエストでは空でもおかしくない。
全プロセスは正常終了し、listener消失とflush成功を確認。最後にflagなしで実APIを再度実行し、
出力0を確認した。所有するコンテナを削除し、アプリ/pprof/DBの3ポートも閉じた。

## 別fixtureとSkillの確認

- Goの独立fixtureでも実MySQLを使い、HTTP1 + DB4 spansが4/4接続することを確認。
  Contextを切った負例は0/4となる。SQL/args/error/header/TraceStateの秘密markerが
  出ないこと、off、private pprof、起動/bind/export失敗の検出、終了を確認した。
  skipなしPASS。専用moduleのtest/vet/buildも成功。
- Rust1.98.1の小さな実loopback HTTP + **mock DB**で、1000件×3回・親子2000 spans/
  無効時0件を確認。初回release buildは非計装1.090秒/計装5.578秒、warm0.086/0.096秒。
  依存取得後の専用空target/intermediateであり、global cacheは消していない。
  実行中央値は同じ計装binaryのflag off42.175ms/on44.919ms、flush4.126ms。
  fmt/workspace test/Clippy全targetは成功。実Rust競技アプリ・MySQL・OTLP・CPU profileは未検証。
- Rust公式stdoutはconsole text、GoはJSON。Go parserへの流用を避け、対応版/APIと
  Context/async/停止のrecipeをRust referenceへ記載した。Collectorは立てていない。
- alp1.0.22を人工31件のtimed access logで実行し、sum/avg/countで順位が変わることを確認。
  JSONはheader付き2次元配列、再解析は`--nosave-pos`が必要。このfixtureからRPSや得点は出さない。
- 独立担当がSkillを使った1ケースでは、avg最大の1件よりsum最大の経路を調査対象とし、
  別SQL fixtureとの負荷/時刻不一致を検出した。人工fixtureの時刻不整合を修正して隠さず、
  比較不能として扱った。blind精度評価やDiscord/本番協調の実証ではない。

`trace_summary.py`は公式Go JSON stream/arrayを読み、source hashとobservation refを保持する。
DBのsum/union、HTTP内へのclip、orphan、未知coverageを区別し、許可していない名称/属性を落とす。
元trace自体はprivateに保持する。11 testsで並列/入れ子、欠落、秘密marker、nanosecond、
破損/空入力、cycle/重複、元データ上書き拒否を検証。全Python134 tests（70.306秒）、
既存shell E2E（45.277秒）、Skill標準validator、manifest JSON、リンク、diff checkが通過。

## 運用へ反映した判断

調べたい不確実性を1つ決め、既存ログ/pprof/SQLで足りるならそこで止める。
HTTP→DBの所有関係が必要な場合だけ短くOTelを追加する。新しいCollectorや全ツール導入を
参加条件にしない。Context切断、DB span欠落、空profileを0コストと呼ばず、span和から
経過時間/CPUを推定しない。公式採否は観測停止後、通常条件で実ベンチを使う。
汎用Skillには問題固有SQL・今回のホスト配置・閾値を埋め込んでいない。
