# 実機運転の結果と次の改善案

`scripts/knowledge.sh report` の出力が一次情報です（`knowledge/records/`）。

## 0.10.0: 観測結果を改善仮説へつなぐSkill

[profile](skills/profile/SKILL.md)を追加した。問いに応じて既存のalp、pprof、SQL digest/
EXPLAIN、OTelを選び、生データ・版・費用・coverageを確認して1つの仮説へ渡す。
全ツールやCollectorの導入は必須にしない。Goテンプレートは公式SDK/otelhttpとotelsqlで
HTTP→実SQLを関連付け、private pprof・起動時flag・正常終了/flush・秘匿を扱う。
Go JSON用集計はDB区間のsum/unionと未知coverageを区別する。Rustは対応版・async・
既存subscriber・build費用・console形式の違いをreferenceへ整理した。

実ISUCON14 + 隔離MySQLでHTTP171件のDB接続、実CPU/heap解析、slowlog/EXPLAIN、停止を確認。
独立Go実DB fixture、Rust実HTTP/mock DB fixture、alp人工ログでも検証した。
全Python134 tests（70.306秒）、shell E2E（45.277秒）、Skill validatorがPASS。
[知見と限界](knowledge/lessons/20261019-profile-tools.md)、
[証拠票](knowledge/validation/profile-tools-20261019.json)を参照する。
公式ベンチの新得点、Rust実アプリ/実DB・OTLP、Discord連携は今回の検証範囲外。

## 未リリース: 2026-10-29 ISUCON14チーム練習（Codex=Agent1、Claude=Agent2）の指摘

練習中にAgent2が記録した13件のうち、plugin側で直せるものを反映した。練習中の共通ホストの
pluginは差し替えておらず、版も上げていない（版を上げるとjoinの版一致で練習中のメンバーが止まる）。

- `task-withdraw`: 提出者が統合前のREADYをCLAIMEDへ戻す。統合担当がその候補IDで占有中なら拒否。
  RETEST_PENDINGの保留はOPENへ戻す。1候補1機構の粒度をteamスキルとOPERATIONSに明記した。
  （指摘12: 統合担当に「機構ごとに分けて」と言われても取り下げる手段がなかった）
- `join.py`: モデル確認の失敗を`auth`/`model_unavailable`/`mismatch`/`cli_error`/`timeout`に分類
  （本文は出さない）。セッションIDの先頭がGitHub loginと大文字小文字だけ違えば警告する。（指摘10・3）
- `--env NAME`（join/control）: `team/environments/NAME`、なければ`~/.config/kaizen/NAME/control-host.json`。
  host-configの`name`を出力とstderrに出す。（指摘11・13）
- host-configの`discord`ブロック（guild_idと5チャンネル）をjoinが表示する。練習用host-configの雛形と
  新規リポジトリ用`AGENTS.md`/`CLAUDE.md`雛形を`team/templates/`に追加した。（指摘1・4・6・7・9）
- DISCORD.md: 共有Botの投稿は`[セッションID]`で始める、参加時は全チャンネルの新着を読む、
  旧チャンネルに移動先を残す、読取位置の記録書式。（指摘2・8・9）

- `watch.py`: 自分のタスクの変化（差し戻し・終了・引継ぎ）を読み取り専用`task-list`で待ち、最初の変化で終了する。
  練習でAgent1がT-0001をNEEDS_MEASUREMENTで返したが、待機中のAgent2は気づかず止まっていた。実台帳でSSM経由の取得を確認。
- 採否ルールv2の`NEW_ERROR_TOLERANCE`（既定`2:1`）: 全サンプルpassで得点が閾値を超え、基準になかった
  非致命のエラー種別が「件数2以下かつ1万リクエストあたり1件以下」なら保留せず採用し、
  `stabilizationRequired`を付ける。統合Agentは関連の安定化タスクを自動で起票する。既知種別の率上昇、
  分母なし、正しさ種別、上限超えは従来どおり保留。（人間の指摘「安定化の余地があるなら採用する価値は
  あるのでは」。T-0004 retry単独は1228/1285・+26.7%だったが、error26が1件出て保留になった）
