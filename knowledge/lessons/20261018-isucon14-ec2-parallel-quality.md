# ISUCON14：実EC2並列検証と品質保留からの修復

- モード：practice。ISUCON14のGo/MySQL固有の知見であり、当日用Skillや自動化の実装ではない。
- 範囲：2026-10-18 02:40–05:40 JST予定の3時間試行。採用表は **05:00 JST時点、採用589まで**の確定記録。末尾にT15の不採用と05:09時点の固定最終計測を追記した。原状復旧・EC2停止は別の監査を参照する。
- 構成：独立した単独app/MySQL＋専用benchを3組。SubAgentとローカル共有Git/台帳がDiscordの代替fixture。実際の公式複数app構成ではない。
- 準備・配布・中断・人間待ちも競技時計へ含めた。既知の過去問題に対する一試行の結果で、他チームとの優位性や未知問題への再現性は未証明。

## 確認済みの採用経路

比較は同じ統合環境の通常sampleで行い、他レーンの得点やobserved sampleを混ぜていない。初期にはCODE25警告があり、PASSだけを品質合格と扱っていない。

| Source | 通常スコア | 変更・扱い | 採用UTC |
|---|---|---|---|
|a09a950|1088 /1061 /1001|初期値。全PASSだがCODE25あり|—|
|313e179|2185 /2585|座標とowner snapshotの順序化、既存の索引・owner絞込みを含む。両PASS・警告0|19:14:43|
|0656a6b|3101 /2736|rides索引、chair token索引、MySQL driver interpolationの組合せ。両PASS・警告0|19:20:28|
|4177b34|3797 /3285|idle connection保持32。両PASS・警告0|19:47:28|
|589fa31|4045 /4688|pool採用後の空きchair集合からの選択。両PASS・警告0|19:52:11|

これは実sourceの採用4回であり、全実験の単純採用率ではない。sandboxのadvisory close、観測専用、未計測中止、調査、toolingを性能不採用と一括集計しない。一方、実測の品質失敗は別区分で必ず残す。

## CODE25/26：限定修復の成功から残余競合の再現へ

**実測事実**：最初のride-status索引候補は1959 /1861へ伸びたが、cleanな同レーン基準に対してowner/chairsの10秒timeout（CODE25）が8 /9件発生した。元sourceとログを付けた保留を作り、得点だけで採用しなかった。

owner距離集計を対象ownerの完全なchair partitionへ絞り、座標INSERTを遅いride/status読取りの後へ移す案は、実MySQLの長い読取り待ちfixtureで旧版FAIL→修正版3件PASSになった。owner条件を逆転したnegative controlもFAILした。しかし合成8050の独立統合比較2158 /2611では1本目にCODE26が残った。cleanな2本目やテスト通過で保留を消していない。

一時schema内のAFTER INSERT trigger＋named lockでINSERT後・COMMIT前を止めると、8050でもfreshness検証がFAILした。最初の行ロック修正8bもFAILした。ownerのidだけを読むcovering secondaryのFOR SHAREと、座標のPRIMARY FOR UPDATEは、想定どおりの競合を起こさなかった。

313eでは座標側がchairのPRIMARYをFOR UPDATE、owner側がowner索引で範囲を絞ったnoncovering readをFOR SHAREしてから最初のconsistent readを取る。実MySQL5件がPASSし、別ownerの座標更新の進行も確認した。同ownerの集計中は座標更新を待たせる副作用がある。全競合・ミリ秒境界・複数appの安全性を証明したわけではない。

独立通常計測、実資源指紋、実際の採用source proofを313eに結び付けてT1/T2を採用し、3件の保留を解消した。元の失敗source、限定修復、失敗した行ロック案、修復後の証拠を保持した。試験はすべて固有の使い捨てschemaで、benchmarkのDBをロックしていない。

**再利用する判断**：品質保留では同じタスクで原因と反例を保持し、検出感度のある小さいtest→修復→独立ベンチへ進む。「ロック句を付けた」ではなく、実行計画・index record・別ownerへの影響まで実DBで確認する。

## 未採用covering index：索引だけでも意味とlivenessを変え得る

**実測事実**：同時刻の座標0→10→1は、旧索引では距離19。提案4列索引 `(chair_id,created_at,latitude,longitude)` は実handler結果を10へ変えた。5列 `(chair_id,created_at,id,latitude,longitude)` はその反例で19を保持した。SQLのwindowはcreated_atだけで順序付けており、明示的な同時刻tie-breakerはない。5列でのfixture成功も普遍的な順序保証ではない。

強化した8件の実MySQL試験はPASS、4列へ戻したnegative controlはFAILした。それでも5列候補T12のlane-b通常1本目は1906 /PASSfalse /CODE32だった。予定2本目を止め、品質保留をOPENにして復旧した。独立統合の3717 cleanでも帳消しにしない。**T12の保留は今回の採用589でもOPENのまま**で、covering indexは589に含まれない。

