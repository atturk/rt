/** Logica degli abbonamenti: dai webhook Polar ai tetti delle chiavi OpenRouter. */
import type { Config } from "./env";
import type { OpenRouterAdmin } from "./openrouter";
import type { Store, User } from "./store";
import { encryptSecret } from "./crypto";
import { quotaUsd } from "./quota";

export interface BillingDeps {
  store: Store;
  cfg: Config;
  openrouter: OpenRouterAdmin;
  encryptionSecret: string;
  now: () => number;
}

const round2 = (n: number) => Math.round(n * 100) / 100;

async function findUser(store: Store, data: any): Promise<User | null> {
  const externalId = data?.customer?.external_id ?? data?.external_customer_id ?? null;
  if (externalId) {
    const byId = await store.userById(externalId);
    if (byId) return byId;
  }
  if (data?.subscription_id) {
    const bySub = await store.userBySubscription(data.subscription_id);
    if (bySub) return bySub;
  }
  if (data?.id && typeof data.id === "string") {
    const bySub = await store.userBySubscription(data.id);
    if (bySub) return bySub;
  }
  const email = data?.customer?.email;
  return email ? store.userByEmail(String(email).toLowerCase()) : null;
}

function planFor(cfg: Config, productId: string | undefined): string | null {
  return cfg.plans.find((p) => p.polar_product_id === productId)?.id ?? null;
}

/**
 * Pagamento riuscito (primo mese o rinnovo): il tetto della chiave diventa
 * "speso finora + quota di questo pagamento". Il credito non usato del mese prima non si somma:
 * è la regola use it or lose it.
 */
export async function onOrderPaid(deps: BillingDeps, data: any): Promise<string> {
  const { store, cfg, openrouter } = deps;
  if (!data?.subscription_id) return "ignorato: ordine senza abbonamento";
  if (await store.orderExists(data.id)) return "ignorato: ordine già elaborato";
  const user = await findUser(store, data);
  if (!user) throw new Error(`Utente non trovato per l'ordine ${data.id}`);

  const total = Number(data.total_amount ?? data.amount ?? 0);
  const tax = Number(data.tax_amount ?? 0);
  if (String(data.currency ?? "eur").toLowerCase() !== "eur") throw new Error(`Valuta non gestita: ${data.currency}`);
  const quota = quotaUsd(total, tax, cfg);

  let usageBefore = 0;
  if (!user.or_key_hash) {
    const created = await openrouter.createKey(`rt-${user.id}`, quota);
    await store.updateUser(user.id, {
      or_key_hash: created.hash,
      or_key_enc: await encryptSecret(created.key, deps.encryptionSecret),
    });
    if (cfg.guardrailId) await openrouter.assignGuardrail(cfg.guardrailId, created.hash);
  } else {
    const info = await openrouter.getKey(user.or_key_hash);
    usageBefore = info.usage;
    await openrouter.updateKey(user.or_key_hash, { limit: round2(info.usage + quota), disabled: false });
  }

  await store.addOrder({
    order_id: data.id, user_id: user.id, created_at: deps.now(), total_cents: total, tax_cents: tax,
    currency: "eur", quota_usd: quota, usage_before_usd: usageBefore,
  });
  await store.updateUser(user.id, {
    subscription_id: data.subscription_id,
    subscription_status: "active",
    polar_customer_id: data.customer_id ?? user.polar_customer_id,
    plan_id: planFor(cfg, data.product_id) ?? user.plan_id,
    monthly_quota_usd: quota,
  });
  return `tetto aggiornato: +${quota} USD`;
}

/** Cambi di stato dell'abbonamento (attivo, disdetto a fine periodo, ripristinato). */
export async function onSubscriptionChanged(deps: BillingDeps, data: any): Promise<string> {
  const user = await findUser(deps.store, { ...data, subscription_id: data.id });
  if (!user) return "ignorato: utente non trovato";
  let status: string = data.status;
  if (status === "active" && data.cancel_at_period_end) status = "canceled";
  await deps.store.updateUser(user.id, {
    subscription_id: data.id,
    subscription_status: status,
    polar_customer_id: data.customer_id ?? user.polar_customer_id,
    current_period_end: data.current_period_end ?? null,
    plan_id: planFor(deps.cfg, data.product_id) ?? user.plan_id,
  });
  return `stato: ${status}`;
}

/** Abbonamento finito davvero: la chiave smette di funzionare (tetto = speso). */
export async function onSubscriptionRevoked(deps: BillingDeps, data: any): Promise<string> {
  const user = await findUser(deps.store, { ...data, subscription_id: data.id });
  if (!user) return "ignorato: utente non trovato";
  if (user.or_key_hash) {
    const info = await deps.openrouter.getKey(user.or_key_hash);
    await deps.openrouter.updateKey(user.or_key_hash, { limit: round2(info.usage), disabled: true });
  }
  await deps.store.updateUser(user.id, { subscription_status: "revoked", monthly_quota_usd: 0 });
  return "chiave disattivata";
}

export async function handlePolarEvent(deps: BillingDeps, event: { type: string; data: any }): Promise<string> {
  switch (event.type) {
    case "order.paid":
      return onOrderPaid(deps, event.data);
    case "subscription.created":
    case "subscription.active":
    case "subscription.updated":
    case "subscription.canceled":
    case "subscription.uncanceled":
      return onSubscriptionChanged(deps, event.data);
    case "subscription.revoked":
      return onSubscriptionRevoked(deps, event.data);
    default:
      return `ignorato: ${event.type}`;
  }
}

/** Controllo orario: saldo OpenRouter basso, o tetti promessi più alti del saldo. */
export async function balanceCheck(deps: BillingDeps): Promise<{ balance: number; outstanding: number; alerts: string[] }> {
  const { total, used } = await deps.openrouter.credits();
  const balance = round2(total - used);
  let outstanding = 0;
  for (const user of await deps.store.activeUsers()) {
    const info = await deps.openrouter.getKey(user.or_key_hash!);
    if (info.limit !== null && !info.disabled) outstanding += Math.max(0, info.limit - info.usage);
  }
  outstanding = round2(outstanding);
  const alerts: string[] = [];
  if (balance < deps.cfg.lowBalanceUsd) alerts.push(`Saldo OpenRouter basso: ${balance} USD`);
  if (outstanding > balance) alerts.push(`Credito promesso agli utenti (${outstanding} USD) oltre il saldo (${balance} USD)`);
  return { balance, outstanding, alerts };
}
