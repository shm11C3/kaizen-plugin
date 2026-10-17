# 並列検証と品質保留からの再計測

## EC2レーンの準備と停止

`scripts/team/ec2_lanes.py`はAWS CLIとPython標準ライブラリだけで、独立したapp＋benchの
起動・再利用・状態取得・停止を行う。[設定例](../templates/ec2-lanes.example.json)を作業領域へ
コピーし、expected account、region、一意なstudy、公式・共通ホストの除外ID、各レーンの
既存IDまたはlaunchを記入する。秘密鍵は設定へ入れず、既存SSH設定から参照する。
AMIのroot deviceに合わせ、全EBSマッピングを暗号化する。新規起動ではIMDSv2を必須にし、
study/lane/roleタグと固定client tokenを付ける。同じstudy/config/stateをリトライで使い、
新規起動の応答が失われてもstateを消さない。

```bash
python3 "$K/scripts/team/ec2_lanes.py" --config /path/ec2-lanes.json \
  --state /path/ec2-lanes-state.json plan
python3 "$K/scripts/team/ec2_lanes.py" --config /path/ec2-lanes.json \
  --state /path/ec2-lanes-state.json --db /srv/isucon/state/team.sqlite3 \
  --output /path/ec2-inventory.json ensure
python3 "$K/scripts/team/ec2_lanes.py" --config /path/ec2-lanes.json \
  --state /path/ec2-lanes-state.json status
```

準備と停止は全環境の占有を解放し、実験を閉じ、実行プロセス・portal予約・復旧待ちがない
境界で行う。CLIは共通台帳と操作ロック、登録projectの状態を確認する。台帳に未登録の
プロセスや外部実行の終了までは証明しない。初回準備にも当日利用する共通DBを指定する。
`ensure`はEC2の起動要求までで、status check、SSH疎通、サービス、初期データ、名前解決、
DB・モック・負荷生成の分離は別途確認する。AMIが不要なアプリやDBも自動起動する場合は
設定したdeploy/recovery手順で整える。SSH IPはstop/startで変わるため出力と照合する。

1. 起動して疎通・分離・復旧を確認し、レーンごとに別clone/config/knowledgeを用意する。
2. 以下の共通台帳へ公式、各レーンの順で登録する。出力の`resource`を資源一覧へ使う。
3. 各レーンを占有し、`target.py --environment lane-a`等でdeploy/benchを同時に進める。
   同じ環境は既存ロックで直列化する。各レーンでbaselineを取り、公式で採用前に再測定する。
4. 最終の復旧・記録・プロセス終了を確認し、全環境を解放して`stop`する。

```bash
python3 "$K/scripts/team/ec2_lanes.py" --config /path/ec2-lanes.json \
  --state /path/ec2-lanes-state.json --db /srv/isucon/state/team.sqlite3 stop
```

停止対象はstateに今回の起動・作成を記録したインスタンスだけ。元からrunningの既存機は
停止しない。新規機も停止までで、EBS料金は残る。証拠を回収して不要になった新規機の
terminateは別途管理する。公式機の停止やSG/IAM/VPC変更はこのCLIの役割に含めない。

CLI導入前に今回のstudy用として起動済みなら、初回ensureだけ`--import-startup /path/startup.json`
で明示的に取り込める。JSONは`{"study":"...","account":"...","instances":{"i-...":
{"original_state":"stopped","evidence":"起動前describeとstart API記録のパス"}}}`とし、新規作成なら
`original_state: "absent"`を使う。申告は利用者が元のAPI記録と照合する。既存stateの
running判定を後から書き換える用途には使えず、除外IDや設定外IDの取り込みは拒否する。

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

### 公式の採用が進んだらsandbox stableを同期する

初期stableを残したまま候補を比較すると、公式で採用済みの改善を含まない古い条件になる。
`initialize`の再実行や、内容が異なるSHAへの`repin`、stateの直接編集、架空のpromoteで
追い付かせない。sandboxの実験を閉じて復旧し、所有権を取得した操作ロック内で同期する。
先に対象projectへ公式stableのGit objectをfetchする。workerのcloneは操作しない。

```bash
python3 "$K/scripts/team/target.py" --db /path/team.sqlite3 --config /path/lane-a.json \
  --environment lane-a --agent MEMBER --token TOKEN \
  stable-sync --record /path/competition/.kaizen/experiments/NNN-adoption/record.json
# 成功後は同じ所有環境で、新しいbaselineを取得する。
```

受理する根拠は、共通台帳へ登録済みのcompetition project内の実promote記録だけ。
record・manifest・decision・実sampleの内容、品質pass、candidate/stable SHA、比較bundleと
source objectを読み取り照合する。評価器の再実行や公式側の変更はしない。
公式の操作ロックは証拠の読取時だけ取得し、sandboxへのdeploy中には保持しない。
公式stableが記録後のmetadata commitへ進んだ場合も、配備対象treeの一致を確認する。
別の改善が含まれる場合は、その新しい採用記録を指定する。

同期先のmainはfast-forwardだけ。sandbox独自のstableと分岐した場合は拒否するため、
未統合候補を別branchへ保持した上で、内容と依存を調整する。新しい公式SHAの配備・
設定したresource初期化・bundle再capture・復旧drill・ファイルとhealthの確認が完了してから
mainを確定する。旧stable/bundleと公式記録のdigest、段階、時間、復旧ログは
`.kaizen/stable-syncs/`へ残す。これはsandbox独自の採用件数には数えない。

