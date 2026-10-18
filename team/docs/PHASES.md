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

### 実DBを使うGoテスト

実DBが必要なGo fixtureは環境を占有し、`target.py check-remote`を使える。
取得済みの完全commit SHAから`--module go`と明示した`--include`だけをexportし、
localでCGO無効・Linux/amd64向けに`go test -c`する。モジュールとincludeは対象presetの
`LOCAL_SYNC_PATHS`内に限定する。test binaryとincludeだけを所有app hostの
`/var/tmp/kaizen-check.*`へ転送し、テスト後にその一時ディレクトリだけを削除する。
アプリの配備先・サービスを変更する操作ではない。Rustや別architectureには未対応。

```bash
python3 "$K/scripts/team/target.py" --db /path/team.sqlite3 --config /path/lane-a.json \
  --environment lane-a --agent MEMBER --token TOKEN \
  check-remote --ref FULL_COMMIT_SHA --label regression --module go \
  --include sql/1-schema.sql --env-file /path/test-env.private.json --test 'TestContract'
```

env-fileは環境変数名→文字列値のJSON map。値はSSH commandへ埋め込まずstdinで渡し、
記録はkey一覧とhashだけを持つ。env-fileと出力はprivateに保持する。接続DSNやSQLパス、
対象問題の再現手順は練習ナレッジへ置き、共通pluginに問題固有の管理接続を固定しない。

**fixture自体が隔離schemaの作成・削除とcleanupを守ることが前提**。実行前に対象refを読み、
既存アプリDBへの書込・DROP・USE切替がなく、一意な一時schemaだけを操作することを確認する。
このwrapperはテストコードのSQL安全性を自動証明しない。必要な管理権限はtest用host内に限定する。

`.kaizen/checks-remote/`へsource commit/tree、binary/include hash、Go版、時間、native exit、
ログとcleanup結果を残す。失敗した旧版はfailedのまま保持する。test無し・binary無し・
選択0件は成功扱いにせず、skipも別記録にする。選択したテストの成功だけで公式ベンチの
品質・性能や、テスト範囲外の正しさまで確認できたとは扱わない。

## 変更容易性を整える

同じ密結合が候補修正を妨げているなら[refactor](../../skills/refactor/SKILL.md)を使う。
次に進める候補を名指しし、直接修正と小さな構造変更を比較する。単なる読みやすさの整理へ広げない。
構造変更と性能変更は別commitにし、契約テストで境界を守る。単独の改善が未確認の前提変更は、
それだけを性能改善として採用せず、必要な組合せ候補を明示して測る。
実証済みで合意した制約内の改善はAIが採用し、構造変更だけで承認待ちにしない。
合意を超える具体的な選択は[人間判断方針](../POLICY.md#adoption-and-human-judgment)に従う。

`team/templates/PHASE.md`をplan／タスクに添え、時間上限、依存候補、期待する節約、打切り条件を決める。
終了時は実際の壁時計時間・並列作業・check参照・候補SHA・ベンチ・後続修正の所要時間を記録する。
テスト数やtrace数を成果指標にしない。比較実験なしに因果効果を断言しない。
直接修正で済む、次の有力候補がない、時間内の回収が見えない場合は延期または直接修正する。

[ツール・観測モード](TOOLS.md)、[並列検証・品質保留](PARALLEL_QUALITY.md)、
[実験選択](STRATEGY.md)、[Discord手順](DISCORD.md)を併用する。
