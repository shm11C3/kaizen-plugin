# Discord連携の導入手順

対象は、各自のPCでClaude Code / Codexを動かし、同じ非公開Discordへ参加する構成。
kaizenを入れるだけではDiscord MCPは登録されない。この手順はBot・各PCのMCP・実接続を別々に準備する。
運用と排他の正本は[DISCORD](DISCORD.md)を参照する。

## 1. Botを準備する（メンバー各自）

### Botの作成と招待

1. [Discord Developer Portal](https://discord.com/developers/applications)でApplicationを作成する。
2. `Bot` → `Privileged Gateway Intents`で **Message Content Intent** を有効にし、保存する。
   このMCPにはServer Members Intent / Presence Intentは不要。
3. Installationの連携タイプは **Guild Install（サーバーインストール）** を使う。
   OAuth2 URL Generatorならscopeは **bot**。`messages.read`を選ぶ手順ではない。
   `applications.commands`が自動で付く場合があるが、このMCPはslash commandの設定を必要としない。
4. Bot Permissionsで以下を選び、生成URLを開いて対象サーバーへ招待する。

   - View Channels
   - Read Message History
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads

   Administratorは不要。非公開カテゴリ・チャンネル側でも、このBotのroleに上記を許可する。
   招待には対象サーバーでアプリを追加できる権限が必要。
   自分で招待できない場合は、生成した招待URLをサーバー管理者へ渡す。tokenを渡す必要はない。
5. `Bot`画面のToken欄から取得する。必要なら`Reset Token`して表示する。
   **Application ID / Public Key / OAuth2 Client Secretとは別の値**で、`Bot `という接頭辞は付けず保存する。

標準運用は **各メンバーが自分のBotを作成し、そのtokenを自分のPCへ保存する**。
他メンバーや管理者へbot-tokenの提供を依頼しない。全員のBotを対象サーバーへ招待し、
同じ対象チャンネルへ必要な権限を与える。同じ人のClaudeとCodexは同じBotを使ってよいが、
セッションIDとreaderIdは別にする。
チャット、Discord投稿、Git、MCP設定ファイルへtokenを貼らない。
R3の検証では共有Botを使ったが、メンバー向けの標準導入手順にはしない。

### サーバー管理者: チャンネルとIDの共有（一度だけ）

非公開の`ops` / `discoveries` / `tasks` / `benchmarks` / `decisions`を用意する。
Discordのユーザー設定 → 詳細設定 → 開発者モードを有効にし、サーバーと各チャンネルの
右クリック → IDをコピーする。IDは文字列として扱い、名前だけで接続先を推測しない。

host-configの`discord`ブロックに `guild_id` と5チャンネルIDを設定して共有する。
実際のキーは[host-config雛形](../templates/control-host.practice.example.json)に従う。
tokenはこのJSONに入れない。既存環境へ参加するときは、管理者のJSONを受け取り勝手に別チャンネルへ変えない。

## 2. 各PCで行うこと

以下はmacOS/Linuxのshell例。Python 3、**Node.js 24**、npm、Gitを用意する。
このadapterは`node:sqlite`を使う。元の`mcp-discord`のNode要件だけで判断しない。
Windowsのネイティブshell用コマンドはこの手順では検証していない。

### 履歴補完adapterを配置する

kaizen-pluginの編集元をclone済みなら、その絶対パスを`KAIZEN_SOURCE`へ指定する。
未取得なら、アクセス権のあるprivate repositoryを取得する。

```bash
git clone https://github.com/shm11C3/kaizen-plugin.git
cd kaizen-plugin
KAIZEN_SOURCE="$PWD"
DISCORD_RUNTIME="$HOME/.local/share/discord-mcp"
umask 077
mkdir -p "$DISCORD_RUNTIME"
chmod 700 "$DISCORD_RUNTIME"
cp "$KAIZEN_SOURCE/integrations/discord-mcp/launch.py" \
   "$KAIZEN_SOURCE/integrations/discord-mcp/server.mjs" \
   "$KAIZEN_SOURCE/integrations/discord-mcp/history.mjs" \
   "$KAIZEN_SOURCE/integrations/discord-mcp/package.json" \
   "$KAIZEN_SOURCE/integrations/discord-mcp/package-lock.json" "$DISCORD_RUNTIME/"
cd "$DISCORD_RUNTIME"
npm ci --ignore-scripts --no-audit --no-fund
node --version
```

Node 24をPATHの先頭へ置いてから実行する。実行用ディレクトリはGit cloneの外に置く。
既に運用中の場合、このcopyは同じtokenと`state/`を残すが、更新はMCPを停止した区切りで行う。
別PCから`bot-token`や`state/`を丸ごとGitへコピーしない。

### tokenを保存する（人間が対話型Terminalで実施）

```bash
python3 "$DISCORD_RUNTIME/launch.py" --configure
```

非表示の入力欄へBot tokenを入力する。保存先はruntimeの`bot-token`（mode600）。
実装は非対話入力とGit checkout内での保存を拒否する。AIへのtoken返信は不要。

### MCPを登録する

各PCで絶対パスを解決する。GUIアプリがshellのPATHを引き継がなくてもNodeを見つけられるよう指定する。

```bash
PYTHON_BIN="$(command -v python3)"
NODE_BIN="$(command -v node)"
# Codexを使うPC
codex mcp add discord --env "DISCORD_MCP_NODE=$NODE_BIN" -- \
  "$PYTHON_BIN" "$DISCORD_RUNTIME/launch.py"
# Claude Codeを使うPC
claude mcp add --scope user --transport stdio discord \
  --env "DISCORD_MCP_NODE=$NODE_BIN" -- \
  "$PYTHON_BIN" "$DISCORD_RUNTIME/launch.py"
```

使うクライアントだけ登録する。同じPCで両方使うなら両方へ登録する。
既に`discord`登録がある場合は先にcommand/argsを確認し、重複追加せずそのエントリを更新する。
Codexの設定は`~/.codex/config.toml`の`mcp_servers.discord`からも確認できる。
設定に入るのは実行パスとNodeパスだけで、tokenは入れない。

登録・変更後はClaudeの新規セッション、CodexのMCP再接続またはアプリ再起動で読み直す。
MCPがconnectedでも、Discord認証・権限確認が終わったとは扱わない。

## 3. 接続を検証する

1. MCPのツール一覧に`discord_read_messages` / `discord_read_unread` /
   `discord_ack_unread` / `discord_list_threads` / `discord_send`があることを確認する。
   補完adapterは現在25ツール。最新100件を読むだけの元MCPと混同しない。
2. 対象の既知チャンネルで`discord_read_messages`を少数取得し、既知メッセージの本文とIDを確認する。
   送信系が未ログインなら`discord_login`を**token引数なし**で呼び、保存済みtokenを使う。
3. セッション固有のreaderIdで未読ページを取得し、全文確認後にreceiptをACKする。
4. 投稿確認は、使用を許可されたテスト先でだけ行う。人間が既知の確認メッセージを投稿して読ませるか、
   AIによるテスト投稿も許可されている場合は識別prefix付きで1件投稿し、履歴から読み戻す。
   権限が許された実際の送信成功を確認して初めて「読み書き接続済み」とする。

AIへ渡す初回指示例（IDだけを実値へ置換）:

```text
自分で作成・招待したBotで参加。セッションID/readerIdは mylogin-codex-20261031-01。
guild_idと5チャンネルIDは共有host-configのdiscordブロックを使う。
全5チャンネルと関連threadを読み、activeとarchivedも確認する。
discord_read_unreadはページ全文を読んでからreceiptをACKし、completeのページもACKする。
空ページもreceiptがあればACKする。出力が切れたらACKせず、小さいlimit/maxCharactersで取り直す。
投稿は[mylogin-codex-20261031-01]で始める。練習先なら指定の「検証用・ミュート推奨」も付ける。
作業中は約1分おきに巡回する。担当取得とbench排他は共有台帳を使う。
今回は読み取り確認のみ。投稿確認は使用許可のあるテスト先で別途行う。
```

別PC・別セッションは別のreaderIdを使う。同じBotだから既読状態や会話が共有されるわけではない。
同じセッションを再開するときは同じreaderIdとruntimeの`state/readers.sqlite3`を使う。
別PCへ引き継ぐなら、最後のACK結果の`committedAfter`を共有し、新readerの初回`initialAfter`へ渡す。
snapshot途中の上限や未ACKの位置は確定cursorとして扱わない。

## 4. 履歴を取りこぼさない運用

- `read_unread` → 全文確認 → `ack_unread`を`complete=true`のページのACKまで繰り返す。
  ACKしないと同じページが再提示される。空ページをACKしない場合も新着を見落とす。
- 新着は次snapshotで読む。重要決定は古い投稿を編集するだけでなく、新しい投稿で追記する。
- tasks配下のactiveとarchived threadを発見し、thread IDをchannelIdとして読む。
  archiveは`hasMore=false`までページングし、台帳の既知thread IDとも照合する。
- 削除済み本文、参加していないprivate thread、古いIDの後日編集は復元・追跡できない。
- 各PCのstate DBとBot tokenは私有のまま保持する。Discordの投稿はタスク取得や排他lockの代用にしない。
- 起動中のAIか巡回subagentが約1分ごとに確認する構成で、Discord受信だけでAIが自動起動する仕組みではない。
  同じBotを複数クライアントで使う場合はAPI制限も共有する。未読差分を読み、変化のない定型投稿を避ける。

## 5. 困ったとき

| 症状 | 確認・対処 |
|---|---|
| tokenがない/401/ログイン不可 | Bot Tokenか、再発行で古い値が失効していないか。`--configure`で再保存し全クライアントを再接続 |
| connectedだが本文が空/Intentエラー | Developer PortalのMessage Content Intentを有効化して保存。再接続する |
| Missing Access / Missing Permissions / 既知履歴が見えない | 正しいサーバー/チャンネルID、Bot招待、親カテゴリを含むView Channels/Read Message Historyを確認。空履歴だけで成功判定しない |
| threadで投稿できない | Send Messages in ThreadsとBotのthread参加/可視範囲を確認 |
| 元MCPの履歴ツールしかない | commandが`launch.py`を指すか、adapter配置、クライアント再起動を確認 |
| nodeがない / node:sqliteエラー | Node24と`DISCORD_MCP_NODE`の絶対パスを確認。登録し直して再接続 |
| 新着が来ない/同じページが続く | readerId重複、空ページの未ACK、pending receiptを確認。切れたページはACKしない |
| 429 | Discordのretry_afterに従う。readerを無闇に作り直したり同じ投稿を連打しない |

tokenを再発行したら、そのBotを使う自分の全PC・クライアントで更新する。既存Bot/token/MCP設定をAIが勝手に再発行・上書きしない。
この手順を読んだだけで実接続や別PCの完了とは扱わない。

## 実装と根拠

adapter配布物は[integrations/discord-mcp](../../integrations/discord-mcp)、元MCPは`mcp-discord@1.3.4`に固定。
依存lockも同梱し、token・DB・node_modulesは配布物に含めない。

- [Discord OAuth2 / Bot Authorization](https://docs.discord.com/developers/topics/oauth2#bot-authorization-flow)
- [Discord Message Content Intent](https://docs.discord.com/developers/events/gateway#message-content-intent)
- [Discord Get Channel Messages](https://docs.discord.com/developers/resources/message#get-channel-messages)
- [Discord Permissions](https://docs.discord.com/developers/topics/permissions)

Botの認証・権限・履歴の実疎通と、ローカルfixture/protocol試験の成功は別の確認である。

2026-10-31確認: 同梱lockから秘密情報のない一時ディレクトリへ`npm ci`成功、
履歴/ACK/分割/再開/権限とMCP protocolの既存13試験成功。
launcherのGit内保存拒否・非対話拒否・mode600保存/値非表示も確認した。
既存接続では既知チャンネルの本文を読み取り確認。別PCの新規Bot/tokenでの導入完了や、
この作業での新規投稿試験まで済んだという意味ではない。