CODE32はユーザーが30秒MATCHINGのままというliveness違反。DB未割当だけでなくchair受諾・通知進行も関係する。障害前のmatching handlerは約12msから約500msへ遅くなり、外部ループの呼出し頻度も落ちた。一方、通知500のcontext canceledはcriticalの約4秒後だった。失敗DB snapshotは復旧前に取れておらず、索引順序・書込/lock負荷・sampling・通知のどれが直接原因かは未確定。

隔離scale fixtureでは60k履歴でowner処理が約161→159ms、600kで約4.55→3.93秒。warmな単回比較の概数で、非秘密flagの値1まで置換するログ秘匿の影響もある。小さいfixtureのplanを大規模へ一般化できず、coveringでもwindow/sort/materializationは残った。1回のbatch INSERT時間からcoordinate transactionの競合や本番の書込安全性は推定しない。

**次の仮説**：owner集計の計算量を減らす価値はある。累積距離summaryは有望だが、初期dumpのbackfill、initialize再実行、旧schemaへの復旧、CODE26の原子性、同時刻順を先に検証する必要がある。今回終盤は調査保存のみとし、新schemaを実装しなかった。

## Pool：機序の確認と得点の採否を分離

最初のlane-b通常3039 /3409は品質passだがノイズと分離できず、inconclusiveのまま保存した。任意のpool sizeを試してclean pairを探していない。

同じ統合hostで0656 controlと4177 candidateを各1 observed走で比較した。HTTP分母54378→64712に対し、app接続delta20417→797、Threads_created delta5508→311。1000 HTTPあたり約375.46→12.32接続、101.29→4.81新thread、約 **96.7% /95.3%減**だった。counter窓は初期化・probe・短い隙間を含み、request mixも異なるので、純粋なpool close数や厳密な因果効果ではない。

観測スコア3598 /3387は採否から除外した。機序を確認して初の独立通常pair3797 /3285を取り、0656の3101 /2736に対して固定ルールで+21.32%、採用4177となった。idle32はactive/open上限ではなく、複数appの総接続数や将来のpeak安全性は未検証。

## Matching：再現できた機会損失と、条件変更後の採用

旧実装はactive chairからRANDで最大10回選び、busyかを後から確認する。実観測の663draw /70assignmentはsamplingの無駄の手掛かりだが、busy率やCODE32の原因を直接測った値ではない。

隔離MySQLでconnectionを1本へ固定しSESSION RAND seedの実作用を確かめ、64 active中1台だけ空きとした。旧実装の10draw外に空きを置くと旧handlerが未割当のまま、修正版はその空きへ割り当てた。同じseedの再現とconnection IDも確認し、偶然のrandom成功をtestにしていない。

修正は既存busy定義を保存した空き集合からRAND選択する1クエリだけ。zero-status ride、COUNT(nonnull)=6、6 sent＋1 NULL、count7、inactive、過去rideの各契約を実DBで確認した。batch化・排他・durabilityは変えず、元からの同時matcher競合を解消したとは主張しない。

0656 baseでのstandalone通常2931 /2701は、同レーン基準2719 /3082に対してrule rejectだった。この弱い結果を残したまま、pool採用でDB接続コストが変わった実base4177へ載せた。初の独立統合pair4045 /4688で+23.31%となり589を採用した。条件変更後の効果であり、元のnegative pairやT12の未解決holdを消す結果ではない。

## 時間・並列化・自律性の扱い

- 初期3環境initializeまで9分17秒、初実採用まで **94分43秒**。準備、品質再現、plugin配布、承認待ちを含み、当日運用では短縮すべきコストだった。
- 後半には、初採用→次採用5分45秒、T10 claim→実DB品質結果約97秒、固定候補2本・復旧まで約6分12秒、T13実装→実DB修復確認約2分という局所サイクルが成立した。常に3～6分で採用できるという意味ではない。
- 最大3環境で実ベンチが重なった。同一環境ではdeploy/bench/実DBtestを予約とoperation lockで直列化した。実採用recordを使うstable-syncも実機成功し、新基準を取り直した。
- 固定P,S,S,P比較は人間の採用回答を受け、エージェントが改善採用を優先する判断で **3/24件**のまま中断した。人間が中止を直接指示したわけではない。serial counterpartは未実行。E003の元pattern名fixed-work-schedulingは採用効果の説明として誤帰属であり、今回の解釈を品質修復へ訂正する。原本recordを編集せず、schedulerの得点効果・controlled speedup・競技全体の因果的短縮を主張しない。
- 人間は小さな局所的・可逆的修正を自律採用でよいと明確化した。軽微な待機やトレードオフだけで承認待ちにしない。重大なリスク、広範な変更、構成・方針の選択は具体的な証拠を添えて人間へ渡す。

