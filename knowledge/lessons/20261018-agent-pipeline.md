# 主Agent内の候補準備とREADY提出

mode: practice。汎用手順は0.8.0のPIPELINE/prepare-candidateへ反映し、ISUCON14固有の施策は
ここに残す。[独立した証跡](https://github.com/shm11C3/kaizen-agent-pipeline-validation-20261018/blob/main/REPORT.md)。

実native SubAgent A/Bを独立worktreeの単一writerとし、仮説の調査から関連QA・commit・
READY資料まで委譲した。Aの実装/QAとBの調査の明示区間は17.465秒重なった。
準備window全体の重なり40.498秒は未記録区間も含むため、実作業の重なりと混同しない。
A QA中にBが実装するところまでは初回では確認していない。

主AgentがREADY資料を台帳へ転記する構成では、資料完成後に146秒/83秒かかった。
同一人間開始セッション内の明示委譲でtask-stage/task-readyだけを担当SubAgentへ渡す
手順へ変更した。既存SHAとQA資料を使った別の提出機能試験は0.151秒/0.084秒で台帳へ
記録された。接続・権限が利用できない場合は機械可読packageの一括転記へ戻す。
公平な時間比較や競技の得点効果は未測定。台帳記録前の待ちも観測しないと、queueが
空だったと誤解しやすい。親受信時刻・純idle・実行環境のavailabilityはunknownとした。

初回は合成完了からQA開始にも146.563秒かかり、主Agentがプラグイン文書整備を
続けていた。統合担当にも合成→actual SHAの関連QAまでを1つの完了単位で渡す手順へ
補強した。別worktreeで既存2案を実際に合成し、直後にnative/gofmt/vetを実行する
機能再試行は1回のorchestration・2.462秒で完了した。合成完了から実native command開始
までは0.071秒。元sourceとtreeが一致する別SHAを検証し、途中の親指示待ちは挟んでいない。
既知候補を使う機能試験で、競技の時間短縮率や新たな得点改善ではない。初回の遅延記録は残す。

## ISUCON14固有の実コード

base `173f9cf4e0f026d0860ccc036f8b6782609ef508`から、AはminimumCostMatchingの
行ごとのscratch再割当を呼出し内再利用へ、BはassignMatchingChairsのmatrix backingと
known/unknown partitionを連続領域へ変更した。共有キャッシュやgoroutine間共有は追加しない。
独立した長方形oracle288入力を含む関連テストでknown優先・unknown fallback・oldest選択を確認。

両案は同一ファイルの別関数を変更するため、合成blobはどちらの提出とも一致しなかった。
worker結果をそのまま合成sourceの証明にせず、実SHA
`541e1801e6d1f717867d258bd2b97a4fd0efd28a`へ再提出し、同じsourceでnative/gofmt/vetを通した。
この照合はgo/sqlを明示したlocal path-scope fixtureで、実deploy資源bundleの証明ではない。

Go1.24.4/darwin arm64/Apple M4、warm cache、各size3走のlocal microbenchで、
20/100/500 chairsの割当回数は61/63/65から各11 allocs/opへ減った。
ns/op中央値は6322/22861/106878から5489/21632/101505。
ホスト上の他処理・同一負荷での対照なし・少数sampleのため、runtime差の一般化や
アプリthroughput・競技スコア改善は主張しない。MySQL/HTTP/EC2では未検証で、競技sourceへ
自動採用していない。固有コードは検証repoのsource refsへ保存する。

## 継続する境界

実SubAgentの数より、明確な完了条件・単一writer・必要なQA・共有可能なREADY・
現在のqueueを優先する。stage観測を必須ゲートにせず、stageの秒数を品質証明に使わない。
後のclean計測で古い品質保留を消さず、失敗・修正・再検証のsource対応を維持する。
公式統合・対象環境の排他・採否は既存手順を使う。Discord接続・native install/reload・
競技全体の時間短縮はこの練習では未検証。
