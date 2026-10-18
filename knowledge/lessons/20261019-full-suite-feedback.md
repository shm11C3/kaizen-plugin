# 既存テスト・Lint一式の方針と常駐QAの引き継ぎ

2026-10-19。PR #1のレビュー不具合修正は別セッションが担当し、このブランチはユーザーのFBと統合後QAだけを含む。

## 取り込むもの

- ブランチ: `shm11C3/tooling/full-suite-feedback`
- 基準: `b5a6c82`（既存integrator + main 0.9.0 + installerの既存修正）
- 実装: `ea66aa0`（既存suite方針・配備前QA）と `f863227`（未分類警告のAI調査）
- PRブランチ・main・別セッションの未コミット変更は更新していない。
- 回数0、手動結果binding、正しさreject、占有、復旧、dashboard、installerのレビュー修正は本差分に含めない。
  別セッションの修正へ本差分だけを取り込む。ローカル参照branch `shm11C3/fix/pr1-validation`は引き継ぎ対象ではない。

```bash
git cherry-pick ea66aa0 f863227
```

衝突時はintegrator.py全体を置き換えず、`run_checks` import、DEFAULTSの`checks`、
`check_candidate()`と「actual compose / manifest記入の後・target deployの前」の呼出しを採用する。
別セッションのmanual予約・再開・source照合・品質保留の修正を保持する。既存manual候補を
再開するときは配備前QAを終えた同じ候補・attemptを継続し、予約や物理枠を追加消費しない。

配備エラーだけを模擬するunit fixtureでは`check_candidate`も成功としてmockし、
そのテストのsubprocess mockにnative QAを巻き込まない。本体の接続は
`tests/test_integrator_checks.py`で別途実際に動かして確認する。

## 最終方針

既存テスト・formatter/Lint一式は実行を基本とする。実測で重いものだけ範囲・頻度・並列実行を
調整し、秒数、cold/warm、build重複、未実施範囲・理由を残す。新coverage、race、独立/LLMレビューの
追加は別判断とする。既存実測を初めからfocusedだけへ狭める根拠にはしない。

setupでGo/Rustの既存コマンドを`integrator.json`の`checks`へ登録する。
[設定例](../../README.md#candidate-checks)と[運用方針](../../team/docs/VALIDATION.md)を参照。
空配列は未設定・未実施として残し、PASSを作らない。既存設定は自動で書き換えない。
LLM reviewの新配布例はnone、既存llm設定は維持する。

既存`check.py`を再利用し、actual candidate SHAの隔離worktreeで全設定checkを実行する。
途中で失敗しても残りを実行し、JSON・生ログ・実行時間・source SHAを一意のpathへ保存する。
blocking失敗は候補を配備せずinconclusive記録・品質保留へ戻す。明示したstyle advisoryの
原結果は保持し、非advisoryの未分類警告はwarning保留で担当AIが調査する。compiler error、
source変更、実行不能・不完全な診断はadvisoryで免除しない。人間の毎回の承認は追加しない。

Rustは未設定時のCARGO_TARGET_DIRをstate/check-cache/cargoへ置いて候補間で再利用する。
既存のCargo/Go cache設定を保持し、QAのためのclean buildを一律に要求しない。

## 検証

検証した実装SHA: `f863227e76f0bd8f0e0579313d4c2df96d746429`。後続はこの引き継ぎ文書だけの追加。

| 検査 | 結果 | wall seconds |
|---|---|---:|
| python3 -m unittest discover -s tests -v | 146件成功 | 135.823 |
| bash tests/run.sh | 全件成功 | 51.361 |
| Python compile / 全tracked shell構文 / plugin・template JSON / diff whitespace | 成功 | — |
| 変更Markdownの相対リンク | 93件存在確認 | — |

追加ケースでは全check実行、失敗後の継続、actual SHA、元source不変、失敗証拠の保持、
advisoryの原結果保持、未分類警告のAIへの返却、compiler errorのadvisory免除拒否、
配備・候補ベンチなしの品質保留、Cargo cacheの継続を確認した。

raw log SHA-256:

- Python: `618efaec3bc47a92ed817e8062380bb5e157d7e901305049dd736629f6d42b26`
- shell: `803a6832e67d3bb8c468c0889ea972c0275b97e1241f0a4e04443b58c75ad404`

原本はこのworktreeの`.local/feedback-validation-final/`にJSON receiptと共に保存している。
Go/Rustアプリの一式そのものや実EC2・Bedrock・実ポータルは今回動かしていない。
nativeコマンドはPython fixtureで再現し、配備/ベンチは隔離したfake targetを用いた。
別セッションの最終レビュー修正と合流した後は、その実際のsnapshotで全suiteを再確認する。
