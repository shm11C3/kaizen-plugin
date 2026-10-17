# 2026-10-17 実機運転の結果と次の改善案

`scripts/knowledge.sh report` の出力が一次情報です（`knowledge/records/`）。

## 測れたこと

| 問題 | 実験 | promote | スコア（最初の baseline 中央値 → 最後の promote） | 最初の promote まで |
|---|---|---|---|---|
| ISUCON14 | 7 | 2 | 2527 → 8650 | 13 分 |
| ISUCON13 | 3 | 3 | 3733 → 9109 | 5 分 |
| ISUCON12 予選 | 1 | 0 | 2064 → （判定不能） | — |

- 1 実験の実時間は 3〜9 分（deploy 4〜10 秒、ベンチ 68〜106 秒 × 2〜3 本）。
- ISUCON14 の stable 75a8032 では同一コードで 5 本 5369〜9538（±27%）。この幅では n=2 の判定は成立せず、006/007 の reject/inconclusive は判定ではなくノイズの範囲。
- ISUCON12 は AMI 初回起動の unattended-upgrades が mysql と docker CLI を差し替え、baseline と candidate の両方を汚染した。plugin に `BENCH_PRECHECK_CMD` と `stable.sh forget-baseline` を追加して対処したが、再計測は未実施。
- hold-out 比較（13 を未知問題として「ナレッジあり / なし」）は、コーパスの計測行が 11 件では成立しないため未実施。13 の 3 実験は 14 で計測した順序（index → 静的/キャッシュ）をそのまま使って全て promote したが、これは比較ではなく一例。

## plugin が実機で学んだこと（retro/log.md、26 件）

rsync の itemize（`<f`）、/etc の所有者、nginx ログの引用符、記録ファイルと git の衝突、cwd 依存、SIGPIPE、docker CLI の差し替え、prepared statement が performance_schema に出ない（slow log 経由の観測と「観測中のサンプルは判定に使わない」）、ベンチ出力と result.json の混線。どれも偽リモートのテストでは出ず、実機 1 周目で出た。

## 次の改善案（優先順）

1. **計画を先に立てる**（実装済み: `knowledge.sh plan` / plan skill / Stop hook）。006/007 は「DB は軽くなったがスコア経路外」で、計画段階でマニュアルの採点方式を見ていれば飛ばせた。plan.md の「scoring path?」欄を埋めるまで experiment を開かない運用にする。
2. **ノイズを先に測り、n を幅から決める**。`bench.sh baseline` を 3 本取って相対幅を出し、`MIN_IMPROVEMENT_BP` と最小サンプル数を自動で提案する（幅 ±27% なら「n≥4 か、効果が 2 倍以上の仮説だけ」）。評価ルールはそのまま、入力の作り方を変える。
3. **ホストの衛生を前提条件にする**。初回起動の unattended-upgrades を setup で無効化または完了待ちし、サンプルごとにホストの load と稼働中パッケージ処理を記録する（12 で全数値が無効になった）。
4. **観測の盲点を埋める**。prepared statement（slow log 経由）と SQLite（アプリ側トレース）を signature が読めるようにし、エンドポイント別レイテンシ表からも候補を出す（12 では既存ルールが 1 つも発火しなかった）。
5. **分散減らし**。ISUCON14 ではマッチングを決定的にしてから再計測する（plan.md に記載）。
6. **hold-out 測定の実施条件**。各問題 10 件以上の計測行が揃ったら、13 を hold-out にして「ナレッジあり / なし」で最初の promote までの時間と固定時間後のスコアを比較する。それまでコーパスは費用。

## 環境

EC2 8 台（isu1〜3, isubench, isu13, isu13bench, isu12, isu12bench）が稼働中。stable: isu1=75a8032（isuride-practice）、isu13=ebb3824（isucon13-practice）、isu12=4be57e2（isucon12-practice）。
