# メンバーの参加手順

当日は競技用リポジトリをcloneし、各メンバーがkaizenをインストールします。運用規約・管理コマンド・テンプレートはプラグインが持ちます。競技用cloneへコピーしません。

Git、Python 3.9以上、AWS CLI v2、使うエージェントを用意します。Privateの競技用・プラグイン用リポジトリと、共通ホストへのSSM権限が必要です。AWSは各自の認証を使い、共有しません。

```bash
git clone https://github.com/shm11C3/isucon-competition.git
cd isucon-competition
```

## Claude Code

```bash
claude plugin marketplace add shm11C3/kaizen-plugin
claude plugin install kaizen@kaizen-plugin
claude
```

新しいセッションで `/kaizen:team` を実行します。競技用cloneの `CLAUDE.md` は短い `AGENTS.md` を取り込み、実際の運用はteamスキルへ委ねます。

## Codex

```bash
codex plugin marketplace add shm11C3/kaizen-plugin
codex plugin add kaizen@kaizen-plugin
codex
```

新しいセッションで「kaizenプラグインのteamスキルで参加。セッションIDはa-codex-01。課題発見・取得・実装・検証・候補提出・次の作業まで自走」と指示します。`.codex-plugin/plugin.json` と `.agents/plugins/marketplace.json` がClaudeと同じ `skills/` を参照します。現在のhook adapterはClaude用です。

## コマンドと接続

teamスキルからプラグインの実パスを確認し、それを `K` とします。プラグインは競技用cloneとは別のインストール先にあります。

```bash
python3 "$K/scripts/team/join.py" --project "$PWD" --agent a-codex-01 --provider codex
# Claude: --provider claude
# 必要な場合だけ --model MODEL。global設定は変更しない。
python3 "$K/scripts/team/control.py" status
python3 "$K/scripts/team/control.py" queue
```

`joined: true`が参加完了です。joinは空の一時ディレクトリで小さなモデル応答を検査し、ソースを送りません。認証・モデル・Git・SSM・共通ホストとのplugin版のどこで止まったかを返します。再ログインや設定の自動変更は行いません。`--offline`はファイル確認だけです。CLI版と既存cacheも含め、当日使う各人のPCで通常のjoinを通してください。

0.3.0導入時はメンバーと共通ホストの版を揃えます。競技中の自動更新は行いません。共通ホスト管理者が占有なし・実行中なしを確認して固定releaseへ更新し、[復旧bundle](RECOVERY.md)を作り直します。

`team/environments/competition/control-host.json`とAWS accountが異なれば止まります。別profileは各自の `AWS_PROFILE` で指定します。台帳と対象操作はSSM Run Commandなので、Session Manager pluginは不要です。対話shellにはSession Manager plugin、またはAWSコンソールを使います。

別環境はhost-configの`state_db`と`target_config`を両方指定します（省略時は従来のcompetitionパス）。検証ではtarget.jsonの`project`・`plugin_root`・`knowledge_dir`も専用領域へ向けます。dispatch adapterは不要です。台帳だけを分けて本番targetを参照してはいけません。`join.py`と後続の`control.py`には同じ`--host-config`を渡してください。

指定したknowledge_dirが未作成なら、最初の占有下のtarget呼出しでpluginのcorpusを専用領域へコピーします。以後その領域の記録を保持し、pluginのseedを上書きしません。既存の不完全なディレクトリは上書きせず拒否します。

共通ホストでは `sudo -iu isucon` で、ソースの `/srv/isucon/repo` とプラグインの `/srv/isucon/kaizen-plugin` を分けて使います。台帳・対象有効化設定は `/srv/isucon/state`、大きなログは `/srv/isucon/artifacts` です。Git取り込みやpreset作成を非対話で行う場合は、環境占有のもとでSSM Run Commandを使い、Command IDから結果を確認します。

プラグインは別のAIセッションやDiscord Botを自動起動しません。各自が起動したセッションで改善ループを続けます。対象が未設定の間は環境操作を開始しません。

- [Codexのプラグイン形式](https://developers.openai.com/plugins/build/plugins)
- [Claudeのプラグイン導入](https://code.claude.com/docs/en/discover-plugins)
- [Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-prerequisites.html)
