import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DiscordHistory, Readers } from './history.mjs';

const START = 90071992547409930n;
const msg = n => ({ id: String(START + BigInt(n)), channel_id: '1001', content: `message ${n}`,
  author: { id: '2001', username: 'member' }, timestamp: new Date(1700000000000 + n).toISOString() });
class FakeAPI {
  constructor(count = 0) { this.messages = Array.from({ length: count }, (_, i) => msg(i + 1)); this.calls = []; this.permissions = '66560'; }
  async get(path, options = {}) {
    this.calls.push({ path, query: options.query });
    if (path === '/channels/1001/messages') {
      if (this.fail) throw new Error('HTTP 429; retry later');
      let rows = [...this.messages];
      if (options.query.has('before')) rows = rows.filter(m => BigInt(m.id) < BigInt(options.query.get('before')));
      if (options.query.has('after')) rows = rows.filter(m => BigInt(m.id) > BigInt(options.query.get('after')));
      return rows.reverse().slice(0, Number(options.query.get('limit')));
    }
    if (path === '/channels/1001') return { id: '1001', guild_id: '1000', type: this.thread ? 11 : 0,
      parent_id: this.thread ? '1002' : null, permission_overwrites: this.overwrites ?? [] };
    if (path === '/channels/1002') return { id: '1002', permission_overwrites: this.overwrites ?? [] };
    if (path === '/guilds/1000') return { owner_id: '9999' };
    if (path === '/guilds/1000/members/2000') return { roles: ['3000'] };
    if (path === '/guilds/1000/roles') return [{ id: '1000', permissions: this.permissions }, { id: '3000', permissions: '0' }];
    if (path === '/oauth2/applications/@me') return { flags: this.noIntent ? 0 : 524288 };
    if (this.handleThreads) return this.handleThreads(path, options);
    throw new Error(`Unexpected route: ${path}`);
  }
}
function fixture(count = 0) {
  const api = new FakeAPI(count);
  const history = new DiscordHistory(api, async () => ({ id: '2000' }));
  return { api, history };
}
async function drain(readers, history, args) {
  const messages = [];
  for (let i = 0; i < 100; i++) {
    const page = await readers.unread(history, args);
    messages.push(...page.messages);
    const ack = readers.ack({ ...args, receipt: page.receipt });
    if (ack.complete) return { messages, ack };
  }
  throw new Error('Did not finish snapshot');
}
const args = { readerId: 'codex-01', channelId: '1001', limit: 100, maxCharacters: 30000 };

test('all 257 messages survive pagination, restart, unacknowledged replay and new arrivals', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'discord-history-test-'));
  const filename = join(directory, 'state.sqlite3');
  let readers = new Readers(filename);
  try {
    const { api, history } = fixture(257);
    const first = await readers.unread(history, args);
    assert.equal(first.snapshotUpper, msg(257).id);
    assert.equal(readers.row(args.readerId, args.channelId).cursor, '0');
    readers.close(); readers = new Readers(filename);
    assert.deepEqual(await readers.unread(history, args), first);
    readers.ack({ ...args, receipt: first.receipt });
    assert.equal(readers.row(args.readerId, args.channelId).cursor, '0');
    api.messages.push(msg(258), msg(259));
    const rest = await drain(readers, history, args);
    const ids = [...first.messages, ...rest.messages].map(m => m.id);
    assert.equal(ids.length, 257);
    assert.equal(new Set(ids).size, 257);
    assert.deepEqual([...ids].sort(), api.messages.slice(0, 257).map(m => m.id).sort());
    assert.equal(rest.ack.committedAfter, msg(257).id);
    const next = await drain(readers, history, args);
    assert.deepEqual(next.messages.map(m => m.id), [msg(259).id, msg(258).id]);
    assert.equal(next.ack.committedAfter, msg(259).id);
  } finally { readers.close(); rmSync(directory, { recursive: true, force: true }); }
});

