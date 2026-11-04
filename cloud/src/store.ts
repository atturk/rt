/** Accesso al database D1. Solo account, abbonamenti e chiavi: nessun contenuto. */
export interface User {
  id: string;
  email: string;
  created_at: number;
  polar_customer_id: string | null;
  subscription_id: string | null;
  subscription_status: string | null;
  plan_id: string | null;
  current_period_end: string | null;
  or_key_hash: string | null;
  or_key_enc: string | null;
  monthly_quota_usd: number;
  sub_remaining_usd: number;
  accounted_usage_usd: number;
}

export interface Topup {
  order_id: string;
  user_id: string;
  created_at: number;
  expires_at: number;
  amount_usd: number;
  remaining_usd: number;
}

export class Store {
  constructor(private db: D1Database) {}

  userByEmail(email: string): Promise<User | null> {
    return this.db.prepare("SELECT * FROM users WHERE email = ?").bind(email).first<User>();
  }

  userById(id: string): Promise<User | null> {
    return this.db.prepare("SELECT * FROM users WHERE id = ?").bind(id).first<User>();
  }

  userBySubscription(subscriptionId: string): Promise<User | null> {
    return this.db.prepare("SELECT * FROM users WHERE subscription_id = ?").bind(subscriptionId).first<User>();
  }

  async createUser(id: string, email: string, now: number): Promise<User> {
    await this.db.prepare("INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)").bind(id, email, now).run();
    return (await this.userById(id))!;
  }

  async updateUser(id: string, fields: Partial<Omit<User, "id" | "email" | "created_at">>): Promise<void> {
    const keys = Object.keys(fields);
    if (keys.length === 0) return;
    const sets = keys.map((k) => `${k} = ?`).join(", ");
    await this.db.prepare(`UPDATE users SET ${sets} WHERE id = ?`)
      .bind(...keys.map((k) => (fields as Record<string, unknown>)[k] ?? null), id).run();
  }

  /** Utenti con una chiave che può ancora spendere: abbonamento in corso o ricariche non finite. */
  async activeUsers(now: number): Promise<User[]> {
    const res = await this.db.prepare(
      `SELECT * FROM users WHERE or_key_hash IS NOT NULL AND (subscription_status IN ('active', 'canceled')
         OR EXISTS (SELECT 1 FROM topups t WHERE t.user_id = users.id AND t.remaining_usd > 0 AND t.expires_at > ?))`,
    ).bind(now).all<User>();
    return res.results;
  }

  /** Ricariche con credito residuo, la più vicina alla scadenza per prima. */
  async openTopups(userId: string): Promise<Topup[]> {
    const res = await this.db.prepare(
      "SELECT * FROM topups WHERE user_id = ? AND remaining_usd > 0 ORDER BY expires_at, created_at",
    ).bind(userId).all<Topup>();
    return res.results;
  }

  async addTopup(t: Topup): Promise<void> {
    await this.db.prepare(
      "INSERT OR IGNORE INTO topups (order_id, user_id, created_at, expires_at, amount_usd, remaining_usd) VALUES (?, ?, ?, ?, ?, ?)",
    ).bind(t.order_id, t.user_id, t.created_at, t.expires_at, t.amount_usd, t.remaining_usd).run();
  }

  async setTopupRemaining(orderId: string, remaining: number): Promise<void> {
    await this.db.prepare("UPDATE topups SET remaining_usd = ? WHERE order_id = ?").bind(remaining, orderId).run();
  }

  /** Utenti con almeno una ricarica scaduta ma non ancora azzerata. */
  async usersWithExpiredTopups(now: number): Promise<User[]> {
    const res = await this.db.prepare(
      `SELECT * FROM users WHERE id IN (SELECT user_id FROM topups WHERE remaining_usd > 0 AND expires_at <= ?)`,
    ).bind(now).all<User>();
    return res.results;
  }

  async addLoginCode(email: string, codeHash: string, now: number, ttlSeconds: number): Promise<void> {
    await this.db.prepare("INSERT INTO login_codes (email, code_hash, created_at, expires_at) VALUES (?, ?, ?, ?)")
      .bind(email, codeHash, now, now + ttlSeconds).run();
  }

  async recentCodeCount(email: string, since: number): Promise<number> {
    const row = await this.db.prepare("SELECT COUNT(*) AS n FROM login_codes WHERE email = ? AND created_at >= ?")
      .bind(email, since).first<{ n: number }>();
    return row?.n ?? 0;
  }

  latestCode(email: string, now: number) {
    return this.db.prepare(
      "SELECT id, code_hash, attempts FROM login_codes WHERE email = ? AND used = 0 AND expires_at > ? ORDER BY id DESC LIMIT 1",
    ).bind(email, now).first<{ id: number; code_hash: string; attempts: number }>();
  }

  async bumpCodeAttempts(id: number): Promise<void> {
    await this.db.prepare("UPDATE login_codes SET attempts = attempts + 1 WHERE id = ?").bind(id).run();
  }

  async useCode(id: number): Promise<void> {
    await this.db.prepare("UPDATE login_codes SET used = 1 WHERE id = ?").bind(id).run();
  }

  async createSession(tokenHash: string, userId: string, now: number): Promise<void> {
    await this.db.prepare("INSERT INTO sessions (token_hash, user_id, created_at, last_used_at) VALUES (?, ?, ?, ?)")
      .bind(tokenHash, userId, now, now).run();
  }

  async sessionUser(tokenHash: string, now: number): Promise<User | null> {
    const row = await this.db.prepare("SELECT user_id FROM sessions WHERE token_hash = ?").bind(tokenHash)
      .first<{ user_id: string }>();
    if (!row) return null;
    await this.db.prepare("UPDATE sessions SET last_used_at = ? WHERE token_hash = ?").bind(now, tokenHash).run();
    return this.userById(row.user_id);
  }

  async deleteSession(tokenHash: string): Promise<void> {
    await this.db.prepare("DELETE FROM sessions WHERE token_hash = ?").bind(tokenHash).run();
  }

  /** true se l'evento è nuovo (e lo registra), false se era già stato elaborato. */
  async claimWebhook(webhookId: string, now: number): Promise<boolean> {
    const res = await this.db.prepare("INSERT OR IGNORE INTO webhook_events (webhook_id, received_at) VALUES (?, ?)")
      .bind(webhookId, now).run();
    return (res.meta?.changes ?? 0) > 0;
  }

  async releaseWebhook(webhookId: string): Promise<void> {
    await this.db.prepare("DELETE FROM webhook_events WHERE webhook_id = ?").bind(webhookId).run();
  }

  async orderExists(orderId: string): Promise<boolean> {
    return (await this.db.prepare("SELECT 1 AS x FROM orders WHERE order_id = ?").bind(orderId).first()) !== null;
  }

  async addOrder(o: {
    order_id: string; user_id: string; created_at: number; total_cents: number; tax_cents: number;
    currency: string; quota_usd: number; usage_before_usd: number;
  }): Promise<void> {
    await this.db.prepare(
      "INSERT INTO orders (order_id, user_id, created_at, total_cents, tax_cents, currency, quota_usd, usage_before_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind(o.order_id, o.user_id, o.created_at, o.total_cents, o.tax_cents, o.currency, o.quota_usd, o.usage_before_usd).run();
  }
}
