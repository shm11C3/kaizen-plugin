# 実戦の短い入口

目的は制限時間内の最終有効スコア。練習・本番とも、方向性を検討し、変更を小さく速く
実装し、既存の検証・実ベンチから速くフィードバックを得る。以下から始め、詳しい文書は
該当操作の前に開く。一括の読書・全員レビュー・段階ごとの承認待ちを初動に置かない。

## まず参加して根拠へ進む

1. 人間のpractice/competition、終了時刻、除外事項、対象repo・host-config、連絡先を確認する。
   変更途中の既存環境は保護し、練習は本番harnessの専用forkと独立した台帳・targetで行う。
2. 実際のGitHub loginと一意のセッションIDを使い、teamスキルのjoinを一度通す。
   `joined: true`を確認する。別環境ではjoin/controlへ同じhost-configを指定する。
   Discord等の読取・投稿は別に疎通確認し、最新の方針・停止指示・議論を自分で読む。
3. `control.py queue`と既存の観測根拠を確認する。関連する仮説と担当を照合し、原子的に
   taskを取得する。環境未設定なら統合担当がsetupし、他の担当は独立したソース調査を進める。

## 続けるための境界

- 台帳が担当・環境占有の正本。会話やAssigneeは通知。コードはGit、実測・採否はkaizen記録。
- 一つの可変worktreeは一担当。調査・実装・関連QA・commit・READYまで完了単位で進める。
  主セッションは調整と速い応答を持ち、長い独立作業はnative SubAgentへ委譲できる。
- deploy、観測設定、benchmark、採否、復旧は予約ownerだけが既存target/script経由で行う。
  予約は時間で失効しない。常駐integratorがあれば二重に環境を取得しない。
- baselineと実際の統合SHAを同条件で比較する。既知の正しさ違反・未解消quality holdを
  PASSで免除しない。失敗は再現・原因・修復案を調べ、修復または根拠ある見切りへ進める。
- 合意した範囲で正しく、比較可能で、復旧を確認した改善は通常の評価に従いAIが採用する。
  未検証はAIの作業。合意を超える目的・権限・不可逆操作・重大な残余リスクだけ人間へ渡す。
- 約1分を目安に新着と停止・方針変更を確認し、queueのREADY/保留/feedbackも見直す。
  履歴の欠落・未読を確認済みにしない。資格情報は会話やGitへ出さない。
- 人間の停止・freeze・期限を守る。新規投入を止め、実行中処理を確認し、必要ならstableへ
  復旧して状態・証拠を報告する。最終確認・復旧時間を残す。レトロは必要時・依頼時に行う。

## 必要になったところだけ開く

| 次の操作 | 読む手順 |
| --- | --- |
| join/接続で止まる | [ONBOARDING](ONBOARDING.md) |
| 初期コード・環境・baselineを用意 | [setup](../../skills/setup/SKILL.md)、[当日の規約](REGULATIONS.md) |
| 候補を選ぶ・準備する | [STRATEGY](STRATEGY.md)、[prepare-candidate](../../skills/prepare-candidate/SKILL.md)、[VALIDATION](VALIDATION.md) |
| 長い作業を分担する | [PIPELINE](PIPELINE.md) |
| deploy/計測/採否/復旧・交代 | [POLICY](../POLICY.md)、[OPERATIONS](OPERATIONS.md)、[RUNBOOK](RUNBOOK.md)、teamスキルのIntegration |
| 会話と判断を共有する | [DISCORD](DISCORD.md) |
| 人間の運用助言・反復作業を反映 | [WORKFLOW](WORKFLOW.md) |

setup、target操作、採否のガードはこの入口で省略しない。新しい管理実装やCodex hook、
自動メッセージ捕捉が追加されたわけではない。規約や具体的な判断に迷ったら[POLICY](../POLICY.md)へ戻る。
