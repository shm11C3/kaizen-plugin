import { DatabaseSync } from 'node:sqlite';
import { randomUUID } from 'node:crypto';

export function snowflake(value, name = 'ID', allowZero = false) {
  if (typeof value !== 'string' || !/^[0-9]{1,20}$/.test(value) || (!allowZero && BigInt(value) === 0n)) {
    throw new Error(`${name} must be a decimal Discord ID string.`);
  }
  return value;
}

function integer(value, fallback, minimum, maximum, name) {
  const result = value ?? fallback;
  if (!Number.isInteger(result) || result < minimum || result > maximum) {
    throw new Error(`${name} must be an integer from ${minimum} to ${maximum}.`);
  }
  return result;
}

function newestFirst(messages) {
  return [...messages].sort((a, b) => BigInt(a.id) > BigInt(b.id) ? -1 : BigInt(a.id) < BigInt(b.id) ? 1 : 0);
}

export function messageView(message) {
  return {
    id: message.id, channelId: message.channel_id,
    author: { id: message.author?.id, username: message.author?.username, bot: message.author?.bot ?? false },
    content: message.content, timestamp: message.timestamp, editedTimestamp: message.edited_timestamp ?? null,
    attachments: message.attachments ?? [], embeds: message.embeds ?? [],
    replyTo: message.message_reference?.message_id ?? null,
  };
}

// Permissions are verified before history reads: Discord otherwise returns []
// when READ_MESSAGE_HISTORY is missing, which must not advance a reader cursor.
export class DiscordHistory {
  constructor(api, identity) { this.api = api; this.identity = identity; }

  async access(channelId) {
    snowflake(channelId, 'channelId');
    const channel = await this.api.get(`/channels/${channelId}`);
    if (!channel.guild_id) throw new Error('History tracking supports server channels and threads only.');
    const user = await this.identity();
    const guild = await this.api.get(`/guilds/${channel.guild_id}`);
    const member = await this.api.get(`/guilds/${channel.guild_id}/members/${user.id}`);
    const roles = await this.api.get(`/guilds/${channel.guild_id}/roles`);
    let bits = 0n;
    for (const role of roles) {
      if (role.id === channel.guild_id || member.roles.includes(role.id)) bits |= BigInt(role.permissions);
    }
    if (guild.owner_id !== user.id && !(bits & 8n)) {
      const parent = [10, 11, 12].includes(channel.type)
        ? await this.api.get(`/channels/${channel.parent_id}`) : channel;
      const overwrites = parent.permission_overwrites ?? [];
      const everyone = overwrites.find(o => o.id === channel.guild_id && Number(o.type) === 0);
      if (everyone) bits = (bits & ~BigInt(everyone.deny)) | BigInt(everyone.allow);
      let deny = 0n, allow = 0n;
      for (const overwrite of overwrites) {
        if (Number(overwrite.type) === 0 && member.roles.includes(overwrite.id)) {
          deny |= BigInt(overwrite.deny); allow |= BigInt(overwrite.allow);
        }
      }
      bits = (bits & ~deny) | allow;
      const personal = overwrites.find(o => o.id === user.id && Number(o.type) === 1);
      if (personal) bits = (bits & ~BigInt(personal.deny)) | BigInt(personal.allow);
      if ((bits & 66560n) !== 66560n) throw new Error('VIEW_CHANNEL and READ_MESSAGE_HISTORY are required; cursor unchanged.');
    }
    return channel;
  }

  async read({ channelId, limit, before, after, around }) {
    const count = integer(limit, 50, 1, 100, 'limit');
    const cursors = { before, after, around };
    if (Object.values(cursors).filter(v => v !== undefined).length > 1) {
      throw new Error('before, after and around are mutually exclusive.');
    }
    const query = new URLSearchParams({ limit: String(count) });
    for (const [key, value] of Object.entries(cursors)) if (value !== undefined) query.set(key, snowflake(value, key));
    await this.access(channelId);
    const application = await this.api.get('/oauth2/applications/@me');
    if (!(BigInt(application.flags ?? 0) & 786432n)) {
      throw new Error('Message Content Intent is not enabled/approved for this Bot; cursor unchanged.');
    }
    const raw = newestFirst(await this.api.get(`/channels/${channelId}/messages`, { query }));
    return {
      channelId, order: 'newest_first', messages: raw.map(messageView),
      nextBefore: raw.at(-1)?.id ?? null, newestMessageId: raw[0]?.id ?? null,
      note: 'Use nextBefore to continue backwards. For durable unread tracking use discord_read_unread and acknowledge every page.',
    };
  }