test('API error after one ACK keeps snapshot position, retry reads all remaining history', async () => {
  const readers = new Readers(':memory:');
  try {
    const { api, history } = fixture(205);
    const first = await readers.unread(history, args);
    readers.ack({ ...args, receipt: first.receipt });
    const state = { ...readers.row(args.readerId, args.channelId) };
    api.fail = true;
    await assert.rejects(readers.unread(history, args), /429/);
    assert.deepEqual({ ...readers.row(args.readerId, args.channelId) }, state);
    api.fail = false;
    const rest = await drain(readers, history, args);
    assert.equal(first.messages.length + rest.messages.length, 205);
  } finally { readers.close(); }
});

test('character budgets and reducing an unacknowledged page never skip withheld messages', async () => {
  const readers = new Readers(':memory:');
  try {
    const { api, history } = fixture(33);
    for (const m of api.messages) m.content = 'あ'.repeat(900);
    const large = await readers.unread(history, args);
    const small = await readers.unread(history, { ...args, limit: 2, maxCharacters: 2000 });
    assert.notEqual(small.receipt, large.receipt);
    assert(small.messages.length <= 2);
    assert.throws(() => readers.ack({ ...args, receipt: large.receipt }), /mismatch/);
    readers.ack({ ...args, receipt: small.receipt });
    const rest = await drain(readers, history, { ...args, maxCharacters: 2000 });
    const ids = [...small.messages, ...rest.messages].map(m => m.id);
    assert.equal(ids.length, 33); assert.equal(new Set(ids).size, 33);
  } finally { readers.close(); }
});

test('reader identity is independent; ACK is idempotent and wrong receipts cannot advance state', async () => {
  const readers = new Readers(':memory:');
  try {
    const { history } = fixture(3);
    const page = await readers.unread(history, args);
    assert.throws(() => readers.ack({ ...args, receipt: 'wrong' }), /mismatch/);
    const other = await readers.unread(history, { ...args, readerId: 'claude-01' });
    assert.deepEqual(other.messages, page.messages);
    const ack = readers.ack({ ...args, receipt: page.receipt });
    await readers.unread(history, args);
    assert.deepEqual(readers.ack({ ...args, receipt: page.receipt }), ack);
  } finally { readers.close(); }
});

test('concurrent reads sharing a session produce one pending page, not two scan advances', async () => {
  const readers = new Readers(':memory:');
  try {
    const { history } = fixture(150);
    const results = await Promise.allSettled([readers.unread(history, args), readers.unread(history, args)]);
    assert.equal(results.filter(r => r.status === 'fulfilled').length, 1);
    assert.equal(results.filter(r => r.status === 'rejected').length, 1);
    const pending = await readers.unread(history, args);
    assert.equal(pending.receipt, results.find(r => r.status === 'fulfilled').value.receipt);
    assert.equal(readers.row(args.readerId, args.channelId).cursor, '0');
  } finally { readers.close(); }
});

test('permission loss and disabled intent are errors, not an empty successful history', async () => {
  for (const mode of ['permissions', 'noIntent']) {
    const readers = new Readers(':memory:');
    try {
      const { api, history } = fixture(3);
      api[mode] = mode === 'permissions' ? '1024' : true;
      await assert.rejects(readers.unread(history, args), /required|Intent/);
      const state = readers.row(args.readerId, args.channelId);
      assert.equal(state.cursor, '0'); assert.equal(state.pending, null);
      assert(!api.calls.some(c => c.path.endsWith('/messages')));
    } finally { readers.close(); }
  }
});

test('archived thread reads use parent permissions; member deny overrides role allow', async () => {
  const { api, history } = fixture(1);
  api.thread = true;
  api.overwrites = [
    { id: '1000', type: 0, deny: '65536', allow: '0' },
    { id: '3000', type: 0, deny: '0', allow: '65536' },
  ];
  assert.equal((await history.read({ channelId: '1001' })).messages.length, 1);
  assert(api.calls.some(c => c.path === '/channels/1002'));
  api.overwrites.push({ id: '2000', type: 1, deny: '65536', allow: '0' });
  await assert.rejects(history.read({ channelId: '1001' }), /READ_MESSAGE_HISTORY/);
});

