import { describe, expect, it } from "vitest";
import { handleRequest } from "../src/app";
import { balanceCheck } from "../src/billing";
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
  const res = await handleRequest(req("POST", "/v1/auth/verify", { email, code }), t.deps);
  return (await res.json() as any).token;
}

let webhookN = 0;
async function webhook(t: Deps, type: string, data: unknown) {
  const body = JSON.stringify({ type, data });
  const id = `msg_${++webhookN}`;
  const ts = String(t.deps.now());
  return handleRequest(new Request("https://cloud.example/webhooks/polar", {
    method: "POST",
    headers: {
      "webhook-id": id, "webhook-timestamp": ts,
      "webhook-signature": await signStandardWebhook(t.deps.webhookSecret, id, ts, body),
    },
    body,
  }), t.deps);
}

async function me(t: Deps, token: string) {
  return (await (await handleRequest(req("GET", "/v1/me", undefined, token), t.deps)).json()) as any;
}

async function userId(t: Deps, email = "studente@example.com") {
  return (await t.deps.store.userByEmail(email))!.id;
}

const order = (id: string, uid: string, extra: Record<string, unknown> = {}) => ({
  id, subscription_id: "sub_1", customer_id: "cus_1", product_id: "prod_base",
  customer: { external_id: uid, email: "studente@example.com" },
  total_amount: 300, tax_amount: 54, currency: "eur", billing_reason: "subscription_create", ...extra,
});

describe("login con codice email", () => {
  it("dà una sessione con il codice giusto", async () => {
    const t = makeDeps();
    const token = await login(t);
    expect(token).toBeTruthy();
    const profile = await me(t, token);
    expect(profile.email).toBe("studente@example.com");
    expect(profile.openrouter_key).toBeNull();
    expect(profile.subscription.status).toBe("none");
  });

  it("rifiuta un codice sbagliato e blocca dopo 5 tentativi", async () => {
    const t = makeDeps();
    const email = "a@example.com";
    await handleRequest(req("POST", "/v1/auth/start", { email }), t.deps);
    const code = t.mails.at(-1)!.subject.match(/\d{6}/)![0];
    const wrong = code === "000000" ? "111111" : "000000";
    for (let i = 0; i < 5; i++) {
      const res = await handleRequest(req("POST", "/v1/auth/verify", { email, code: wrong }), t.deps);
      expect(res.status).toBe(400);
    }
    const res = await handleRequest(req("POST", "/v1/auth/verify", { email, code }), t.deps);
    expect(res.status).toBe(400);
  });

  it("limita i codici richiesti", async () => {
    const t = makeDeps();
    for (let i = 0; i < 5; i++) {
      expect((await handleRequest(req("POST", "/v1/auth/start", { email: "b@example.com" }), t.deps)).status).toBe(200);
    }
    expect((await handleRequest(req("POST", "/v1/auth/start", { email: "b@example.com" }), t.deps)).status).toBe(429);
  });

  it("senza sessione le rotte private rispondono 401", async () => {
    const t = makeDeps();
    expect((await handleRequest(req("GET", "/v1/me"), t.deps)).status).toBe(401);
    expect((await handleRequest(req("GET", "/v1/me", undefined, "falso"), t.deps)).status).toBe(401);
  });
});

