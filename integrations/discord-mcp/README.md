# Discord history adapter

Bot作成・各PCへの配置・Codex/Claude登録は
[Discord導入手順](../../team/docs/DISCORD_SETUP.md)を参照。

元MCPは`mcp-discord@1.3.4`。server/historyは既存の履歴補完実装を配布用に同梱した。
launcherはNodeの絶対パス指定/PATH検索に対応し、Git checkout内へのtoken保存を拒否する。
実行用コピー、token、state DB、node_modulesはGitの外へ置く。

Node24とruntimeへの`npm ci`後、資格情報なしの既存fixture/protocol試験を実行できる。
以下の`RUNTIME`は導入先の絶対パスへ置換する。

```sh
DISCORD_MCP_ROOT=RUNTIME node --test integrations/discord-mcp/history.test.mjs integrations/discord-mcp/protocol.test.mjs
```

この試験の成功はDiscordの認証・権限・投稿の実接続確認を代替しない。
