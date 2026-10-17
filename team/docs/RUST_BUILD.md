# Rustのビルド時間を改善サイクルに含める

候補の費用は実装だけでなく、check・テスト・コンパイル・リンク・転送・起動・ベンチ・復旧まで。
Rust採用時はsetupで所要時間を記録し、planの候補順位と最終検証枠に反映する。

## 最初に残す記録

初回ビルド、同じソースの再ビルド、小さな修正後、stableへの復旧を区別する。
setupの配備・復旧ドリルを使い、毎候補で全条件をやり直さない。初回条件を追加確認する場合も
別の一時targetディレクトリを使い、稼働中のキャッシュを`cargo clean`で消さない。
手元の変更なしビルドだけでは、Git export・同期後の再ビルド時間は分からない。

- ソースSHA、Cargo.lock、rustc／Cargo版、OS・CPUアーキテクチャ・target triple・libc。
- profile、features、RUSTFLAGS、linker、jobs数、targetディレクトリ、キャッシュの状態。
- 実行コマンドと壁時計時間、`cargo build --release --locked --timings`のレポート。
  コンパイル・リンク・依存取得・ロック待ちのどこが支配的かを確認する。
- 実際のdeploy／recover全体の時間。現行deployは各app hostでBUILD_CMDを実行し、復旧も再ビルドする。

## 毎回の作業

ローカルでは`cargo check --locked`と変更に関係するテストで早く誤りを見つけ、候補確定前に
採用時のrelease profileでも必要なテストとビルドを通す。checkはコード生成・リンクを確認しない。
debug／計装入りのスコアを採否に混ぜず、baselineとcandidateのビルド条件を揃える。
`scripts/check.py`で所要時間とソースの証拠を残せる。終了するまで同じ作業領域を変更しない。

Cargoのダウンロードキャッシュと作業領域ごとの`target/`を維持する。
deployは`rsync --delete`なので、通常のRust配置ならpresetの`SYNC_EXCLUDES`に
`--exclude target/`を指定し、受信先のビルド出力を消さない。別のCARGO_TARGET_DIRを使う場合は
実際の場所・所有者・保持を確認する。生成物はGitへ入れない。
並列workerはそれぞれの作業領域でビルドし、共有targetディレクトリのロック待ちや
CPU・メモリ競合を避ける。check・事前ビルドは対象予約前に並列で行えるが、対象ホスト上の
ビルドは既存のtarget wrapperと予約の内側で行い、他候補の計測と重ねない。

toolchain・features・flags・profileをむやみに切り替えず、意図しない依存更新を`--locked`で防ぐ。
これはネットワーク禁止ではない。`--offline`／`--frozen`は必要な依存が揃い、実行できると確認して使う。

## 遅い場合と終盤

既存の[sccache](https://github.com/mozilla/sccache)も選択肢。導入費用、実際のhitと総時間で判断する。
リンクが必要なcrateやincremental compilationにはキャッシュの制約があるため、導入だけで
高速化したと扱わない。releaseのincrementalは既定で無効。LTO、codegen-units、incremental、
linkerの変更はビルド時間と実行性能を比較し、一律の高速化設定にしない。

事前生成したバイナリの配備を追加するなら、ソースSHA・成果物hash・ビルド条件を結び、
対象OS／arch／libc／CPUへの適合と復旧を検証する。現行deployにビルド省略機能があるとは扱わない。
終盤は実測したビルド・復旧時間に余裕を加えて新候補の受付を止める。
依存追加や全体再ビルドを伴う変更は、その残り時間で検証と復旧まで終わるかで判断する。

一次資料: [cargo build](https://doc.rust-lang.org/cargo/commands/cargo-build.html)、
[profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)、
[build cache](https://doc.rust-lang.org/cargo/reference/build-cache.html)。
