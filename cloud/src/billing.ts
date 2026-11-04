/** Logica degli abbonamenti: dai webhook Polar ai tetti delle chiavi OpenRouter. */
import type { Config } from "./env";
import type { OpenRouterAdmin } from "./openrouter";
import type { Store, Topup, User } from "./store";
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

const round4 = (n: number) => Math.round(n * 10000) / 10000;

/** Il credito dell'utente dopo il conteggio, prima di applicare l'evento. */
interface Ledger {
  subRemaining: number;
  topups: Array<{ order_id: string; expires_at: number; remaining: number; changed: boolean }>;
  newTopup?: Topup;
}

/**
 * Il cuore del credito. Legge quanto ha speso la chiave dall'ultimo conteggio e lo scala prima dal
 * credito dell'abbonamento, poi dalle ricariche (la più vicina alla scadenza per prima); azzera le
 * ricariche scadute; applica l'evento (`change`); infine porta il tetto della chiave a
 * "speso finora + credito residuo". Se il credito è finito la chiave viene disattivata.
 */
async function settle(deps: BillingDeps, user: User, change: (ledger: Ledger) => void = () => {}): Promise<number> {
  const { store, openrouter } = deps;
  const info = await openrouter.getKey(user.or_key_hash!);
  let spent = Math.max(0, info.usage - (user.accounted_usage_usd ?? 0));

  const ledger: Ledger = {
    subRemaining: user.sub_remaining_usd ?? 0,
    topups: (await store.openTopups(user.id)).map((t) => ({
      order_id: t.order_id, expires_at: t.expires_at, remaining: t.remaining_usd, changed: false,
    })),
  };
  const fromSub = Math.min(spent, ledger.subRemaining);
  ledger.subRemaining -= fromSub;
  spent -= fromSub;
  const now = deps.now();
  for (const t of ledger.topups) {
    const take = Math.min(spent, t.remaining);
    if (take > 0) { t.remaining -= take; spent -= take; t.changed = true; }
    if (t.expires_at <= now && t.remaining > 0) { t.remaining = 0; t.changed = true; }
  }

  change(ledger);

  for (const t of ledger.topups) if (t.changed) await store.setTopupRemaining(t.order_id, round4(t.remaining));
  if (ledger.newTopup) await store.addTopup(ledger.newTopup);
  const credit = round4(ledger.subRemaining + ledger.topups.reduce((sum, t) => sum + t.remaining, 0)
    + (ledger.newTopup?.remaining_usd ?? 0));
  await store.updateUser(user.id, { sub_remaining_usd: round4(ledger.subRemaining), accounted_usage_usd: info.usage });
  await openrouter.updateKey(user.or_key_hash!, { limit: round2(info.usage + credit), disabled: credit < 0.01 });
  return info.usage;
}

/** Crea la chiave dell'utente se non ce l'ha ancora (tetto 0: lo alza subito `settle`). */
async function ensureKey(deps: BillingDeps, user: User): Promise<User> {
  if (user.or_key_hash) return user;
  const created = await deps.openrouter.createKey(`rt-${user.id}`, 0);
  await deps.store.updateUser(user.id, {
    or_key_hash: created.hash,
    or_key_enc: await encryptSecret(created.key, deps.encryptionSecret),
    accounted_usage_usd: 0,
  });
  if (deps.cfg.guardrailId) await deps.openrouter.assignGuardrail(deps.cfg.guardrailId, created.hash);
  return (await deps.store.userById(user.id))!;
}

/**
 * Pagamento riuscito. Due casi:
 * - abbonamento (primo periodo o rinnovo): il credito dell'abbonamento diventa la quota di questo
 *   pagamento, quello non usato del periodo prima si perde (use it or lose it);
 * - ricarica extra: si aggiunge una ricarica che vale `validDays` giorni e non si perde al rinnovo.
 */
