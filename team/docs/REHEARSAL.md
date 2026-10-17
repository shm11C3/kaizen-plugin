# ISUCON14チーム検証からの反映（0.3.0）

この文書は0.3.0開発時の検証履歴である。親Agentの補助はその試験での条件であり、
本番手順の前提ではない。現行は各人の独立セッションが[Discord](DISCORD.md)で連携する。

[2026-10-17の実測記録](https://github.com/shm11C3/isucon-team-rehearsal/blob/2de6f3fd6d0408d9249838997733fc48083b462a/reports/verification.md)では、3cloneでの調整・2候補・12回の実ベンチ・元環境復元を確認した。Claudeモデルの実作業、異なる3人の認証、Discordは未確認。

| 気づき | plugin側の対応 |
|---|---|
| 親Agentが導入・環境分離を補助した | join.py、release整合、host-configのDB/targetパス、targetのknowledge_dir |
| コードを戻しても追加indexが残る | stable bundle、明示restore/probe、SQL/config変更の事前拒否、復旧失敗時のpending維持 |
| pass/scoreだけだとAをpromoteする | rule-v2、error種別・分母・率、未知の品質と正しさを上書き不可 |
| Bはbaselineのばらつきと重なる | 同じ候補・bundle、最小サンプル、古いbaseline除外、ノイズ条件の維持 |
| 調査不足まで人間待ちになった | NEEDS_MEASUREMENT/task-resume、NEEDS_HUMANの具体的question |
| experiment終了後に復旧benchが上限外になった | 永続する物理試行台帳、終了後も同じ実験へ帰属、総数/時間/復旧枠、portal開始前予約 |
| 直列計測の前に候補が溜まり得る | queueの件数と助言、READY滞留時にログ解析・調査へ回る運用 |

次の実地確認は各人の実PC・native Claude/CodexでjoinとDiscord疎通を通し、各セッションが方針・関連スレッドを読み、通常改善1件を共有・自動採用してmainへ反映する。投稿の配送と新着でのAI起動は別々に検証する。Botや自動wakeが追加済みとは扱わない。

## この更新の検証

- 偽2ホストの通し試験で、通常promote、品質不明候補のpromote拒否（人間参照があっても拒否）、DB状態の残存検出、復旧失敗、portal予約・中断・回数保持を確認。
- Python 19テストで、調整・旧台帳の追加migration・異なる環境パス・knowledge分離・error分母・ノイズ・古いbaseline・物理予算を確認。
- Codex CLIでソースを送らない小さなモデルprobeが成功。offline joinは構成とcloneを確認し、joined=falseを維持。
- skill YAML、manifest JSON、shellcheckのerror検査を通過。既存のdescriptionの引用符不足は文字列の内容を変えず修正。

この更新版を共通EC2へ配備しての再走行、native Claudeのモデルprobe、実PC3台の参加は未実施。

## 更新時

既存のsource・knowledge・plugin identityは保持する。稼働中のreleaseを無断で差し替えず、占有・実行中処理なしを確認してメンバーと共通ホストを同じ版へ揃える。0.2.0のschema/config復旧とbaselineをそのまま信用せず、RECOVERY手順で再ドリルする。SQLiteは既存task/eventを保持し、新しいmember表とhuman_question列を追加する。