旧・同期先SHAの既存baselineはretireし、公式や他レーンのsampleを基準値へコピーしない。
同期したレーンで新baselineを取ってから候補を比較する。
同一SHAですでにhealthyなstableなら、bundle・ファイル・healthを確認するだけでbaselineを保持する。
resource初期化は行わず、`verified-unchanged`の履歴を残す。

失敗時は旧bundleと旧stableで自動復旧する。復旧を確認できなければpendingを保持し、
bench/deploy/新実験等を拒否する。履歴とrollback.logを調べ、原因を解消してから次を実行する。
stateやpendingファイルを手で消して先へ進めない。自動復旧後もretireしたbaselineは再利用しない。

```bash
python3 "$K/scripts/team/target.py" --db /path/team.sqlite3 --config /path/lane-a.json \
  --environment lane-a --agent MEMBER --token TOKEN stable-sync --rollback
```

実DBでの再現・修復テストも、所有レーンの`target.py check-remote`で実行する。
deploy/benchと同じ操作ロックを保持し、他の環境のappには転送しない。
[Go実DBテスト手順](PHASES.md#実dbを使うgoテスト)に従い、隔離schemaを守るfixtureと
明示したsource/include/envを使う。失敗した再現版と修正版の記録を両方残し、
再現失敗を期待どおりという理由でpassedに書き換えない。

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
スコア評価器は実験単位のまま維持する。競技用`target.py experiment record`入口は、
共有台帳の`OPEN / RETEST_PENDING`をtask IDに関係なく確認する。元sourceがGit祖先、
同じ配備対象tree、またはbaseからの変更blobを保持する候補には保留を引き継ぐ。
未修復なら公式promoteを拒否する。独立したstableベースの候補は妨げない。
保留中の候補を採用せず閉じて復旧する場合は、明示的に
`record --override inconclusive <reason>`または`--override reject`を使う。
省略時はpromoteの可能性を保守的に扱う。sandboxの明示inconclusiveも実行できる。

修正版の提出で`OPEN → RETEST_PENDING`となるが、解消扱いにはしない。
再計測で失敗すれば新たな保留にその結果を追加し、再び調査する。
解消には公式環境の採用記録を使う。保留のない候補も含め、すべての`ACCEPTED`で
`--record`と`--tested-sha`を指定する。

```bash
python3 "$K/scripts/team/team.py" --db /srv/isucon/state/team.sqlite3 \
  task-finish --id T-0001 --agent INTEGRATOR --result ACCEPTED \
  --record /srv/isucon/repo/.kaizen/experiments/002-retest/record.json \
  --tested-sha FULL_INTEGRATED_SHA --reason '元の品質問題を修正し公式で採用'
```

共通ホストに登録した公式project内の記録で、修正版提出後に閉じられ、品質pass、
promote、candidate/stable-after/サンプルのSHA一致と、修正版提出後のcandidate sampleを
確認できた場合だけ`RESOLVED`になる。別taskの候補が修復を含む場合も、該当する
`RETEST_PENDING`をこの公式記録で解消できる。
元source、修正source、実測した統合SHAは別々に残す。実験記録のdigestも保存する。
配備対象はcaptured stable bundleの`trees`に従い、Git objectを取得して照合する。
提出sourceと実測版が同じ配備対象内容ならSHAが違ってもよい。それ以外はbaseから
提出sourceへ変更したpathのblob・削除・modeが実測版に残ることを確認する。
重複しないcherry-pickは受理し、提出修正を単純revertした子孫は拒否する。
同じfileへ別の変更を重ねて一致しなくなった場合は、内容を確認した担当が元taskを
resumeし、実際の統合SHAを`task-ready`で再提出してから測る。
未解消保留の修復も同じblob条件で確認し、同一内容のclean sample引き直しを修復としない
（計測条件の保留`conditions`は同じsourceで条件を直し再計測できる）。
source包含の確認はコードの意味や記録の偽造まで証明する仕組みではない。
人間判断対象は従来どおり実際の判断参照を両方の記録に残す。

不採用なら保留は`ABANDONED`となり、修正成功として数えない。最終計測で再発した
問題は採用済みタスクを巻き戻さず、`task-create --related T-0001 --kind investigation`
で新しい調査へつなげる。公式PASSとpluginの追加品質確認も別々に報告する。
`RESOLVED / ABANDONED`はこの自動継承ガードの対象外で、履歴を保持してAIが確認する。
修復採用後に同じSQL fileへ別の索引を足す通常改善を永久に拒否しないため、閉じた
保留を自動で再開するworkflowは追加しない。過去の不具合を再導入する任意の書換え、
一部だけのcherry-pick、意味が同じ別実装まで自動検出できない。再発を観測したら
新しい調査・保留と回帰テストを作る。

## 検証範囲

ローカルの独立した子プロセスで並列実行、同一環境の排他、共通タスク取得、
資源重複・設定変更の拒否、ポータル待ち、保留→修正→再計測の履歴を検証する。
このテストだけでは複数EC2の計測条件・ネットワーク分離・時間短縮は実証できない。
実機ではレーンごとのbaseline、初期状態、環境差、再確認コストを別途測る。
