# テスト・観測・整備へ時間を使う

最終有効スコアのために準備フェーズを置ける。全員一斉停止の固定日程や定期的な全面リファクタは設けない。
Go／Rustで同じ判断基準を使い、準備費用も8時間に含める。最終検証枠を先に残す。
Rustでは[ビルド時間](RUST_BUILD.md)も準備予算に含め、実際のdeploy／recover時間から終盤の枠を残す。

## 初期テスト

独立した担当が、契約テスト、既存ツールと計測、採点経路の調査を並列で行う。
共有環境の変更・観測・ベンチは単一予約を守る。テスト完成まで実装を全面停止しない。
[prepare-tests](../../skills/prepare-tests/SKILL.md)で、仕様・checkerから初期化・権限・集計・
状態遷移・永続性・並行実行など予定する改善が壊しうる契約を守る。現実装の誤りを正解にしない。
実DBが必要なもの、未実行、skip、依存不足を区別する。品質保留は再現→修正→再計測へ戻す。
[Lint手順](LINT.md)も同じ準備予算に含め、開始時の既存診断と候補提出前の関連検査を記録する。

既存の言語ツールを使う。`scripts/check.py`は実行証拠を残す補助:

```bash
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT" --label regression --timeout 120 -- go test ./...
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT" --label regression --timeout 120 -- cargo test
```

projectにはgo.mod／Cargo.tomlのあるディレクトリを指定する。`.kaizen/checks/`にログとJSONを保存する。
通常checkは終了0かつ実行中のソース変化なしが`passed`。Lint用parserを指定した場合は指摘も判定し、
終了0でも`needs_review`になりうる。テスト内容の十分性や公式checker合格は別途必要。
wrapper成功にskipを隠さない。成果物は追跡対象から除外し、到達可能なartifact参照で共有する。

## 変更容易性を整える

同じ密結合が候補修正を妨げているなら[refactor](../../skills/refactor/SKILL.md)を使う。
次に進める候補を名指しし、直接修正と小さな構造変更を比較する。単なる読みやすさの整理へ広げない。
構造変更と性能変更は別commitにし、契約テストで境界を守る。単独の改善が未確認の前提変更は、
それだけを性能改善として採用せず、必要な組合せ候補を明示して測る。大きなリスク・曖昧な採否・
トレードオフは既存の人間判断方針に従う。

`team/templates/PHASE.md`をplan／タスクに添え、時間上限、依存候補、期待する節約、打切り条件を決める。
終了時は実際の壁時計時間・並列作業・check参照・候補SHA・ベンチ・後続修正の所要時間を記録する。
テスト数やtrace数を成果指標にしない。比較実験なしに因果効果を断言しない。
直接修正で済む、次の有力候補がない、時間内の回収が見えない場合は延期または直接修正する。

[ツール・観測モード](TOOLS.md)、[並列検証・品質保留](PARALLEL_QUALITY.md)、
[実験選択](STRATEGY.md)、[Discord手順](DISCORD.md)を併用する。
