# 安定版bundleと資源の復旧

0.3.0ではGit SHA、配備tree、target設定hash、宣言した資源のfingerprintを `.kaizen/stable-bundle.json` に保存する。計測にはこのbundle IDと計測終了時の資源fingerprintを記録する。設定を変えた場合は安定状態でcaptureし直し、異なる条件のbaselineを退避して測り直す。repinは資源が一致する場合だけrevisionを更新する。

bundle の `configHash` は計測条件（ホスト、配備・復旧・ベンチのコマンド）の解決済みの値から計算する。予算・閾値・観測設定・plugin の版は含めない。plugin を競技中に更新しても bundle は保たれ、どの plugin 版で計測したかは bundle と各サンプルの `pluginRevision` に残る。

分母の取得方法も計測条件。`REQUEST_COUNT_CMD`・`NGINX_HOST`・`parse_bench_requests`を変えたら
安定状態でcaptureし直し、新しいbaselineを取る。0.6.2ではこれらをhashに追加したため、既存bundleも
再captureが必要。実験・ポータル予約・復旧待ちのない安定状態で更新する。予約中は条件を変えない。
各sampleの`requestSource.id`も比較し、自動取得／明示入力の混在や新旧の来歴欠落を再計測へ戻す。
旧記録同士の再生は引き続き可能だが、新しい来歴つきsampleとの混在はしない。

## 初期設定

当日マニュアルと対象環境に合う次の設定を、統合用cloneのconfig.shへ書く。

```bash
RESOURCE_HOSTS="$DB_HOST"             # 復旧・検証が必要なホスト
RESOURCE_PATHS="sql etc migrations"   # 変更時にcode-only復旧を拒否するソース領域
RESOURCE_FINGERPRINT_CMD='対象のschema・index・設定を決定的な順序で出力するread-onlyコマンド'
RECOVERY_CMD='安定版から対象の資源を復旧する、確認済みのコマンド'
```

2つのCMDはセットで設定する。pluginはfingerprintの出力をhash化し、内容そのものはbundleへ保存しない。時刻・件数・AUTO_INCREMENT等、通常のベンチで変わる値を混ぜない。probeの失敗は空の資源として採用せず停止する。設定へ秘密情報を書かない。

ISUCON14のindex確認なら `information_schema.STATISTICS` のtable/index名・unique・column順を安定順で出す。column変更や外部設定も対象ならそれらも含める。pluginは検証コマンドの対象範囲が十分かまでは推定できない。`changedResources`に書いた全資源をカバーする復旧ドリルが必要。

DB初期化や元dumpのrestoreは対象ごとに意味が違う。競技マニュアルと人間の許可範囲を確認してRECOVERY_CMDを準備する。元データの保存が必要なら、変更前のバックアップと復元後の内容比較を先に用意する。pluginが無条件にDBを初期化する設定は同梱しない。

```bash
# setup時、安定コードと資源を初期状態へ揃えた後
"$K/scripts/deploy.sh" main
"$K/scripts/stable.sh" capture
"$K/scripts/recover.sh"
"$K/scripts/bench.sh" baseline
"$K/scripts/bench.sh" baseline-2
```

チームでは占有下のtarget deploy/stable/recover/benchを使う。初回有効化前のドリルはRUNBOOKのsetup手順で行う。

## 候補と復旧

manifestの`changedResources`にdatabase/configuration/data/external等の変更資源を記す。SQL・overlay・RESOURCE_PATHSの差分、またはchangedResourcesがある候補は、復旧コマンド未設定ならdeployを拒否する。

`recover.sh`は同じ配備lockの下で安定コードの配備→RECOVERY_CMD→ファイルと資源の一致確認を行う。全て成功して初めてhealthy/revert状態を回復する。安定SHAを再配備しただけのbaselineも、資源が異なれば拒否する。復旧失敗をcaptureし直して安定と扱ってはいけない。

0.2.0の既存baselineにはbundle IDがないため、0.3.0では判定に再利用しない。初期ドリル・capture・新baselineから再開する。