- `task-ready`: `--base`がOPEN/RETEST_PENDINGの品質保留のsource（または修正SHA）と一致すれば`warnings`を返す。
  T-0007とT-0009はT-0001のsource上に積まれたが、T-0001は品質保留#2（timeout）になり、修正でSHAが変わると
  2件とも作り直しになる。台帳はgitを持たないので、祖先関係ではなく一致だけを見る。
- 採否ルールv2の`STABILIZE_GAIN_BP`（既定10000＝得点2倍）: 全pass・正しさ種別なしで中央値が2倍以上なら、
  既知エラーの率上昇も採用＋安定化タスクにする。T-0001 index単独は2946/3245（初期中央値992）で
  error25が16/10へ増え保留になった。保留すると後続候補が初期基準で測られ、積み上げが効かない。
- `task-create --related`: 同じタスクの周辺にある進行中タスクを`possibleDuplicates`で返す。仮説キーは
  自由記述なので、T-0006「index単独」がREADYのT-0001と重複しても検出できなかった。
- POLICY: 連絡は速く・方向は入念・修正は速く・検証は仕組みへ、
  上記の採用方針、FBと気づきの記録と反映（練習では厚めに、本番は得点優先で、未反映は可視化するがgateにしない）。
  FBの記録先はAgent1が実装中の共有台帳registry（T-0005）に合わせる。

- teamスキル: 1〜2分ごとに環境の全Discordチャンネルを読む（Subagent可）、control.pyはstdoutだけを解析する（stderrは`SSM Command ID:`と`environment:`）。（指摘14: Agent2はAgent1の返答4件を約10分見逃し、監視scriptはstderrの行をJSONとして読もうとして毎回失敗していた）
- 未対応（観察）: 練習環境の準備をAgent1が手書きscript 6本（制御ホストの専用dir、plugin/repoのclone、deploy key、ssh_config、control-host.json、target.json、env-acquire）で行った。生成したcontrol-host.jsonには`name`も`discord`もない。環境名・repo・host一覧から一式を出す`practice-init`があれば、state_dbとtarget_configの組のずれと、targetの`environment: competition`による取り違えを防げる。また占有tokenがローカルのscriptファイルに平文で残った。

残り: MCPにチャンネル名変更・カテゴリ移動がない（指摘5）、新着でのセッション起動（指摘8の本体）は
plugin外。練習後に共通ホストへ入れ、実際のjoin出力とwithdrawを確かめる。

## 0.9.0: 必要な事前確認と実ベンチ、回数上限の見直し

[検証方針](team/docs/VALIDATION.md)へ集約した。事前は必要なbuild/smoke、変更契約・
観測済み不具合のfocused regression、安価な関連Lintを選ぶ。全回帰・race・Clippy全target・
新coverage・独立/LLMレビューを毎候補の必須ゲートにしない。実ベンチで性能とcheckerの
正しさを確認し、既知欠陥・未解消holdはPASSでも免除しない。READYに公式結果は要求しない。

一律の総120回・毎時30回・実験6回・毎時6実験という既定上限には、公式規定や実測で
必要性を示す根拠を今回確認できなかった。4つの回数capは既定0（plugin上限なし）へ変更した。
全物理試行は記録し、公式制限やチームの予算に基づく正の明示値は引き続き強制する。
復旧余裕は各有限capの中に残し、実際のquotaを超過できる追加枠にはしない。
時間予算・MAX_EXP_MINUTES=30・判定v2/最低2サンプル・排他・品質条件は維持する。

既存configの正数は自動変更しない。変更はidle時に行い、チーム環境の既存再登録手順を
使う。quotaだけの変更でstable bundleの比較条件は変わらないが、登録identityは別に守る。
進行中のcore/pinは差し替えない。別ブランチで開発中の独立integratorはこの変更に含めず、
統合時に任意レビューの既定無効化・占有前の実施を本方針と照合する。

