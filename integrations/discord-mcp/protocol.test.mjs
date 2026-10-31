import test from 'node:test';
import assert from 'node:assert/strict';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { mkdtempSync, rmSync } from 'node:fs';

const root = process.env.DISCORD_MCP_ROOT ?? join(homedir(), '.local/share/discord-mcp');
const { Client } = await import(pathToFileURL(join(root, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js')));
const { StdioClientTransport } = await import(pathToFileURL(join(root, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js')));

test('MCP initialize, extended schemas, local errors and original tool delegation work without credentials', { timeout: 20000 }, async () => {
  const directory = mkdtempSync(join(tmpdir(), 'discord-mcp-protocol-'));
  const transport = new StdioClientTransport({
    command: process.execPath, args: [process.env.DISCORD_MCP_SERVER_PATH ?? fileURLToPath(new URL('./server.mjs', import.meta.url))],
    env: { PATH: process.env.PATH, DISCORD_MCP_ROOT: root, DISCORD_MCP_STATE_DIR: directory },
    stderr: 'pipe',
  });
  transport.stderr.on('data', () => {});
  const client = new Client({ name: 'setup-protocol-test', version: '1.0.0' });
  try {
    await client.connect(transport);
    const tools = (await client.listTools()).tools;
    assert.equal(tools.length, 25);
    assert(tools.find(t => t.name === 'discord_read_messages').inputSchema.properties.before);
    for (const name of ['discord_read_unread', 'discord_ack_unread', 'discord_list_threads', 'discord_send']) assert(tools.find(t => t.name === name));
    const invalid = await client.callTool({ name: 'discord_read_unread', arguments: { readerId: '../bad', channelId: '1001' } });
    assert.equal(invalid.isError, true);
    assert.match(invalid.content[0].text, /readerId/);
    const original = await client.callTool({ name: 'discord_get_server_info', arguments: { guildId: '1000' } });
    assert.match(original.content[0].text, /not logged in/);
  } finally {
    await client.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
