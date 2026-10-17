# Lint導入・検出と実行時間（2026-10-18、0.6.1）

## 結果

Go／Rustとも、通常ビルドが通る誤りを既存Lintで検出し、ソース修正後の指摘解消とテスト合格を確認した。
gofmtの整形差分とClippyのwarningは終了0でもcheck.pyがneeds_reviewとして記録する。
候補提出前の手順をteam規約、prepare-tests／team／experiment skill、候補テンプレートへ組み込んだ。
新しいtask-ready／deployゲートは追加していない。スタイル提案はAIが理由つきで扱う。

## 条件と時間

- macOS 26.6.2、arm64、論理CPU 10。Go 1.24.4、Rust／Cargo 1.98.1、Clippy 0.1.98、rustfmt 1.9.0。
- `tests/fixtures/lint/`の依存なしfixture。Goはログと料金関数、Rustは境界比較関数。
  テストはそれぞれ1件。競技アプリ、EC2、Discord、複数workerの並列性能は対象外。
- Goは専用の空GOCACHE、Rustは専用の空target／build-dirを使う。インストール済みtoolchain・標準ライブラリは保持。
  Rustはoffline、sccache等のwrapperを検証プロセスだけ無効化。利用者の全体設定は変更していない。
- 各言語を直列実行。初回1回、同じソースの再実行3回、小さな正しい修正後1回、指摘の修正後1回。
  以下はformat＋vet／Clippyの2コマンド合計の壁時計時間。Python起動、Git指紋、記録処理を含む。

| 言語 | 初回 | 再実行3回の中央値 | 小さな修正後 | 指摘の修正後 |
|---|---:|---:|---:|---:|
| Go | 2.618秒 | 0.427秒 | 0.361秒 | 0.350秒 |
| Rust | 0.637秒 | 0.426秒 | 0.420秒 | 0.417秒 |

再実行3回の実値: Go 0.455／0.381／0.427秒、Rust 0.436／0.426／0.417秒。
専用キャッシュであっても両言語の標準ライブラリやキャッシュの構造は異なり、同等のcold条件ではない。
小さな異なるfixtureであり、この表からRust／Goの優劣や競技アプリの所要時間を推定しない。
開発PCでの計測で、他プロセスの負荷は固定していない。

## 実際に検出したもの

| 入力 | native結果 | check.pyの結果 |
|---|---|---|
| Goの整形差分 | gofmt -lは終了0、ファイル名を出力 | needs_review、wrapper終了3 |
| Goのslog引数のkey欠落 | go buildは成功、go vetは終了1で検出 | failed、wrapper終了2 |
| Rustの整形差分 | cargo fmt --checkは終了1 | failed、wrapper終了2。整形指摘としてAIが扱う |
| Rustの自己比較distance == distance | cargo buildは成功、Clippyはeq_opで終了101 | failed、wrapper終了2 |
| Rustの不要なreturn | Clippyはneedless_returnを警告、終了0 | needs_review、wrapper終了3 |
| 正しいソースへ修正後 | 両言語でformat・Lint合格 | passed、wrapper終了0 |

修正後のgo test／cargo testも成功した（記録上のコマンド時間は1.230秒／0.878秒）。
修正はharnessが既知の正しいソースへ戻したもの。AIの自律修正速度や、競技の品質保留回収率を測った試験ではない。
all-targetsではlibとtestの診断が重複しうる。指摘件数を不具合件数と同一視しない。

## 起動失敗と反映した知見

初回はPC全体のsccache設定が権限エラーで失敗。次は別設定の共有build-dirへの書込みで失敗した。
専用targetだけでは中間生成物の分離を確認できないため、wrapperとbuild-dirも明示して再実行した。
失敗を消さず機械可読の記録に保持した。成功した試行は38コマンド・12.764秒、先行失敗2試行の
記録範囲は9.307秒／8.360秒。計約30.4秒は実行部分で、実装・原因調査・文章作成時間を含まない。
通常の利用でsccacheを無効化する方針ではなく、設定の確認と隔離が必要という知見。

check.pyは通常checkの終了コード判定を維持し、明示したgofmt／Cargo出力だけを解釈する。
Cargo成功markerの欠落・壊れたJSON・error診断、timeout、実行中のHEAD／ソース変更は合格にしない。
元のcheck JSONは編集せず、AIの対応・保留理由は候補記録へ添える。

## 証拠・再実行・未検証

- [機械可読の実測記録](../validation/lint-20261018.json): 38コマンド、診断、時間、source指紋、
  source／runner hash、起動失敗2試行。配布用コピーはパスを$STUDY／$PLUGINへ置換し、元ログ・recordのhashも保存した。
- 生のcheck JSON・ログ・fixtureのGit履歴はplugin worktreeの`.local/lint-validation-20261018-v3/`。
  先行試行は末尾なし／v2の各ディレクトリ。生成物・キャッシュは追跡しない。
- 再実行: plugin rootで`python3 tests/measure_lint.py --output .local/lint-validation-new`。
  出力先は新しいディレクトリにする。native Go／Rustとfmt／Clippyが必要。サーバーは操作しない。
- 未検証: 競技アプリの依存・規模での初回／修正後時間、並列実行の資源競合、実際に削減できた手戻り時間、最終スコアへの効果。

変更の検証: 43 unit tests、fake-remote通しテスト、shellcheck（error）、変更した3 skillの形式検証、
文書リンク、fixture／runner hashと実測記録の一致を確認した。

運用: [Lint手順](../../team/docs/LINT.md)、[Go／Rustの選択](../../team/docs/RUST_BUILD.md)。