  async threads({ channelId, scope = 'active', before, limit }) {
    const channel = await this.access(channelId);
    if (scope === 'active') {
      if (before !== undefined) throw new Error('Active threads do not accept a before cursor.');
      const result = await this.api.get(`/guilds/${channel.guild_id}/threads/active`);
      return { channelId, scope, threads: result.threads.filter(t => t.parent_id === channelId), hasMore: false, nextBefore: null };
    }
    const paths = { public_archived: 'public', joined_private_archived: 'private/joined' };
    if (!(scope in paths)) throw new Error('Use active, public_archived or joined_private_archived.');
    const query = new URLSearchParams({ limit: String(integer(limit, 50, 1, 100, 'limit')) });
    if (before !== undefined) {
      if (scope === 'joined_private_archived') snowflake(before, 'before');
      else if (typeof before !== 'string' || !Number.isFinite(Date.parse(before))) throw new Error('Public archive before must be an ISO timestamp.');
      query.set('before', before);
    }
    const path = scope === 'joined_private_archived'
      ? `/channels/${channelId}/users/@me/threads/archived/private`
      : `/channels/${channelId}/threads/archived/${paths[scope]}`;
    const result = await this.api.get(path, { query });
    const last = result.threads.at(-1);
    const cursor = last ? (scope === 'public_archived' ? last.thread_metadata.archive_timestamp : last.id) : null;
    if (result.has_more && (!cursor || cursor === before)) throw new Error('Archive pagination did not advance; do not mark discovery complete.');
    return {
      channelId, scope, threads: result.threads, hasMore: Boolean(result.has_more), nextBefore: result.has_more ? cursor : null,
      coverage: scope === 'joined_private_archived' ? 'Only private threads joined by this bot.' : 'Accessible public archived threads.',
    };
  }
}

export class Readers {
  constructor(filename) {
    this.db = new DatabaseSync(filename);
    this.db.exec(`PRAGMA busy_timeout=5000; PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS readers (
        reader TEXT NOT NULL, channel TEXT NOT NULL, cursor TEXT NOT NULL,
        upper_id TEXT, before_id TEXT, pending TEXT, version INTEGER NOT NULL DEFAULT 0,
        last_receipt TEXT, last_result TEXT, PRIMARY KEY(reader, channel)
      );`);
  }
  close() { this.db.close(); }
  row(reader, channel) { return this.db.prepare('SELECT * FROM readers WHERE reader=? AND channel=?').get(reader, channel); }
  validate(reader, channel) {
    if (typeof reader !== 'string' || !/^[A-Za-z0-9._-]{1,120}$/.test(reader)) throw new Error('readerId must be a stable, unique session ID (letters, digits, dot, underscore, hyphen).');
    snowflake(channel, 'channelId');
  }

