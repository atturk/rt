import { describe, expect, it } from "vitest";
import { handleRequest } from "../src/app";
import { expireTopups } from "../src/billing";
import { signStandardWebhook } from "../src/crypto";
import { makeDeps } from "./helpers";

type Deps = ReturnType<typeof makeDeps>;

const req = (method: string, path: string, body?: unknown, token?: string) =>
  new Request(`https://cloud.example${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

async function login(t: Deps, email = "studente@example.com"): Promise<string> {
  await handleRequest(req("POST", "/v1/auth/start", { email }), t.deps);
  const code = t.mails.at(-1)!.subject.match(/\d{6}/)![0];
  return ((await (await handleRequest(req("POST", "/v1/auth/verify", { email, code }), t.deps)).json()) as any).token;
}

let n = 0;
async function webhook(t: Deps, type: string, data: unknown) {
  const body = JSON.stringify({ type, data });
  const id = `msg_t${++n}`;
  const ts = String(t.deps.now());
  return handleRequest(new Request("https://cloud.example/webhooks/polar", {
    method: "POST",
    headers: { "webhook-id": id, "webhook-timestamp": ts, "webhook-signature": await signStandardWebhook(t.deps.webhookSecret, id, ts, body) },
    body,
  }), t.deps);
}

const me = async (t: Deps, token: string) =>
  (await (await handleRequest(req("GET", "/v1/me", undefined, token), t.deps)).json()) as any;

// Abbonamento di prova: 3 € → 1,44 $. Ricarica da 20 € → 13,33 $ (margine 10%).
const sub = (id: string, uid: string) => ({
  id, subscription_id: "sub_1", product_id: "prod_base", customer: { external_id: uid },
  total_amount: 300, tax_amount: 54, currency: "eur",
});
const topup = (id: string, uid: string) => ({
  id, subscription_id: null, product_id: "prod_topup", customer: { external_id: uid },
  total_amount: 2000, tax_amount: 361, currency: "eur", billing_reason: "purchase",
});

async function setup() {
  let clock = 1_800_000_000;
  const t = makeDeps({ now: () => clock });
  const token = await login(t);
  const uid = (await t.deps.store.userByEmail("studente@example.com"))!.id;
  return { t, token, uid, key: () => t.openrouter.keys.get("hash1")!, advance: (s: number) => { clock += s; } };
}

describe("ricariche extra", () => {
  it("il checkout chiede un abbonamento in corso e un importo valido", async () => {
    const { t, token, uid } = await setup();
    const topupReq = (amount_cents: number) => handleRequest(req("POST", "/v1/topup", { amount_cents }, token), t.deps);
    expect((await topupReq(2000)).status).toBe(409);
    await webhook(t, "order.paid", sub("ord_1", uid));
    expect((await topupReq(499)).status).toBe(400);
    const res = await topupReq(2000);
    expect(((await res.json()) as any).url).toContain("amount=2000");
  });

  it("ricarica prima del rinnovo: il credito del mese si perde lo stesso, la ricarica resta", async () => {
    const { t, token, uid, key } = await setup();
    await webhook(t, "order.paid", sub("ord_1", uid));
    key().usage = 0.4;
    expect(((await (await webhook(t, "order.paid", topup("ord_r", uid))).json()) as any).result).toBe("ricarica: +13.33 USD");
    expect(key().limit).toBe(0.4 + 1.04 + 13.33);

    await webhook(t, "order.paid", { ...sub("ord_2", uid), billing_reason: "subscription_cycle" });
    // 1,04 $ non usati del mese persi; nuovo mese 1,44 $; ricarica intatta
    expect(key().limit).toBe(0.4 + 1.44 + 13.33);
    expect((await me(t, token)).topup.balance_usd).toBe(13.33);
  });

  it("si spende prima il mese, poi la ricarica; a fine abbonamento la chiave vive di ricariche", async () => {
    const { t, token, uid, key } = await setup();
    await webhook(t, "order.paid", sub("ord_1", uid));
    await webhook(t, "order.paid", topup("ord_r", uid));
    key().usage = 3.44; // 1,44 del mese + 2 della ricarica
    await webhook(t, "order.paid", { ...sub("ord_2", uid), billing_reason: "subscription_cycle" });
    expect((await me(t, token)).topup.balance_usd).toBe(11.33);
    expect(key().limit).toBe(3.44 + 1.44 + 11.33);

    await webhook(t, "subscription.revoked", { id: "sub_1", status: "canceled", customer: { external_id: uid } });
    expect(key()).toMatchObject({ limit: 3.44 + 11.33, disabled: false });
    const profile = await me(t, token);
    expect(profile.subscription.status).toBe("revoked");
    expect(profile.openrouter_key).toBeTruthy();
  });

  it("la stessa ricarica non si somma due volte", async () => {
    const { t, uid, key } = await setup();
    await webhook(t, "order.paid", sub("ord_1", uid));
    await webhook(t, "order.paid", topup("ord_r", uid));
    await webhook(t, "order.paid", topup("ord_r", uid));
    expect(key().limit).toBe(1.44 + 13.33);
  });

  it("dopo 12 mesi la ricarica non usata scade", async () => {
    const { t, uid, key, advance } = await setup();
    await webhook(t, "order.paid", sub("ord_1", uid));
    await webhook(t, "order.paid", topup("ord_r", uid));
    key().usage = 1;
    await webhook(t, "subscription.revoked", { id: "sub_1", status: "canceled", customer: { external_id: uid } });
    advance(364 * 86400);
    expect(await expireTopups(t.deps)).toBe(0);
    advance(2 * 86400);
    expect(await expireTopups(t.deps)).toBe(1);
    expect(key()).toMatchObject({ limit: 1, disabled: true });
  });
});
