# 既存Lintを実行し、重い検査を実測で調整する

Go／Rustとも既存formatterと静的解析一式の実行を基本とする。[検証方針](VALIDATION.md)に従い、
まず時間を測り、重いと確認できた検査だけpackage/crate・頻度・並列実行を調整する。
既存suite実行と新しいLintルール導入・独立レビューは別判断とする。
ローカルのチェックは共有ベンチ枠を使わず、整形・styleの助言だけで提出を止めない。
toolchain・対象・flagsを記録し、Rustの[キャッシュと時間予算](RUST_BUILD.md)を守る。

## 実行と記録

`K`はplugin root。projectは実際のgo.mod／Cargo.tomlがあるディレクトリにする。
最初に`go version`または`rustc --version`・`cargo --version`・`cargo clippy --version`・
`rustfmt --version`を記録して共有する。使う版・コンポーネントを事前に確認する。

```bash
# Go: 既存module全体を基本とする。
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT/go" --label lint-format --diagnostics gofmt -- gofmt -l .
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT/go" --label lint-vet -- go vet ./...

# Rust: 既存workspace/target設定を使う。既存featuresに合わせ、all-featuresは追加しない。
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT/rust" --label lint-format -- cargo fmt --all -- --check
python3 "$K/scripts/check.py" --project "$KAIZEN_PROJECT/rust" --label lint-clippy --diagnostics cargo -- cargo clippy --workspace --all-targets --message-format=json -- --no-deps
```

パス・flagsは既存project設定へ合わせる。gofmtの`-l`は書換えない。
修正・整形は別途行い、チェック中のソース・HEADは変更しない。formatterによる全面的な無関係差分を避ける。
検査は候補のimmutable commitで実行し、task-ready時に実際の証拠を添える。
cold/warm・compile重複と実行秒数を記録し、重い検査を絞った場合は未実施範囲と理由も残す。
統合でソースを変更した場合は、その版の既存suiteを基本に再検証する。

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

- 正しさに関わる指摘は原因確認・修正・再チェックへ戻す。既知の不備をベンチPASSで免除しない。
  誤検知や意図した実装なら根拠を残し、必要な箇所だけ抑制する。実行できない検査は不足として残す。
- スタイル提案は競技時間と変更リスクで判断する。候補に指摘コード・理由・対応／保留を記録し、
  元のcheck JSONは編集しない。advisoryなneeds_reviewを一律の提出停止、不採用、人間待ちにしない。
- 全警告の一律エラー化やpedantic／restrictionの一括導入は初期要件にしない。
  性能提案は仮説としてベンチで確認し、DB整合性・仕様は再現テストと公式checkerで確認する。

既存Lint一式の実行と、raceや新規の独立/LLMレビュー追加は分ける。
既存checkを常駐integratorへ登録すると、配備前に全設定チェックを実行する。
明示したstyle advisoryは継続できる。非advisoryの未分類警告はwarning保留へ戻し、担当AIが調査する。
compiler error・source変更・実行不能はadvisoryでも免除しない。人間の毎回の承認は要求しない。
実行時間と検出例は[Lint実測](../../knowledge/lessons/20261018-lint-validation.md)を参照する。

一次資料: [gofmt](https://pkg.go.dev/cmd/gofmt)、[go vet](https://pkg.go.dev/cmd/vet)、
[Clippy](https://doc.rust-lang.org/clippy/usage.html)、
[Cargo JSON](https://doc.rust-lang.org/cargo/reference/external-tools.html#json-messages)。