既存Go native tools、httptest、MySQL slowlog/EXPLAIN/status、nginx counterを使い、OpenTelemetryは追加していない。練習の固有手順はこのknowledgeへ保存する。将来の本番固有Skill化は、入力・対象・出力・失敗条件・復旧と、実装/検証/配布の費用を含む残り時間で判断する。今回の文書追加は新しいSkill・script・運用ルールを配布しない。

## 未検証と証拠への戻り方

native Discord/Gateway/MCP連携、3人の別PCでclone→Claude/Codex plugin install→参加、Rustのbuild/test/runtime比較、元の複数app構成、8時間運用、pluginなしの直列対照、未知問題での再現性は未検証。採用時のpairと末尾の最終確認pairを混ぜない。

一次証拠はPrivate検証リポジトリ [isucon14-ec2-parallel-validation-20261018](https://github.com/shm11C3/isucon14-ec2-parallel-validation-20261018) の以下にある。TRIAL-RESULTSは更新される報告であり、確定source・sample・recordを優先する。

- [FINAL-RESULTS](https://github.com/shm11C3/isucon14-ec2-parallel-validation-20261018/blob/main/evidence/FINAL-RESULTS.md)、途中の`evidence/TRIAL-RESULTS.md`、`controller/protocol.json`、`evidence/scheduling-partial.md`。
- `evidence/member-b-preparation.md`、`evidence/member-c-covering-index.md`、`evidence/member-b-code32-assessment.md`、`evidence/pool-mechanism.md`、`evidence/T-0013-candidate.md`。
- 実採用record：`integration/.kaizen/experiments/{003-scheduling-crossover,004-lookup-driver-combination,007-mysql-idle-pool-mechanism,008-eligible-chair-after-pool}/record.json`。可視性・export範囲により、実行cloneのcanonical artifactを参照する。
- immutable source（検証の共有bare Git内）：initial `a09a95052135d05a28e8b7981384a5db49d6dd39`、repair `313e1795a85839786a946f16881f5e81fe664965`、lookup `0656a6bc89a500909b77efd33aae6f24a5db0411`、pool `4177b3412c1069674d5c9cc0897d13e519356104`、matching `589fa316fa1a4fb8b2cb3989a795ad93426567ad`。
- 失敗/比較source：長い待ち旧版`252ef77392e32bd7432e67627fd47bc25c640ea6`→限定修復`4be719a7cb623b17e53a8f027f1292f9328836cc`、残余窓旧版`e91024c8a5f176462d1fa671adb64bec2ddab644`、不十分なrowlock`8b537c12297c47e4773b78d2515bca377c21fc80`、cover5`3bdbd1c9ee8f38e79e887dd9f66dc3aabae23a6e`、cover4 negative`5a72ac0ea0a58667ff97e226be1e48ad04ee4212`、matching旧fixture`2d6a4b636ce24965f43384b71e30e26a544f7dd8`→修復`33a4e1cff423758c7e7ad2dae8b8c386f12cf947`。

## 05:04 JST追記：同じ索引を新しい比較条件で検証した結果

589の観測でもcoupon全走査が残ったため、既存T10の非unique used_by索引だけを
pool＋matching採用後の実baseへ再適用した。元の0656での公式3172/2581と全履歴を保持し、
同一条件の再試行ではなく比較baseの変更として記録した。
source `0f45cde17a7ab3e7d1ef1a1afbbd9b95347c3960` の実MySQL9件＋11状態ケースは通過したが、
通常3261/2974は589の4045/4688に対して中央値−28.61%で不採用となった。
実データのEXPLAINはused_byが新索引のref/1行、user別未使用検索はPRIMARYのref/3行だった。
索引未使用やlock用索引の切替えが原因という証拠はなく、得点低下の機序は未分離である。
SQL処理量の削減を得点効果と同一視せず、T10/T15を今回不採用として589へ復旧した。
最終2走はこの後に固定した589で行い、観測最高値を最終得点にしない。

## 05:09 JST追記：固定した最終確認

589を選定し、canonical recoveryによるapp/matcher再起動・DB復旧後の事前固定通常2走は
**4007 /3263、両PASS・警告0、中央値3635**。初期中央値1061とのraw比は3.426倍だが、
初期にはCODE25警告があり、pluginや並列化の因果効果ではない。採用pair4045/4688や
observed最高5843を最終値へ差し替えていない。実source/DB schemaを含む資源指紋も一致した。
EC2 OS全体のrebootは未実施。レプリカのlane-a2638/2912、lane-b4095/3567もすべてcleanだが、
異なる環境のスコアは混ぜず、独立な稼働確認として保持した。

最終集計はphysical sample69件（normal61/observed8）、最大3環境同時、重複wall clock998.738秒。
制御された直列対照がないため、その値を実際の短縮時間とは呼ばない。
`FINAL_MEASUREMENT.json`と`EVIDENCE.json`は原状復旧前の最後の実測状態を表す。
その後の開始前snapshot復旧とEC2停止は、検証repoの`CLEANUP.md`と独立した監査へ分離した。
