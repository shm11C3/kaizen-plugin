# 既存の確認を実行し、実測で調整する

目的は制限時間内の最終有効スコア。候補ごとに包括テストを完成させることではない。
当日の公式実ベンチ（練習では配布された実ベンチ）を、性能とcheckerが検査する正しさの
共通の判断材料にする。既存テストとformatter/Lint一式は実行を基本とする。
既存suiteを回す費用と、新しいテスト・独立レビューを作る費用は分けて判断する。

## 候補前の確認

1. プロジェクトの既存テスト・formatter/Lint一式を、既存の設定・featuresで実行する。
   Goの例は`go test ./...`、`gofmt -l .`、`go vet ./...`。Rustの例は
   `cargo test --workspace`、`cargo fmt --all -- --check`、
   `cargo clippy --workspace --all-targets`。[Lint手順](LINT.md)の記録方法を使う。
   既存CI/scriptのflagsやDB接続条件に合わせ、恣意的な`--all-features`は追加しない。
2. 実行時間を測り、cold/warm、依存取得・compile・link、既存buildとの重複を区別する。
   重いことが確認できた検査だけ、残り時間から範囲・頻度・並列実行を調整する。
   最初から全体をfocusedへ限定せず、数秒で済むsuiteはそのまま回す。
   並列化によるCPU競合・共有cache/build lockも測り、コマンドを同時起動しただけで
   時間が減るとは扱わない。target計測と資源を競合させない。
3. 足りない範囲のテスト追加やrace・DB/並行検査は、具体的な故障リスク・観測済み不具合・
   回収できる時間がある場合に別途選ぶ。mockやpure helperの成功でDBの意味を検証済みにしない。
4. 必要ならbuild・load/smokeも確認する。既存テストやdeployのbuild・health確認との
   重複費用を把握する。正しさの診断を修正し、整形・styleの助言だけで提出を止めない。

既存suite実行と、新しい網羅的coverage・race・独立レビュー・LLM契約レビューは別判断。
全ケースを列挙するLLM契約レビューは既定で行わず、
具体的な仕様疑義・大きな意味変更・観測した失敗を解く必要があるときだけ任意に使う。
準備段階の独立レビューやテスト設計は共有targetの占有外で行い、環境が必要な検証は既存の占有を使う。
小さな修正を包括レビューの完了待ちへ戻さない。
常駐integratorの新規設定例は`review=none`。既存設定の`review=llm`は互換のため維持され、
現実装では処理する候補ごとに占有内で任意レビューを行う。自動で書き換えず、不要なら
idle時に`none`へ変更する。設定名だけから候補別のrisk判定や占有前レビューを推測しない。

## 何を確認できたかを残す

実行したcheckはimmutable source SHA・範囲・条件・結果・時間へ結び付ける。
未実施・skip・依存不足・選択0件をPASSと記録しない。実測を受けて範囲や頻度を変えたら、
元の秒数・判断理由・未実施範囲を残す。新coverageの完成をREADYの一律条件にしない。
統合でsourceが変わった場合はactual integrated SHAで既存suiteを基本に確認し、
高コスト検査の調整は同じ基準で行う。同じsource・scope・条件の証拠は再利用できる。

常駐integratorは、合成したactual candidate SHAをdeployする前に設定済みの`checks`を実行する。
既存`check.py`を再利用する小helperで全configured checksを走らせ、source SHA・JSON・生ログ・
秒数を残す。workerの旧sourceの結果だけで合成版を検証済みにはせず、通常はこの経路で確認を
完結させる。blocking check失敗は品質保留・復旧へ戻す。style専用の`advisory:true`は
declaredAdvisoryとして別記録し、raw status・exit code・passedをPASSへ書き換えない。
明示したstyle advisoryは継続できるが、非advisoryの`needs_review`は自動通過させずwarning保留へ戻し、
担当AIが原因・正しさへの影響を調べる。必要な修正や根拠付きの局所抑制を同じtaskで再提出する。
警告を一律エラー化したり人間の承認待ちにしたりはしない。compiler error・source変更・実行不能は
advisoryラベルでも免除しない。

setup時に[Go/Rustの既存suiteレシピ](../../README.md#candidate-checks)を実projectへ合わせ、
`settings.checks`へ相対`cwd`とargvの`command`、`timeout_seconds`、必要な`diagnostics`を登録する。
配布例・未設定の`checks=[]`は未設定/未実施として台帳へ記録し、PASSを作らない。
既存設定を自動で書き換えず、idle時に更新する。新しいテストframeworkを導入したり、
QAのためだけに恒常的な親待ち・手動再提出を追加したりしない。

既知のローカル正しさ違反は修正・保留へ戻す。公式ベンチのPASSでも既知の欠陥や
未解消quality holdを免除しない。品質の調査が必要な事実と、未着手の包括coverageは
区別する。新たな具体的な故障根拠がなければ、後者だけで実ベンチへの提出を止めない。
ベンチ成功はcheckerが通した経路の証拠であり、全仕様の証明ではない。

## 採否と実行方法

公式環境でactual candidateを実ベンチにかけ、既存の品質・比較条件・固定採点ルール・
変更資源の復旧を満たしたときに採用する。ローカルmicrobenchは補助資料。
配布された同じcheckerと負荷を許可条件で動かす実ベンチとは区別し、sandboxの結果を
公式登録環境のスコアへ置き換えない。判定ルールv2・最低2サンプル・品質保留は維持する。
ポータルの手動操作が必要かは[当日の規約](REGULATIONS.md)で操作ごとに決める。
この方針は、人間の毎回の採否承認や手動起動を一律に要求しない。

## 回数と残り時間

plugin独自の回数上限は既定で設けない。`MAX_BENCH_PER_EXP`、`MAX_BENCH_TOTAL`、
`MAX_BENCH_PER_HOUR`、`MAX_EXP_PER_HOUR`の`0`はそのscopeでのplugin回数制限なし。
正の明示値は引き続き有効で、結果なし・復旧を含む全物理試行を数える。
公式の回数・時間・同時実行制限は別に守り、`0`で解除されたとは扱わない。

`RECOVERY_BENCH_RESERVE=1`は適用される有限枠にだけ復旧余裕を残す。
無制限のscopeへ新たな枠を作る値でも、公式quotaの追加枠でもない。
有限capが1でreserveも1なら、その枠はstableの復旧確認用となり候補には使えない。
`MAX_EXP_MINUTES=30`、競技終了時刻、最終確認・復旧・cleanupの時間予算は維持する。
回数無制限は同一候補の得点引き直しや、情報価値のない追加走行を勧める意味ではない。

既存configの正の明示quotaは更新で自動変更しない。変更するなら意図と当日制約を確認し、
安定・idleな境界で設定する。quotaだけの変更はstable bundleの比較条件を変えないが、
チーム環境登録はconfig.shのraw bytesを照合するため、既存の登録手順でidle時に再登録する。
identity guardを緩めて変更を通さない。進行中の実験・予約・コマンドは元のpinで終え、
計測coreを実行途中に差し替えない。
