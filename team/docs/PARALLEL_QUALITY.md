# 並列検証と品質保留からの再計測

## 共通台帳、環境ごとの占有

タスクは共通ホストの**１つのSQLite**で管理し、`competition`とsandboxごとに
占有・実行ロック・ポータル待ちを分ける。公式の統合・採否は`competition`だけ。
別のDBを作るのはチーム全体を分けるリハーサル用で、並列レーン用にはしない。

各環境に別のproject、knowledge_dir、アプリ、DB、初期データ、モック、負荷生成CPU、
ログと設定を用意する。公式系からsandboxへ処理が流れないようにする。
同一のベンチホストを別名で登録しても独立にはならない。
レーンの構築・同期・再測定に費やす時間と、キュー待ちの削減を比較し、
利益が小さければ１レーンへ戻す。最初は独立したsandboxを２つまででよい。

`target.json`には既存の設定に次を加える。`resources`は、SSH別名ではなく
AWSアカウント・region・instance IDなどから作った同一性を比較できるIDを使う。
DBやモックを共用する場合、その実体のIDも含める。projectとknowledgeの絶対パスは
登録時に自動追加される。

```json
{
  "environment": "lane-a",
  "resources": [
    "aws:ACCOUNT:REGION:i-APP",
    "aws:ACCOUNT:REGION:i-DB-MOCK",
    "aws:ACCOUNT:REGION:i-BENCH"
  ]
}
```

全環境を解放した状態で、先に`competition`、次に各sandboxを共通ホストへ登録する。
以下の`K`は共通ホストの固定したpluginリリース。設定は同じホストに置く。

```bash
python3 "$K/scripts/team/team.py" --db /srv/isucon/state/team.sqlite3 \
  env-register --agent setup --config /srv/isucon/state/target.json \
  --reason '公式資源の一覧、規約と復旧確認への参照'
python3 "$K/scripts/team/team.py" --db /srv/isucon/state/team.sqlite3 --environment lane-a \
  env-register --agent setup --config /srv/isucon/state/lane-a.json \
  --reason '資源・ネットワーク・登録先の分離を確認した証拠'
```

資源IDの重複は拒否される。登録後のtarget.jsonまたはprojectのconfig.sh変更も
操作時に拒否されるため、対象や設定を変える場合は全環境を解放して再登録する。
これは**申告された資源一覧とファイルの結び付け**であり、AWSやネットワークの
実体を自動発見して完全な分離を証明するものではない。登録者が実構成と照合する。
設定からさらに別ファイルを読み込む場合も、その依存先と資源を確認する。

各PCのレーン用host-configには、同じ`instance_id`、`remote_plugin_root`、
**同じ`state_db`**と、別の`target_config`、`environment: "lane-a"`を指定する。
`control.py --host-config /path/lane-a-control.json env-acquire ...`でその環境だけを占有する。
target操作も同じhost-configを使う。各レーンは基準版と候補をそれぞれ測り、
候補の選別結果を共有する。有望な変更は現在の公式stableへ取り込み、公式で再計測する。
sandboxの結果だけで`task-finish ACCEPTED`にすることはできない。

`competition`の従来の占有・ロック名は互換性のため維持する。ただし機能の混在を
避け、全メンバーと共通ホストを同じリリースに揃えてから並列機能を有効にする。

## 品質保留は修正可能な候補として残す

スコア改善があっても品質が未確認なら採用しない。失敗した走行を復旧し、
実装候補は原因を調べて直せるように残す。次を分ける。

| 分類 | 次の作業 |
|---|---|
| correctness | 失敗条件を再現し、仕様・整合性を修正する。失敗した版は採用しない |
| warning / timeout | エラー種別、発生タイミング、件数と分母、関連遅延を調べる |
| conditions | DB初期状態・配備・観測設定・共有負荷等の混入を解消する |
| unknown | 不足する証拠を取得する。未計測をゼロや成功に置き換えない |

品質の問題は`task-quality-hold`で元base/source SHAと証拠を固定する。
以下は共通ホストの例。各PCでは同じ引数を`control.py`へ渡す。

```bash
python3 "$K/scripts/team/team.py" --db /srv/isucon/state/team.sqlite3 \
  task-quality-hold --id T-0001 --agent INTEGRATOR --token TOKEN \
  --category warning --evidence '/srv/isucon/artifacts/E-01/bench.log:CODE26' \
  --reason '速度改善あり。分母不明、反映時刻とcommit可視性を調べる'
python3 "$K/scripts/team/team.py" --db /srv/isucon/state/team.sqlite3 \
  task-resume --id T-0001 --agent ORIGINAL_WORKER --reason '原因調査と修正を開始'
# 調査・局所再現・修正・検証後、通常のtask-readyで修正版SHAを提出する。
```

レーンで見つけた品質問題もその環境のowner/tokenで登録できる。タスクの担当は維持し、
必要なら明示的にhandoffする。`status`に保留の分類・元SHA・修正版・状態が表示される。
仮説、反証、修正案、残り時間と計測枠を記録し、同じ失敗を根拠なく繰り返さない。
修復の見込みが低い、利益が小さい、残り時間に合わない場合は理由付きで中断する。
同一内容・同じ条件の警告は、実験を作り直しただけでは解消しない。
cherry-pickで統合SHAが変わっても、同じworker sourceや同一のアプリtreeに残る警告を引き継ぐ。ソースを変えず
再測定する場合は新たな原因証拠・修正した条件・説明を区別できる測定を示す。
クリーンな2回が得られるまでの引き直しを解消として扱わず、未解明の過去警告も採否に含める。
現在のスコア評価器は実験単位であり、別実験の同一内容を横断する強制判定は行わない。
この履歴確認と専用保留の登録は統合担当が行う。

修正版の提出で`OPEN → RETEST_PENDING`となるが、解消扱いにはしない。
再計測で失敗すれば新たな保留にその結果を追加し、再び調査する。
解消には公式環境の採用記録を使う。

```bash
python3 "$K/scripts/team/team.py" --db /srv/isucon/state/team.sqlite3 \
  task-finish --id T-0001 --agent INTEGRATOR --result ACCEPTED \
  --record /srv/isucon/repo/.kaizen/experiments/002-retest/record.json \
  --tested-sha FULL_INTEGRATED_SHA --reason '元の品質問題を修正し公式で採用'
```

共通ホストに登録した公式project内の記録で、修正版提出後に閉じられ、品質pass、
promote、candidate/stable-after/サンプルのSHA一致を確認できた場合だけ`RESOLVED`になる。
元source、修正source、実測した統合SHAは別々に残す。実験記録のdigestも保存する。
sourceをcherry-pickした統合版に修正が含まれることは統合担当が確認する。
台帳はコードの意味や記録の偽造まで検証する仕組みではない。
人間判断対象は従来どおり実際の判断参照を両方の記録に残す。

不採用なら保留は`ABANDONED`となり、修正成功として数えない。最終計測で再発した
問題は採用済みタスクを巻き戻さず、`task-create --related T-0001 --kind investigation`
で新しい調査へつなげる。公式PASSとpluginの追加品質確認も別々に報告する。

## 検証範囲

ローカルの独立した子プロセスで並列実行、同一環境の排他、共通タスク取得、
資源重複・設定変更の拒否、ポータル待ち、保留→修正→再計測の履歴を検証する。
このテストだけでは複数EC2の計測条件・ネットワーク分離・時間短縮は実証できない。
実機ではレーンごとのbaseline、初期状態、環境差、再確認コストを別途測る。