追加5件を含むPython123テスト（75.68秒）と`tests/run.sh`（49.44秒）がPASS。
無制限でも125試行の記録、有限3scopeの復旧枠、上限超過拒否、時間窓、既存設定維持、
不正値の拒否を確認した。これらはplugin変更の回帰で、アプリ候補ごとの全回帰義務ではない。
詳細は[検証記録](knowledge/lessons/20261018-bench-first-validation.md)。公式ベンチの新得点や
各PCのnative reload、独立integratorの実機運転はこの検証では確認していない。

## 0.8.0: 各主Agentの候補準備パイプライン

各Discordの主Agentが判断と共有を持ち、native SubAgentへ実装から関連QA・READY資料までを
一括委譲する。初期の目安は実装1件＋次候補調査1件。小修正の独立レビューや新規Agentを
必須化せず、役割は動的にする。詳細は[PIPELINE](team/docs/PIPELINE.md)と
[prepare-candidate](skills/prepare-candidate/SKILL.md)。同じ環境の排他・単一公式統合・品質保留・
actual sourceの検証は維持する。

任意の`task-stage`と読み取り専用`pipeline-status`を既存eventへ追加した。未計測の工程は
unknownとし、記録区間の和とunionを区別する。submittedAgeは統合待ち時間ではなく、
実統合開始の厳密markerが無い場合のqueue待ちはunknownのまま。

前回の追加試験は15候補9採用、最終固定31306/30373だが、実機は2h24m44sで終了して
約35分を使い切らなかった。候補の検討・実装・QA・待ち・比較・修正/復旧・final/cleanupを
総予算へ含め、source固定の時刻目安だけで探索を終えない。clean不採用はprior recordと
変わった負荷・機構・識別根拠から再検討する。登録名衝突のH1は未解消のまま保持し、
後のclean pairや別タスクで免除しない。問題固有の施策はpractice knowledgeへ保存する。