export async function onOrderPaid(deps: BillingDeps, data: any): Promise<string> {
  const { store, cfg } = deps;
  const isTopup = !data?.subscription_id && !!cfg.topup && data?.product_id === cfg.topup.productId;
  if (!data?.subscription_id && !isTopup) return "ignorato: ordine senza abbonamento";
  if (await store.orderExists(data.id)) return "ignorato: ordine già elaborato";
  const found = await findUser(store, data);
  if (!found) throw new Error(`Utente non trovato per l'ordine ${data.id}`);

  const total = Number(data.total_amount ?? data.amount ?? 0);
  const tax = Number(data.tax_amount ?? 0);
  if (String(data.currency ?? "eur").toLowerCase() !== "eur") throw new Error(`Valuta non gestita: ${data.currency}`);
  const quota = quotaUsd(total, tax, cfg, isTopup ? cfg.topup!.margin : cfg.margin);
  const now = deps.now();

  const user = await ensureKey(deps, found);
  // L'ordine si registra alla fine: se qualcosa fallisce Polar ritenta e il conteggio riparte da dove era.
  const usage = await settle(deps, user, (ledger) => {
    if (isTopup) {
      if (ledger.topups.some((t) => t.order_id === data.id)) return; // già aggiunta da un tentativo precedente
      ledger.newTopup = {
        order_id: data.id, user_id: user.id, created_at: now, expires_at: now + cfg.topup!.validDays * 86400,
        amount_usd: quota, remaining_usd: quota,
      };
    } else {
      ledger.subRemaining = quota;
    }
  });
  await store.addOrder({
    order_id: data.id, user_id: user.id, created_at: now, total_cents: total, tax_cents: tax,
    currency: "eur", quota_usd: quota, usage_before_usd: usage,
  });

  if (isTopup) {
    await store.updateUser(user.id, { polar_customer_id: data.customer_id ?? user.polar_customer_id });
    return `ricarica: +${quota} USD`;
  }
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

/**
 * Abbonamento finito davvero: il credito dell'abbonamento si azzera. La chiave resta attiva solo
 * finché ci sono ricariche non scadute.
 */
export async function onSubscriptionRevoked(deps: BillingDeps, data: any): Promise<string> {
  const user = await findUser(deps.store, { ...data, subscription_id: data.id });
  if (!user) return "ignorato: utente non trovato";
  if (user.or_key_hash) await settle(deps, user, (ledger) => { ledger.subRemaining = 0; });
  await deps.store.updateUser(user.id, { subscription_status: "revoked", monthly_quota_usd: 0 });
  const left = user.or_key_hash ? (await deps.store.openTopups(user.id)).length : 0;
  return left ? "abbonamento finito, restano le ricariche" : "chiave disattivata";
}

/** Azzera le ricariche scadute (dal cron). */
export async function expireTopups(deps: BillingDeps): Promise<number> {
  const users = await deps.store.usersWithExpiredTopups(deps.now());
  for (const user of users) if (user.or_key_hash) await settle(deps, user);
  return users.length;
}

/** Credito ricariche residuo all'ultimo conteggio e prima scadenza, per l'app. */
export async function topupSummary(deps: BillingDeps, user: User) {
  const now = deps.now();
  const open = (await deps.store.openTopups(user.id)).filter((t) => t.expires_at > now);
  return {
    balance_usd: round2(open.reduce((sum, t) => sum + t.remaining_usd, 0)),
    next_expiry: open.length ? new Date(open[0].expires_at * 1000).toISOString() : null,
  };
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
  for (const user of await deps.store.activeUsers(deps.now())) {
    const info = await deps.openrouter.getKey(user.or_key_hash!);
    if (info.limit !== null && !info.disabled) outstanding += Math.max(0, info.limit - info.usage);
  }
  outstanding = round2(outstanding);
  const alerts: string[] = [];
  if (balance < deps.cfg.lowBalanceUsd) alerts.push(`Saldo OpenRouter basso: ${balance} USD`);
  if (outstanding > balance) alerts.push(`Credito promesso agli utenti (${outstanding} USD) oltre il saldo (${balance} USD)`);
  return { balance, outstanding, alerts };
}
