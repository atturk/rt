/** Rotte HTTP del backend. Le dipendenze esterne sono iniettate per poterle testare. */
import type { Config } from "./env";
import type { Mailer } from "./mail";
import type { OpenRouterAdmin } from "./openrouter";
import type { Payments } from "./polar";
import { Store } from "./store";
import { decryptSecret, randomCode, randomToken, sha256Hex, verifyStandardWebhook } from "./crypto";
import { handlePolarEvent, type BillingDeps } from "./billing";

export interface AppDeps extends BillingDeps {
  payments: Payments;
  mailer: Mailer;
  webhookSecret: string;
}

const CODE_TTL = 10 * 60;
const MAX_CODES_PER_HOUR = 5;
const MAX_CODE_ATTEMPTS = 5;
const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,255}\.[^\s@]{2,}$/;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const error = (status: number, code: string, message: string) => json({ error: { code, message } }, status);

async function readJson(request: Request): Promise<any> {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

const codeHash = (email: string, code: string) => sha256Hex(`${email}:${code}`);

async function authUser(deps: AppDeps, request: Request) {
  const header = request.headers.get("Authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return null;
  return deps.store.sessionUser(await sha256Hex(token), deps.now());
}

export async function handleRequest(request: Request, deps: AppDeps): Promise<Response> {
  const url = new URL(request.url);
  const route = `${request.method} ${url.pathname}`;
  const { store, cfg } = deps;

  if (route === "GET /v1/health") return json({ ok: true });

  if (route === "GET /v1/plans") {
    return json({ plans: cfg.plans.map(({ id, label }) => ({ id, label })), models: cfg.modelPool });
  }

  if (route === "POST /v1/auth/start") {
    const body = await readJson(request);
    const email = String(body?.email ?? "").trim().toLowerCase();
    if (!EMAIL_RE.test(email)) return error(400, "invalid_email", "Indirizzo email non valido");
    const now = deps.now();
    if ((await store.recentCodeCount(email, now - 3600)) >= MAX_CODES_PER_HOUR) {
      return error(429, "too_many_codes", "Troppi codici richiesti: riprova tra un'ora");
    }
    const code = randomCode();
    await store.addLoginCode(email, await codeHash(email, code), now, CODE_TTL);
    await deps.mailer.send(email, `Il tuo codice RT: ${code}`,
      `Il tuo codice di accesso a RT è ${code}.\nScade tra 10 minuti. Se non l'hai chiesto tu, ignora questa email.`);
    return json({ ok: true });
  }

  if (route === "POST /v1/auth/verify") {
    const body = await readJson(request);
    const email = String(body?.email ?? "").trim().toLowerCase();
    const code = String(body?.code ?? "").trim();
    const now = deps.now();
    const row = await store.latestCode(email, now);
    if (!row || row.attempts >= MAX_CODE_ATTEMPTS) return error(400, "invalid_code", "Codice non valido o scaduto");
    if (row.code_hash !== (await codeHash(email, code))) {
      await store.bumpCodeAttempts(row.id);
      return error(400, "invalid_code", "Codice non valido o scaduto");
    }
    await store.useCode(row.id);
    const user = (await store.userByEmail(email)) ?? (await store.createUser(crypto.randomUUID(), email, now));
    const token = randomToken();
    await store.createSession(await sha256Hex(token), user.id, now);
    return json({ token });
  }

  if (route === "POST /webhooks/polar") {
    const body = await request.text();
    const id = request.headers.get("webhook-id") ?? "";
    const ok = await verifyStandardWebhook(deps.webhookSecret, id,
      request.headers.get("webhook-timestamp") ?? "", body, request.headers.get("webhook-signature") ?? "", deps.now());
    if (!ok) return error(401, "bad_signature", "Firma non valida");
    if (!(await store.claimWebhook(id, deps.now()))) return json({ ok: true, result: "già ricevuto" });
    try {
      const result = await handlePolarEvent(deps, JSON.parse(body));
      return json({ ok: true, result });
    } catch (err) {
      // Si libera l'evento così Polar lo ritenta.
      await store.releaseWebhook(id);
      console.error("webhook polar", err);
      return error(500, "webhook_failed", "Elaborazione non riuscita");
    }
  }

  // Da qui in poi serve una sessione.
  const user = await authUser(deps, request);
  if (!user) return error(401, "unauthorized", "Accesso richiesto");

  if (route === "GET /v1/me") {
    const usable = user.subscription_status === "active" || user.subscription_status === "canceled";
    return json({
      email: user.email,
      subscription: {
        status: user.subscription_status ?? "none",
        plan: user.plan_id,
        current_period_end: user.current_period_end,
        monthly_quota_usd: user.monthly_quota_usd,
      },
      // Il saldo si legge direttamente da OpenRouter con questa chiave (GET /api/v1/key).
      openrouter_key: usable && user.or_key_enc ? await decryptSecret(user.or_key_enc, deps.encryptionSecret) : null,
      models: cfg.modelPool,
      vision_model: cfg.visionModel ?? null,
    });
  }

  if (route === "POST /v1/checkout") {
    const body = await readJson(request);
    const plan = cfg.plans.find((p) => p.id === (body?.plan ?? cfg.plans[0].id));
    if (!plan) return error(400, "invalid_plan", "Piano inesistente");
    if (user.subscription_status === "active") {
      return error(409, "already_subscribed", "Abbonamento già attivo: gestiscilo dal portale");
    }
    const url = await deps.payments.createCheckout({
      productId: plan.polar_product_id, userId: user.id, email: user.email, successUrl: cfg.successUrl,
    });
    return json({ url });
  }

  if (route === "POST /v1/portal") {
    if (!user.subscription_id) return error(404, "no_subscription", "Nessun abbonamento");
    return json({ url: await deps.payments.customerPortal(user.id) });
  }

  if (route === "POST /v1/auth/logout") {
    const token = (request.headers.get("Authorization") ?? "").slice(7).trim();
    await store.deleteSession(await sha256Hex(token));
    return json({ ok: true });
  }

  return error(404, "not_found", "Rotta inesistente");
}