describe("abbonamento e chiave OpenRouter", () => {
  it("checkout porta a Polar con l'id dell'utente", async () => {
    const t = makeDeps();
    const token = await login(t);
    const res = await handleRequest(req("POST", "/v1/checkout", { plan: "base" }, token), t.deps);
    expect((await res.json() as any).url).toContain(await userId(t));
  });

  it("primo pagamento: crea la chiave con il tetto e la consegna all'app", async () => {
    const t = makeDeps({ cfg: { ...makeDeps().deps.cfg, guardrailId: "gr_1" } });
    const token = await login(t);
    const uid = await userId(t);
    expect((await webhook(t, "order.paid", order("ord_1", uid))).status).toBe(200);

    const profile = await me(t, token);
    expect(profile.subscription.status).toBe("active");
    expect(profile.openrouter_key).toBe("sk-or-v1-test1");
    expect(t.openrouter.keys.get("hash1")!.limit).toBe(1.44);
    expect(t.openrouter.guardrails).toEqual([["gr_1", "hash1"]]);
    // la chiave in chiaro non è nel database
    const stored = await t.deps.store.userById(uid);
    expect(stored!.or_key_enc).not.toContain("sk-or");
  });

  it("rinnovo: use it or lose it, il credito non usato non si somma", async () => {
    const t = makeDeps();
    await login(t);
    const uid = await userId(t);
    await webhook(t, "order.paid", order("ord_1", uid));
    t.openrouter.keys.get("hash1")!.usage = 0.4; // ha usato 0,40 su 1,44
    await webhook(t, "order.paid", order("ord_2", uid, { billing_reason: "subscription_cycle" }));
    expect(t.openrouter.keys.get("hash1")!.limit).toBe(1.84); // 0,40 + 1,44, non 1,44 + 1,04 + 1,44
    expect(t.openrouter.keys.size).toBe(1);
  });

  it("lo stesso ordine o lo stesso webhook non ricaricano due volte", async () => {
    const t = makeDeps();
    await login(t);
    const uid = await userId(t);
    await webhook(t, "order.paid", order("ord_1", uid));
    t.openrouter.keys.get("hash1")!.usage = 1;
    const res = await webhook(t, "order.paid", order("ord_1", uid));
    expect((await res.json() as any).result).toContain("già elaborato");
    expect(t.openrouter.keys.get("hash1")!.limit).toBe(1.44);
  });

  it("firma sbagliata: 401 e nessun effetto", async () => {
    const t = makeDeps();
    const res = await handleRequest(new Request("https://cloud.example/webhooks/polar", {
      method: "POST",
      headers: { "webhook-id": "x", "webhook-timestamp": String(t.deps.now()), "webhook-signature": "v1,falsa" },
      body: "{}",
    }), t.deps);
    expect(res.status).toBe(401);
  });

  it("disdetta: la chiave resta fino a fine periodo, poi si spegne", async () => {
    const t = makeDeps();
    const token = await login(t);
    const uid = await userId(t);
    await webhook(t, "order.paid", order("ord_1", uid));
    await webhook(t, "subscription.canceled", {
      id: "sub_1", status: "active", cancel_at_period_end: true, customer: { external_id: uid },
      current_period_end: "2027-01-01T00:00:00Z", product_id: "prod_base",
    });
    expect((await me(t, token)).subscription.status).toBe("canceled");
    expect((await me(t, token)).openrouter_key).toBeTruthy();

    t.openrouter.keys.get("hash1")!.usage = 0.5;
    await webhook(t, "subscription.revoked", { id: "sub_1", status: "canceled", customer: { external_id: uid } });
    const profile = await me(t, token);
    expect(profile.subscription.status).toBe("revoked");
    expect(profile.openrouter_key).toBeNull();
    expect(t.openrouter.keys.get("hash1")).toMatchObject({ limit: 0.5, disabled: true });
  });

  it("un errore nel webhook libera l'evento per il nuovo tentativo di Polar", async () => {
    const t = makeDeps();
    const res = await webhook(t, "order.paid", order("ord_x", "utente-inesistente", { customer: { external_id: "nope" } }));
    expect(res.status).toBe(500);
  });
});

describe("controllo saldo", () => {
  it("avvisa se i tetti promessi superano il saldo", async () => {
    const t = makeDeps();
    await login(t);
    await webhook(t, "order.paid", order("ord_1", await userId(t)));
    t.openrouter.balance = { total: 10, used: 9 };
    const report = await balanceCheck(t.deps);
    expect(report.balance).toBe(1);
    expect(report.outstanding).toBe(1.44);
    expect(report.alerts).toHaveLength(2);
  });
});