  async unread(history, { readerId, channelId, initialAfter, limit, maxCharacters }) {
    this.validate(readerId, channelId);
    const count = integer(limit, 20, 1, 100, 'limit');
    const budget = integer(maxCharacters, 12000, 2000, 30000, 'maxCharacters');
    if (initialAfter !== undefined) snowflake(initialAfter, 'initialAfter', true);
    this.db.prepare('INSERT OR IGNORE INTO readers(reader,channel,cursor) VALUES(?,?,?)')
      .run(readerId, channelId, initialAfter ?? '0');
    const row = this.row(readerId, channelId);
    if (initialAfter !== undefined && initialAfter !== row.cursor) throw new Error('Reader already exists at another cursor. Use its saved cursor or a new readerId.');
    if (row.pending) {
      const pending = JSON.parse(row.pending);
      const selected = [];
      let characters = 0;
      for (const message of pending.messages) {
        const size = JSON.stringify(message).length;
        if (selected.length && (selected.length >= count || characters + size > budget)) break;
        selected.push(message); characters += size;
      }
      // A client can reduce a pending page after response truncation. Reissue a
      // receipt for its prefix; undelivered messages remain behind nextBefore.
      if (selected.length < pending.messages.length) {
        const smaller = { ...pending, receipt: randomUUID(), messages: selected, complete: false,
          nextBefore: selected.at(-1).id, overCharacterBudget: characters > budget };
        const update = this.db.prepare('UPDATE readers SET pending=?,version=version+1 WHERE reader=? AND channel=? AND version=?')
          .run(JSON.stringify(smaller), readerId, channelId, row.version);
        if (!update.changes) throw new Error('Reader changed; retry to retrieve its pending page.');
        return smaller;
      }
      return pending;
    }

    // Scan a finite snapshot backwards. No dependence on undocumented ordering
    // of an `after` query and no jump to newest while older unread pages remain.
    const page = await history.read({ channelId, limit: count, ...(row.before_id ? { before: row.before_id } : {}) });
    const raw = page.messages;
    const newest = raw[0]?.id;
    const upper = row.upper_id ?? (newest && BigInt(newest) > BigInt(row.cursor) ? newest : row.cursor);
    const eligible = raw.filter(m => BigInt(m.id) > BigInt(row.cursor) && BigInt(m.id) <= BigInt(upper));
    const selected = [];
    let characters = 0;
    for (const message of eligible) {
      const size = JSON.stringify(message).length;
      if (selected.length && characters + size > budget) break;
      selected.push(message); characters += size;
    }
    const complete = selected.length === eligible.length && (raw.length === 0 || raw.some(m => BigInt(m.id) <= BigInt(row.cursor)));
    if (!selected.length && !complete) throw new Error('History pagination made no progress; cursor unchanged.');
    const result = {
      readerId, channelId, receipt: randomUUID(), order: 'newest_first',
      messages: selected, complete, committedAfter: row.cursor, snapshotUpper: upper,
      nextBefore: complete ? null : selected.at(-1).id,
      overCharacterBudget: characters > budget,
      instruction: 'Read every message. Do not acknowledge truncated output. Call discord_ack_unread with this receipt, then repeat discord_read_unread until complete. New arrivals after snapshotUpper are read in the next snapshot. ACK confirms delivery to this session, not task completion.',
    };
    const update = this.db.prepare('UPDATE readers SET pending=?,version=version+1 WHERE reader=? AND channel=? AND version=? AND pending IS NULL')
      .run(JSON.stringify(result), readerId, channelId, row.version);
    if (!update.changes) throw new Error('Another request changed this reader. Retry to retrieve its pending page.');
    return result;
  }

  ack({ readerId, channelId, receipt }) {
    this.validate(readerId, channelId);
    const row = this.row(readerId, channelId);
    if (!row) throw new Error('Reader does not exist.');
    if (typeof receipt !== 'string' || !receipt) throw new Error('receipt is required.');
    if (receipt === row.last_receipt) return JSON.parse(row.last_result);
    const pending = row.pending && JSON.parse(row.pending);
    if (!pending || pending.receipt !== receipt) throw new Error('Receipt mismatch; cursor unchanged.');
    const result = {
      readerId, channelId, acknowledged: true, complete: pending.complete,
      committedAfter: pending.complete ? pending.snapshotUpper : row.cursor,
      nextBefore: pending.nextBefore,
    };
    const update = this.db.prepare(`UPDATE readers SET cursor=?, upper_id=?, before_id=?, pending=NULL,
      last_receipt=?,last_result=?,version=version+1 WHERE reader=? AND channel=? AND version=?`)
      .run(result.committedAfter, pending.complete ? null : pending.snapshotUpper,
        pending.nextBefore, receipt, JSON.stringify(result), readerId, channelId, row.version);
    if (!update.changes) throw new Error('Another request changed this reader; inspect the pending page.');
    return result;
  }
}
