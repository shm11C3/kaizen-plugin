# Lintを候補提出前に行う

Go／Rustとも既存formatterと静的解析を使う。開始時に既存診断を確認し、実装中は変更した
package／crate、候補提出前は関連範囲へ広げる。ローカルのチェックは共有ベンチ枠を使わない。
toolchain・対象・flagsを記録し、Rustの[キャッシュと時間予算](RUST_BUILD.md)を守る。

## 実行と記録

`K`はplugin root。projectは実際のgo.mod／Cargo.tomlがあるディレクトリにする。
最初に`go version`または`rustc --version`・`cargo --version`・`cargo clippy --version`・
`rustfmt --version`を記録して共有する。使う版・コンポーネントを事前に確認する。

```bash
# Go: 初回は全体。作業中のgofmtの対象は変更ファイルに絞れる。
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT/go" --label lint-format --diagnostics gofmt -- gofmt -l .
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT/go" --label lint-vet -- go vet ./...

# Rust: 作業中は -p PACKAGE で対象crateを選ぶ。提出前は関連targetも確認する。
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT/rust" --label lint-format -- cargo fmt --check
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT/rust" --label lint-clippy --diagnostics cargo -- cargo clippy --locked --all-targets --message-format=json -- --no-deps
```

パスと対象を実際の配置に合わせる。gofmtの`-l`は書換えない。Rustのfmtも必要なら`-p`で絞る。
修正・整形は別途行い、チェック中のソース・HEADは変更しない。formatterによる全面的な無関係差分を避ける。
初回確認後、各候補の最終commitで関連Lint・テストを実行し、task-readyより前に証拠を添える。
統合でソースを変更した場合は、統合担当がその版の関連チェックを再実行する。

`.kaizen/checks/`のJSON・生ログにコマンド、SHA・差分指紋、時間、終了コード、診断が残る。
各コマンドは既定120秒。初回の依存構築などで不足する場合は予算を見て`--timeout`を設定し、
timeoutを合格にしない。Lintも[prepare-tests](../../skills/prepare-tests/SKILL.md)の時間予算に含める。

## 指摘をAIが扱う

| status / wrapper終了コード | 扱い |
|---|---|
| passed / 0 | 対象範囲で実行成功・ソース不変・選択した診断parserで未解決指摘なし。仕様やテスト合格の保証は別途必要 |
| needs_review / 3 | gofmtの整形差分、またはCargoの警告を検出。ネイティブの終了0でも見落とさず、AIが指摘内容を確認する |
| failed / 2 | コマンド失敗・timeout・ソース変化・error診断・Cargo JSONの欠落等。原因を確認して修正／再実行する |

`--diagnostics cargo`には`--message-format=json`が必要。成功したbuild-finishedがない、
JSONが壊れている場合も合格にしない。`processPassed`はプロセス成功とソース不変だけを表す。
parserを指定しない通常checkは従来通り終了コードで判定するため、Clippyには必ず指定する。

- 正しさに関わる指摘は原因確認・修正・再チェックへ戻す。既存の不備も明示して修正する。
  誤検知や意図した実装なら根拠を残し、必要な箇所だけ抑制する。実行できない検査は不足として残す。
- スタイル提案は競技時間と変更リスクで判断する。候補に指摘コード・理由・対応／保留を記録し、
  元のcheck JSONは編集しない。needs_reviewを一律の不採用や人間待ちにしない。
- 全警告の一律エラー化やpedantic／restrictionの一括導入は初期要件にしない。
  性能提案は仮説としてベンチで確認し、DB整合性・仕様は再現テストと公式checkerで確認する。

これは候補提出手順と証拠の補助で、task-readyやdeployに新しい機械的なゲートは追加しない。
実行時間と検出例は[Lint実測](../../knowledge/lessons/20261018-lint-validation.md)を参照する。

一次資料: [gofmt](https://pkg.go.dev/cmd/gofmt)、[go vet](https://pkg.go.dev/cmd/vet)、
[Clippy](https://doc.rust-lang.org/clippy/usage.html)、
[Cargo JSON](https://doc.rust-lang.org/cargo/reference/external-tools.html#json-messages)。
