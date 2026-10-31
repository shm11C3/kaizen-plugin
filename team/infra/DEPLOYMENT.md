# 共通ホストの構築記録

2026-10-17にSSM経由の共通ホストを構築し、GitHub clone、SQLite台帳、排他・引継ぎ・解放の操作を確認しました。公開版では実AWSアカウント、リソースID、Discord ID、deploy key IDを設定例から除いています。過去のGit履歴には当時の運用情報が残ります。秘密鍵・認証トークンは含めません。

## 自分の環境で残す情報

構築時は次をチーム内の非公開記録へ保存してください。

- AWS account、region、EC2/VPC/subnet/Security Group/EBSのID
- インスタンスタイプ、AMI、暗号化・IMDS・SSMの設定
- 競技用・plugin用リポジトリ、deploy key IDと権限
- 固定したplugin SHA、実行した検証と結果
- 台帳・対象設定・artifactの保存先、バックアップと復旧方法

初期構成はt3.small、gp3 30GiB、SSMのみの接続、inboundなしです。SQLiteとartifactはEBS上に保存します。作成・初期化・停止手順は[README](README.md)を参照してください。実際の料金・権限・保持期間は利用環境に合わせて確認します。

検証記録はfixtureや特定時点の接続実績です。新しい環境では、その環境に対する疎通・排他・復旧の確認を行ってください。
