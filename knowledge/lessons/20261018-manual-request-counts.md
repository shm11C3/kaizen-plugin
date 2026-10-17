# manual分母取得と比較条件の検証（2026-10-18、0.6.2）

## 変更

- manualの予約時にカウンター値・取得方法・設定hashを保存し、結果登録時に差分を記録する。
  ポータル操作の自動化は追加していない。
- REQUEST_COUNT_CMD、NGINX_HOST、parse_bench_requestsをstable bundleの条件へ追加した。
  条件変更中の予約・結果登録は拒否する。結果登録の拒否時は予約と元カウンターを保持する。
- sampleのrequestSourceに方法・ID・取得ホスト・コマンド／解析関数hash・前後値・状態を保存する。
  明示入力の--requestsは別method。v2／v3とも取得方法の異なるsampleや新旧来歴の混在を再計測へ戻す。
- DESIGN_REVIEWの「必ず警告が出る」「何本取っても判定できない」といった断定と、
  取得・解析の修正だけで採用が保証される表現を、記録と予算に応じた記述へ直した。

## 検証結果

`tests/test_request_counts.py`は一時Git repoとfake remoteを作り、実際のdeploy／capture／
bench --reserve／bench --resultを実行する。通信・特権操作はfixture内に置き換え、実サーバーは使わない。

| ケース | 確認した結果 |
|---|---|
| manualの自動取得 | 予約時100、登録時137を保存し、requests=37、counter-delta／host／availableを記録 |
| カウンターの開始値0 | 0→9をrequests=9として記録。0を取得失敗と混同しない |
| 取得コマンド変更 | 次の予約と予約中の結果登録をtarget config changedで拒否 |
| 取得ホスト変更 | 同上。変更先のカウンター値で元の予約を確定しない |
| 解析関数の変更 | 同上。parser追加も条件変更として検出 |
| 条件を元に戻す | 保持した予約の100を使い、142との差42を正常登録 |
| 自動取得と明示入力の混在 | --requests 200はexplicitとして記録。同じbundleでもv2／v3の両方がinconclusive・remeasure |
| カウンター減少 | 100→4はrequests=null、status=counter-reset |
| 不正な出力 | 12と34の2行を1234へ結合せずrequests=null・unavailable |
| 読取失敗 | 予約時に取得できなければ、登録時150でもrequests=null・unavailable |
| 来歴が一致／欠落 | 一致するsampleは通常判定。来歴つきと来歴なしの混在はv2／v3とも比較不適合 |

53 unit tests、fake-remote通しテスト、shellcheck（error）が成功した。
unit全体の実行時間は17.950秒。実サーバーの権限・ログ形式・競技ポータルでの運用は未検証。

## 運用

0.6.2は条件hashに分母設定を追加するため、旧bundleをそのまま再利用しない。
実験・ポータル予約・復旧待ちのない安定状態で更新し、stable.sh captureと新baselineを実行する。
取得方法を変更するときも同じ。予約中に変更した場合は元へ戻して登録するか、
実行終了を確認してabandonする。失敗した予約やsampleを削除して実行回数をなかったことにしない。

ログ差分は予約から結果登録までの全通信を含む。対象・計数範囲・ローテーション・
別通信の影響を確認する必要があり、整数を得ただけでcheckerのエラーと比較可能とは断定しない。
v3の品質方針や既定ルールは今回変更していない。