test('disabling content intent during a snapshot cannot silently acknowledge blank history', async () => {
  const readers = new Readers(':memory:');
  try {
    const { api, history } = fixture(130);
    const first = await readers.unread(history, args);
    readers.ack({ ...args, receipt: first.receipt });
    const state = { ...readers.row(args.readerId, args.channelId) };
    api.noIntent = true;
    await assert.rejects(readers.unread(history, args), /Intent/);
    assert.deepEqual({ ...readers.row(args.readerId, args.channelId) }, state);
  } finally { readers.close(); }
});

test('history cursors retain snowflake precision and reject mutually exclusive inputs', async () => {
  const { history } = fixture(250);
  const page = await history.read({ channelId: '1001', limit: 100 });
  const next = await history.read({ channelId: '1001', before: page.nextBefore, limit: 100 });
  assert.equal(page.messages.at(-1).id, msg(151).id);
  assert.equal(next.messages[0].id, msg(150).id);
  const after = await history.read({ channelId: '1001', after: msg(249).id });
  assert.deepEqual(after.messages.map(m => m.id), [msg(250).id]);
  await assert.rejects(history.read({ channelId: '1001', before: msg(2).id, after: msg(1).id }), /mutually exclusive/);
  await assert.rejects(history.read({ channelId: '1001', before: Number(START) }), /string/);
});

test('explicit initial boundary and empty channels require ACK without skipping future arrivals', async () => {
  const readers = new Readers(':memory:');
  try {
    const { api, history } = fixture(8);
    const result = await drain(readers, history, { ...args, initialAfter: msg(5).id });
    assert.deepEqual(result.messages.map(m => m.id), [msg(8).id, msg(7).id, msg(6).id]);
    await assert.rejects(readers.unread(history, { ...args, initialAfter: msg(1).id }), /already exists/);
    api.messages = [];
    const empty = await drain(readers, history, { ...args, readerId: 'empty-01' });
    assert.equal(empty.ack.committedAfter, '0');
    api.messages.push(msg(9));
    assert.equal((await drain(readers, history, { ...args, readerId: 'empty-01' })).messages[0].id, msg(9).id);
  } finally { readers.close(); }
});

test('thread discovery paginates archives, scopes active threads and supports joined private IDs', async () => {
  const { api, history } = fixture();
  api.handleThreads = async (path, { query }) => {
    if (path.endsWith('/threads/active')) return { threads: [{ id: '11', parent_id: '1001' }, { id: '12', parent_id: '1002' }] };
    if (path.endsWith('/threads/archived/public')) {
      return query.has('before') ? { threads: [], has_more: false } : {
        threads: [{ id: '10', thread_metadata: { archive_timestamp: '2026-10-24T00:00:00.000Z' } }], has_more: true,
      };
    }
    assert.equal(path, '/channels/1001/users/@me/threads/archived/private');
    return { threads: [{ id: '9' }], has_more: true };
  };
  assert.equal((await history.threads({ channelId: '1001' })).threads.length, 1);
  const first = await history.threads({ channelId: '1001', scope: 'public_archived' });
  assert.equal(first.hasMore, true);
  assert.equal((await history.threads({ channelId: '1001', scope: 'public_archived', before: first.nextBefore })).hasMore, false);
  assert.equal((await history.threads({ channelId: '1001', scope: 'joined_private_archived' })).nextBefore, '9');
});

test('an empty or older server history never regresses the committed cursor', async () => {
  const readers = new Readers(':memory:');
  try {
    const { history } = fixture(3);
    const result = await drain(readers, history, { ...args, initialAfter: msg(20).id });
    assert.deepEqual(result.messages, []);
    assert.equal(result.ack.committedAfter, msg(20).id);
  } finally { readers.close(); }
});