[独立した検証記録](https://github.com/shm11C3/kaizen-agent-pipeline-validation-20261018/blob/main/REPORT.md)で、
実SubAgent2つが実ISUCON14 Goコードを修正し、関連QAまで自走した。準備は54秒/104秒、
明示した作業区間の重なりは17.47秒（準備windowの重なり40.50秒とは区別）。
初回は成果READYから台帳READYへ146秒/83秒かかったため、同一主セッションの明示委譲を
READY提出まで拡張した。既存候補を使う提出のみの再試行では台帳eventまで0.151秒/0.084秒。
これは機能確認で、公平な直列対照や競技全体の短縮率ではない。
初回の合成完了→QA開始にも147秒の間隔があったため、統合担当へ合成から関連QAまでを
一括委譲する手順へ補強した。別worktreeの実合成・actual SHA検証を1回のorchestrationで
完了し、段階ごとの親指示待ちを挟まない動作を確認した（全体2.46秒、得点比較ではない）。

合成で同一ファイルのblobが変わる2案をactual SHA `541e180`へ再提出し、そのsourceを
native契約3件（4 subtestsを含む）・gofmt・vetで検証した。割当microbenchは
61/63/65→各11 allocs/op。アプリ得点効果は未測定。追加14件を含むPython 118テストと
`tests/run.sh`がPASSし、既存排他・品質保留・source guardを維持した。
実DB2つで`pipeline-status`前後のbytes・mtime・schema・内容の不変も確認した。
問題固有の変更は[practice knowledge](knowledge/lessons/20261018-agent-pipeline.md)へ保存した。
Discordの実接続、各PCのClaude/Codex install/reload、実EC2での得点・時間短縮の因果効果は
別の検証項目として残す。計測coreは変更していない。

## 0.7.6: 実証済み改善の自律採用

大きい構造変更でも、品質・比較・固定ルールの得点改善・変更資源の復旧を確認し、
合意した目的・仕様・競技ルール・操作範囲を守るならAIが採用する。
構造変更・複数案・副指標の悪化だけで`review=human`にしない。
合意を超える目的選択・権限・不可逆操作・重大な残余リスクを人間へ渡す。
未検証やノイズはAI調査とし、品質条件や既存のhuman参照ガードは維持する。

根拠は[得点予算試験](https://github.com/shm11C3/isucon14-score-budget-validation-20261018/blob/main/evidence/FINAL-RESULTS.md)の
通知方式変更を人間待ちにした件と、その後の人間による運用方針の訂正。
これは将来の分類ルールの更新で、当時の未採用記録・スコア・閉じたproofは書換えない。
Skill形式・相対リンク61件・両manifestの版一致・diffを確認し、既存team 13テストも
3.18秒でPASS。判定script・品質・復旧ガードのコードは変更していない。
実行中・既存セッションのcacheを差し替えず、新版の実読み込みは別途確認する。

## 現行の優先事項（0.6.0とその後のmain更新）

実験途中で目的が変わった場合、閉じる前に最終の変更・仮説へmanifestを更新し、
元の計画を別artifactへ残す。診断・並列化の計画にアプリ修正の得点を帰属させない。
閉じた採用proofは書換えず、ナレッジへ明示的な訂正注記を付ける。

**未修正: remote Go checkのログ秘匿**。env-fileの全値を`text.replace`で秘匿するため、
非秘密flagの`"1"`もログ中の数字1を置換し、今回のEXPLAINやhandler timingの正確な値が失われた。
JSONのtest duration・hash・pass等のmetadataは正しい。秘匿を既定としたまま、非秘密flagを
明示分類する方法を検討し、短いsecretの漏えい防止と非秘密の数値保持を回帰検証する。
文字数だけで短い値を秘匿対象外にする対応は行わない。今回の固定版・実測coreは変更しない。

**未修正: guardの読取・派生出力の誤検知**。`hooks/guard.py`の`PROTECTED_FILE`と
`WRITE_INDICATOR`の組合せが、Pythonのread-onlyな`>`比較も書込と誤検知し、
今回のFINAL派生集計を2回拒否した。既存のsummarize exportと派生artifact作成を分けて
原本を変更せず完了した。読取・派生出力と保護対象への実書込を区別し、実書込の拒否を
維持する回帰テストを加えて修正する。今回のcode・runtime pinは変更しない。

**未修正: 更新前セッションのhook cache寿命と再開手順**。旧root/infraは不在の
`~/.codex/plugins/cache/kaizen-plugin/kaizen/0.2.0/hooks/guard.py`をPreToolUseが参照し、
終了時のexecを実行前に拒否した。Pythonの`>`比較の誤検知とは別件。
設定無効化・cache捏造・コマンドの迂回は行わず、正常なhook設定でSTSが成功した新規
セッションへ所有権を移譲し、固定6台の復旧・停止を完了した。cache消失の原因や
全provider経路は未検証。旧cacheの保持期間と更新済みnativeセッションへの再開手順を
確認・実装する。認証待ちの間もSubAgentが許可済みのSSH準備を継続した。

## 今回の3時間予算の実機試行で確認したこと

実測runtimeは`0.7.5@f3ef308`に固定しており、この文書更新で変更しない。
対象はISUCON14 Goの練習環境で、`competition`も実際の公式競技サーバーではない。
[最終実測報告](https://github.com/shm11C3/isucon14-ec2-parallel-validation-20261018/blob/main/evidence/FINAL-RESULTS.md)は
集計時刻を持つsnapshotであり、採用時と終了時の値を区別する。実source採用は313e・0656・4177・589fa3の4回、
アプリ改善タスク7件がACCEPTED。589fa3の採用確認はnormal 4045/4688・警告なし、前stable4177比+23.31%。
最終sourceは`589fa316fa1a4fb8b2cb3989a795ad93426567ad`。両lane同期・新baselineと、
アプリ／matcherのservice再起動・DB復旧後の統合確認を完了した。事前に固定したnormal 2本は
4007/3263・警告なし、中央値3635。これは原状復旧前の最終実測で、OS全体の再起動は未実施。
[最終実測の証跡](https://github.com/shm11C3/isucon14-ec2-parallel-validation-20261018/blob/main/FINAL_MEASUREMENT.json)を参照する。
予定予算は02:40〜05:40 JST。最終ベンチは05:06:32、6台の復旧・独立照合・停止の
実機終了確認は05:23:33（開始から2時間43分33秒）。予定終了まで計測を続けたとは扱わない。

- 実EC2の独立した単独app＋専用benchを3組使い、最大3環境の同時計測を確認した。
  stable-syncは実採用0656の記録から両laneをa09→0656へ同期し、target操作は約16秒ずつ。
  新bundleを確認して各laneで新baselineを取り、公式や旧laneのsampleを流用していない。
- Go remote checkerで実MySQLの隔離schemaを使い、5・6・7・8件のfixture実行、
  old-red/new-green、negative control、cleanupを確認した。全競合の不存在を証明したとは扱わない。
- source-bound品質保留3件を313eの実official採用記録へ結び付け、RESOLVEDまで通した。
  新しいcovering-index候補のCODE32に関するT12の保留はOPENのまま保持している。
  実promote直前の資源fingerprintも計測済みcandidateと照合した。
- 開始から初期3環境の準備完了まで9分17秒、初実採用まで94分43秒。
  PSSPは3/24で中断しserial対照は実行していないため、並列化による時間短縮の因果効果は未証明。
- `ec2_lanes.py`の新規create APIはfake検証のみ。実機ensure/statusと管理対象4台のstop APIを確認した。
  各自の開始前snapshotへの復旧・独立照合は全6台PASS。integration2台は固定IDで別stopし、
  AWS上で全6台stopped・対象外の本番controlはrunningを確認。本番repoも開始時SHAのままclean。
  [終了監査](https://github.com/shm11C3/isucon14-ec2-parallel-validation-20261018/blob/main/CLEANUP-EVIDENCE.json)を参照。
  terminate/EBS削除・復旧後API/bench/deployは行っていない。Discord接続、別PC3台でのClaude/Codex native install、
  Rust版の競技build/test/runtime比較、本来の複数app構成も未検証のまま。

**台帳の未解消課題: tooling作業の完了表現**。T7のplugin toolingは実装・release済みだが、
`work_kind`にtoolingがなくアプリの採用proofを要求するため、CLAIMED表示が残っている。
偽のアプリ採用記録で閉じず、tooling用の種別・検証証跡・完了経路を設計して検証する。

## リリース別の確認と残作業

0.7.5では通常比較・観測専用・未計測・旧形式不明を分け、比較合格と実際の採用を
別集計する。意図的な未採用だけでno_verified_gainを出さず、失敗・警告・品質不明は
保持する。全102unit/E2Eと追加修正後13focused tests、実台帳のread-only再集計で確認した。
待機も競技時計を消費し、これらの件数だけでは採用率の分母や因果効果を定義しない。
今回の実測runtimeへはidle境界で読み込み、以後`f3ef308`の固定版を維持している。

0.7.4ではpromote直前の実資源を、同candidate SHAの非観測sampleのfingerprintと照合する。
human待ちrecoverでschemaが戻り、コード再deployだけで異なる資源を採用できる問題を
fake remoteで再現して修正した。probe失敗もmain/STABLE_REV更新前に拒否し、
元sampleは保持する。スコア・evaluate・benchの判定は変更しない。今回の固定版へ取り込み、
実採用時にも現在の資源とcandidate sampleを照合した。

0.7.3では未解消の品質保留をtask IDを越えて継承し、提出sourceの変更内容が実測SHAに
含まれることを検証する。公式promote前とtask採用時の両方で確認し、重なる編集は実際の
統合SHAで再提出する。全93unit/E2Eと実候補のread-only replayで確認済み。
閉じた履歴や任意の意味的書換えの検出は範囲外として記録を残す。今回の実機では3件の
保留を313eの実採用proofでRESOLVEDとし、新しいT12の保留は解消扱いにしていない。

0.7.2では公式の実promote記録に束縛したsandbox stable同期を追加。別環境のsampleを
転用せずbaselineをretireし、同期後の新baselineを必須にする。FF制限、失敗時の旧stable
復旧、復旧不能時のpendingと他操作拒否はfake remoteで検証した。今回の実機positiveは
両laneのa09→0656同期と、新baseline取得まで確認した。実機の故障注入は未実施。

0.7.1では所有レーンの操作ロック内でimmutable refをcrossbuildするGo remote checkerを追加。
明示include・private env map・隔離schema fixtureを使い、失敗・skip・選択0件を区別する。
誤ref・missing include・cleanup対象限定・native失敗保持・target排他はfakeで確認し、
今回の実機で旧版再現→修正版確認・negative control・隔離schema cleanupを確認した。

0. **EC2並列レーンの終了・復旧まで確認する（0.7.0）**。app＋benchのplan/ensure/status/stopと
   起動前状態・client tokenの保存を追加した。誤account、資源重複・公式資源、応答喪失後の
   二重作成防止、停止対象の限定はfake AWSで確認済み。実機の最大3並列計測と
   品質保留→修正→公式再測定・実採用、全6台snapshot復旧・独立verify・停止を確認済み。
   sandbox4台の実stop APIは確認済み、新規create APIはfakeのみ。
   準備を含む時間短縮の因果効果は未証明。

1. **品質保留の修復を続ける**。基準版でも出る警告と候補の退行を区別し、
   実DBの再現・修正・公式採用proofで3件を解消した。新T12のCODE32を調査し、
   同じ内容の再試行には未解明の警告を引き継ぐ。
   未実装: T12は明示recoverをDB snapshotより先に実行して失敗状態を失ったため、時間・秘匿・復旧優先の境界を決め、復旧前に限定した診断状態を保存できる仕組みを検討する。
2. **Go実アプリで確認したLintをRust・並列資源の検証へ広げる**。Go競技アプリのwarm fmt/vetは
   例0.078/0.321秒。rootの合成sourceではworkspace cache coldのvet 4.128秒、local test 1.311秒を確認した。
   実MySQL確認は別の8.815秒で、local testと区別する。Rust実アプリと並列local資源競合の因果測定は未検証。
3. **Go／Rustを改善サイクル全体で比較する**。ビルド・テスト・修正・復旧時間と、実行性能、
   コンパイル時の安全性を比較する。[判断基準とキャッシュ保持](team/docs/RUST_BUILD.md)は反映済み、言語間の実測は未実施。

Discordを用意できたら、各人の実PCで独立したClaude/Codexセッションを起動し、[Discord連携](team/docs/DISCORD.md)の
読取・投稿と[参加手順](team/docs/ONBOARDING.md)を確認する。GitHubユーザー名をブランチの
先頭に使い、セッションIDを区別する。実際の会話・候補提出・統合・結果共有を通す。
過去の検証補助や同一PCでの試験を当日の連携手段として前提にしない。

[並列検証と品質保留](team/docs/PARALLEL_QUALITY.md)は今回の実EC2で並列実行と修復・採用まで確認した。
実Discordでの協調と、複数EC2による時間短縮の因果効果は未検証。[最小構成との比較](team/docs/COMPARISON.md)は
並列化・品質保留の扱いを優先する方針で延期しており、競技力の優位性は未証明。

以下の練習は異なる問題・条件の事例で、プラグインやplanの因果効果を示す比較ではない。下の「次の改善案」は当時の候補一覧。追加の管理機能は、比較で分かった損失と得点への効果を見て選ぶ。

## 2026-10-17に測れたこと

| 問題 | 実験 | promote | スコア（最初の baseline 中央値 → 最後の promote） | 最初の promote まで |
|---|---|---|---|---|
| ISUCON14 | 7 | 2 | 2527 → 8650 | 13 分 |
| ISUCON13 | 3 | 3 | 3733 → 9109 | 5 分 |
| ISUCON12 予選 | 1 | 0 | 2064 → （判定不能） | — |

- 1 実験の実時間は 3〜9 分（deploy 4〜10 秒、ベンチ 68〜106 秒 × 2〜3 本）。
- ISUCON14 の stable 75a8032 では同一コードで 5 本 5369〜9538（±27%）。この幅では n=2 の判定は成立せず、006/007 の reject/inconclusive は判定ではなくノイズの範囲。
- ISUCON12 は AMI 初回起動の unattended-upgrades が mysql と docker CLI を差し替え、baseline と candidate の両方を汚染した。plugin に `BENCH_PRECHECK_CMD` と `stable.sh forget-baseline` を追加して対処したが、再計測は未実施。
- hold-out 比較（13 を未知問題として「ナレッジあり / なし」）は、コーパスの計測行が 11 件では成立しないため未実施。13 の 3 実験は 14 で計測した順序（index → 静的/キャッシュ）をそのまま使って全て promote したが、これは比較ではなく一例。

## 追記: ISUCON12 予選の再走行（計画先行・静かなホスト、2026-10-17 夜）

| | ISUCON14 1 周目（計画なし） | ISUCON12 再走行（plan.md 先行） |
|---|---|---|
| 実験数 | 7 | 4 |
| 最終判定で無駄になった実験 | 4/7（うち 2 件は採点経路外） | 0/4（ルール単独では 2 件 inconclusive を「前提条件」として override） |
| 採点経路外の実験 | 2 | 0（全て採点比率 46% 以上の経路） |
| 最初の promote まで | 13 分 | 7 分（ルール単独の promote は 24 分） |
| スコア | 2527 → 8650（7 実験） | 2274 → 8230（4 実験、実稼働 47 分） |
| 計画の改訂 | — | 4 回書き、順番が変わったのは 1 回 |

計画が外したのは効果の大きさの予測（index と一括 INSERT は flock の待ち行列に隠れて +5〜10% にしか見えなかった）で、順番の判断（採点経路、lock → id 生成が大きい）は当たった。待ち時間と処理時間を区別できる観測（lock 待ち、リクエストあたり CPU）が次に必要。ホストは再起動後に docker daemon の更新で compose が壊れており、setup に「再起動後はサービスとイメージビルドを確認」を追加した。

## plugin が実機で学んだこと（retro/log.md、26 件）

rsync の itemize（`<f`）、/etc の所有者、nginx ログの引用符、記録ファイルと git の衝突、cwd 依存、SIGPIPE、docker CLI の差し替え、prepared statement が performance_schema に出ない（slow log 経由の観測と「観測中のサンプルは判定に使わない」）、ベンチ出力と result.json の混線。どれも偽リモートのテストでは出ず、実機 1 周目で出た。

## 次の改善案（優先順）

1. **計画を先に立てる**（実装済み: `knowledge.sh plan` / plan skill / Stop hook）。006/007 は「DB は軽くなったがスコア経路外」で、計画段階でマニュアルの採点方式を見ていれば飛ばせた。plan.md の「scoring path?」欄を埋めるまで experiment を開かない運用にする。
2. **ノイズを先に測り、n を幅から決める**。`bench.sh baseline` を 3 本取って相対幅を出し、`MIN_IMPROVEMENT_BP` と最小サンプル数を自動で提案する（幅 ±27% なら「n≥4 か、効果が 2 倍以上の仮説だけ」）。評価ルールはそのまま、入力の作り方を変える。
3. **ホストの衛生を前提条件にする**。初回起動の unattended-upgrades を setup で無効化または完了待ちし、サンプルごとにホストの load と稼働中パッケージ処理を記録する（12 で全数値が無効になった）。
4. **観測の盲点を埋める**。prepared statement（slow log 経由）と SQLite（アプリ側トレース）を signature が読めるようにし、エンドポイント別レイテンシ表からも候補を出す（12 では既存ルールが 1 つも発火しなかった）。
5. **分散減らし**。ISUCON14 ではマッチングを決定的にしてから再計測する（plan.md に記載）。
6. **hold-out 測定の実施条件**。各問題 10 件以上の計測行が揃ったら、13 を hold-out にして「ナレッジあり / なし」で最初の promote までの時間と固定時間後のスコアを比較する。それまでコーパスは費用。

## 環境（記録時点のスナップショット。現在の稼働状態は別途確認）

EC2 8 台（isu1〜3, isubench, isu13, isu13bench, isu12, isu12bench）が稼働中。stable: isu1=75a8032（isuride-practice）、isu13=ebb3824（isucon13-practice）、isu12=4be57e2（isucon12-practice）。

## 0.6.0: Go／Rust、既存ツールと準備フェーズ（2026-10-18）

prepare-tests/refactor、既存ツール選択、汎用観測セッションと採否用スコアの分離、
実行時間・ソースに紐付くテスト記録を追加。Discord実接続は未検証。
効果の主張は実測報告を参照し、Go/Rust smokeと競技実測を混同しない。

20分の追加試行では3実験すべて品質保留、採用0。回帰の失敗検出は確認したが得点効果は未確認。
[知見](knowledge/lessons/20261018-isucon14-tools-tests-phases.md)に、同一内容の警告再発、
保留台帳の未使用、clone内の並列操作混線、実DBテストの不足を記録した。
入口手順を補強した。当時不足した実験をまたぐ品質保留の継承とsource bindingは0.7.3で補い、
後の3時間実機では3件の保留を実採用proofへ結び付けた。意味的な同一性の任意の書換えまで自動検出はしない。

候補最高は2,846点だが最終採用スコアではない。初期版に戻して3回測定したraw中央値は1,042点、
pluginの品質判定はunknown。同じ警告が初期版でも出たため、候補が品質を悪化させたと断定できない。
最終初期版のgo testは既存slog vet診断で失敗し、修正は候補branchに残った。
独立したRust fixtureではテストの成功と意図的な不具合の検出を確認したが、Rust版ISUCONの
性能・ビルド時間は未計測。以上は先の問題別練習と条件が異なり、得点を直接比較しない。

## 0.6.1: Lintを運用へ組み込む（2026-10-18）

- [x] 開始時に対象toolchainで全体を確認し、既存の指摘と実行時間を記録する手順を追加した。
  実装中は変更package／crate、候補提出前は関連範囲へ広げる。formatterは変更ファイルを中心に使う。
- [x] Goはgofmtとgo vet、Rustはcargo fmt --checkとcargo clippy --lockedを基本に、
  [prepare-tests](skills/prepare-tests/SKILL.md)と[既存ツール手順](team/docs/TOOLS.md)へ反映した。
  実行をscripts/check.pyで記録し、ツール版・対象・ソース・生ログ・時間を共有する。
- [x] 正しさに関わる指摘は原因確認・修正へ戻す手順を追加。意図した実装なら根拠を残して限定的に扱う。
  既存診断を黙って無効化せず、スタイル提案と区別する。Clippyの終了0でも警告内容を確認する。
- [x] 全警告の一律エラー化やpedantic／restrictionの一括導入は初期要件にしない方針を反映。
  性能の提案は仮説として扱い、公式ベンチで確認する。仕様・DB整合性は再現テストでも検証する。
- [x] 小さな正常／不具合入りfixtureで検出と修正後の解消を確認し、初回・再実行3回・修正後のLint時間を測った。
  整形＋解析の記録込み壁時計は初回Go 2.618秒／Rust 0.637秒、再実行中央値Go 0.427秒／Rust 0.426秒。
  終了0のgofmt差分・Clippy警告もneeds_reviewとして検出した。
- [ ] 競技アプリの依存・規模と並列ビルドの資源競合を確認し、増えた待ち時間と実際に削減できた手戻りを記録する。

[運用手順](team/docs/LINT.md)、[実測と起動失敗を含む知見](knowledge/lessons/20261018-lint-validation.md)、
[機械可読の証拠](knowledge/validation/lint-20261018.json)を参照。依存なしの異なるfixtureによる測定で、
言語間の優劣、AIの自律修正速度、競技アプリの最終スコアへの効果は示していない。

一次資料: [go vet](https://pkg.go.dev/cmd/vet)、
[Clippyの実行](https://doc.rust-lang.org/clippy/usage.html)・[指摘の分類](https://doc.rust-lang.org/clippy/lints.html)。

## 0.6.2: manual分母取得と条件不一致（2026-10-18）

manualの予約時／結果登録時のカウンター差分、取得コマンド・ホスト・解析関数の条件hash、
sampleの取得元IDを追加した。方法変更時の予約・登録拒否、自動取得／明示入力の比較不適合、
読取失敗・不正出力・カウンター減少を偽リモートで確認した。
[検証記録](knowledge/lessons/20261018-manual-request-counts.md)を参照。
DESIGN_REVIEWの断定表現も修正した。旧bundleは安定状態で再captureし、新baselineを取る。
今回のSSH運用では実ログの分母取得を確認した。manualポータルでの実運用、およびv3の本番適性は未検証。
