# 構築記録

2026-10-17（Asia/Tokyo）に構築。

| 項目 | 値 |
|---|---|
| AWS account | `521390384516` |
| Region | `ap-northeast-1` |
| EC2 | `i-006f0637c33d1d766` |
| Name | `isucon-competition-control` |
| Type | `t3.small` / 2 vCPU / 2 GiB |
| AMI | `ami-0c1e0061f931b36f8` / AL2023 2023.12.20261016.0 x86_64 |
| VPC / subnet | `vpc-0599aa584eabb7604` / `subnet-031099c9c2353a28c` |
| Security Group | `sg-0f8a6244913dd40ec` / ingressなし |
| EBS | `vol-0d6078593815dfe9e` / gp3 30 GiB / encrypted |
| Instance profile / role | `isucon-competition-control-ssm` |
| Attached policy | `AmazonSSMManagedInstanceCore` |
| Metadata | IMDSv2 required / hop limit 1 |
| CPU credits | standard |
| Access | SSM Online / inbound SSHなし |
| Repository | `shm11C3/isucon-competition` / Private |
| Repository deploy key ID | `166751939` / write |
| Plugin deploy key ID | `166751941` / read-only |
| 初期構築時のPlugin revision | `187200363e980f208b64040537e6357384604da3` |

## 検証

- 初回commit `3977fc2101066242e7f56cae864ca790a33d6250` をGitHubと共通ホストへ配置。
- ローカルとEC2内で `python3 -m unittest discover -s tests -v` の6項目が成功。同時claim、永続占有とtoken更新、実行中の解放拒否、人間判断参照、対象未設定時の拒否、占有下の対象操作を確認。
- EC2内のclone・plugin固定・テスト・台帳初期化のSSM Command ID: `b4dc18a9-a010-4858-b3a9-5c8bb9f2c7a0`（Success）。
- 各PC用 `control.py` の実際のSSM経路で、占有取得、別担当の取得拒否、引き継ぎ、旧tokenの拒否、対象未設定時の拒否、解放を確認。最終状態は占有なし・タスクなし。
- 共通ホストからGitHubへの `git push --dry-run origin main` が成功。ローカル・GitHub・共通ホストのmainを同期。
- 既存の練習用EC2、既存Security Group、既存VPC経路は変更していない。

## 現在の対象設定

競技用リポジトリは最小の起動案内だけを持ち、ソースは未投入。競技対象サーバー・ベンチ・デプロイpreset・Discord連携は未設定。通常の対象操作は無効。競技開始時に [RUNBOOK](../docs/RUNBOOK.md) で初期化する。

初期構築時には当日用リポジトリへ管理コードを置いていたが、利用者の方針に合わせてプラグイン側へ移動。共通ホストの管理コードは `/srv/isucon/kaizen-plugin/scripts/team`、台帳と対象有効化設定は `/srv/isucon/state` に配置する。EC2・SSH鍵・台帳を作り直さず、競技用cloneから管理コードへの依存を除く。

移行時の実装SHAは `7cb84b824d6d32246a4fcb56e3116ccc686cb9ad`（plugin 0.2.0）。SSM Command `e281c93b-00ce-4674-9438-87db8c28090b` でEC2内の6項目が成功。台帳を `/srv/isucon/state/team-before-plugin-move.sqlite3` にバックアップし、同じ占有をプラグイン側クライアントから確認。対象有効化設定はfalse、両SSH秘密鍵はisucon所有・権限600を維持。

チームメンバーのGitHub・AWSアクセス追加、Discord接続、予算アラートの金額と通知先、終了時刻とfreeze時刻は、実際の参加者・競技情報に合わせて設定する。

## 接続・停止

```bash
python3 "$K/scripts/team/control.py" status
python3 "$K/scripts/team/control.py" shell
aws ec2 stop-instances --region ap-northeast-1 --instance-ids i-006f0637c33d1d766
```

EC2は構築後も起動した状態で引き渡す。停止前に実行中処理・占有・記録を確認する。EBSの料金は停止後も続く。認証用の秘密鍵・token・AWS credentialsはこの記録に含めない。
