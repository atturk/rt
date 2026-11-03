import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import type { AppDeps } from "../src/app";
import type { Config } from "../src/env";
import type { KeyInfo, OpenRouterAdmin } from "../src/openrouter";
import { Store } from "../src/store";

/** D1 finto sopra node:sqlite, con lo schema vero delle migrazioni. */
export function fakeD1(): D1Database {
  const db = new DatabaseSync(":memory:");
  const dir = new URL("../migrations/", import.meta.url);
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".sql")).sort()) {
    db.exec(readFileSync(new URL(file, dir), "utf8"));
  }
  const prepare = (sql: string) => {
    let args: unknown[] = [];
    const stmt: any = {
      bind(...values: unknown[]) { args = values; return stmt; },
      async first() { return (db.prepare(sql).get(...(args as any[])) as any) ?? null; },
      async all() { return { results: db.prepare(sql).all(...(args as any[])) }; },
      async run() { const r = db.prepare(sql).run(...(args as any[])); return { meta: { changes: Number(r.changes) } }; },
    };
    return stmt;
  };
  return { prepare } as unknown as D1Database;
}

export const testConfig: Config = {
  polarApi: "https://sandbox-api.polar.sh",
  successUrl: "https://example.com/ok",
  plans: [{ id: "base", polar_product_id: "prod_base", label: "Base" }],
  modelPool: ["deepseek/deepseek-v4-flash"],
  margin: 0.2,
  topup: { productId: "prod_topup", margin: 0.1, minCents: 500, maxCents: 20000, validDays: 365 },
  paymentFeePercent: 0.05,
  paymentFeeFixedCents: 50,
  openrouterFee: 0.055,
  eurToUsd: 1.05,
  lowBalanceUsd: 5,
  mailFrom: "RT <noreply@example.com>",
  adminEmail: "admin@example.com",
};

export class FakeOpenRouter implements OpenRouterAdmin {
  keys = new Map<string, KeyInfo & { key: string }>();
  guardrails: Array<[string, string]> = [];
  balance = { total: 50, used: 0 };
  private n = 0;
  async createKey(_name: string, limitUsd: number) {
    const hash = `hash${++this.n}`;
    const key = `sk-or-v1-test${this.n}`;
    this.keys.set(hash, { hash, key, usage: 0, limit: limitUsd, disabled: false });
    return { hash, key };
  }
  async getKey(hash: string) { const k = this.keys.get(hash)!; return { ...k }; }
  async updateKey(hash: string, patch: { limit?: number; disabled?: boolean }) {
    Object.assign(this.keys.get(hash)!, patch);
  }
  async assignGuardrail(id: string, hash: string) { this.guardrails.push([id, hash]); }
  async credits() { return this.balance; }
}

export function makeDeps(overrides: Partial<AppDeps> = {}) {
  const mails: Array<{ to: string; subject: string; text: string }> = [];
  const openrouter = new FakeOpenRouter();
  const deps: AppDeps = {
    cfg: testConfig,
    store: new Store(fakeD1()),
    openrouter,
    payments: {
      async createCheckout({ userId, amountCents }) {
        return `https://sandbox.polar.sh/checkout/${userId}${amountCents ? `?amount=${amountCents}` : ""}`;
      },
      async customerPortal() { return "https://sandbox.polar.sh/portal"; },
    },
    mailer: { async send(to, subject, text) { mails.push({ to, subject, text }); } },
    webhookSecret: "polar_whs_testsecret",
    encryptionSecret: btoa(String.fromCharCode(...new Uint8Array(32).fill(7))),
    now: () => 1_800_000_000,
    ...overrides,
  };
  return { deps, mails, openrouter };
}
