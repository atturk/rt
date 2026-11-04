/** Variabili e segreti del Worker. I segreti si impostano con `wrangler secret put`. */
export interface Env {
  DB: D1Database;
  // segreti
  OPENROUTER_MANAGEMENT_KEY: string;
  POLAR_ACCESS_TOKEN: string;
  POLAR_WEBHOOK_SECRET: string;
  KEY_ENCRYPTION_SECRET: string; // base64 di 32 byte casuali
  RESEND_API_KEY: string;
  ADMIN_EMAIL?: string;
  // variabile: email ammesse durante la prova, separate da virgole (vuota = tutti)
  ALLOWED_EMAILS?: string;
  OPENROUTER_GUARDRAIL_ID?: string;
  // variabili
  POLAR_ENV: string;
  CHECKOUT_SUCCESS_URL: string;
  PLANS: string;
  MODEL_POOL: string;
  VISION_MODEL?: string;
  MARGIN: string;
  TOPUP_PRODUCT_ID?: string;
  TOPUP_MARGIN?: string;
  TOPUP_MIN_CENTS?: string;
  TOPUP_MAX_CENTS?: string;
  TOPUP_VALID_DAYS?: string;
  PAYMENT_FEE_PERCENT: string;
  PAYMENT_FEE_FIXED_CENTS: string;
  OPENROUTER_FEE: string;
  EUR_TO_USD: string;
  LOW_BALANCE_USD: string;
  MAIL_FROM: string;
}

export interface Plan {
  id: string;
  polar_product_id: string;
  label: string;
}

/** Ricariche extra (prodotto Polar una tantum con prezzo a scelta del cliente). */
export interface TopupConfig {
  productId: string;
  margin: number;
  minCents: number;
  maxCents: number;
  validDays: number;
}

/** Un modello del pool consigliato. `note` è il testo breve mostrato nell'app. */
export interface PoolModel {
  id: string;
  label: string;
  note?: string;
  recommended?: boolean;
}

export interface Config {
  polarApi: string;
  successUrl: string;
  plans: Plan[];
  /** Il primo è il predefinito per le fasi di testo. */
  modelPool: PoolModel[];
  visionModel?: string;
  margin: number;
  topup?: TopupConfig;
  paymentFeePercent: number;
  paymentFeeFixedCents: number;
  openrouterFee: number;
  eurToUsd: number;
  lowBalanceUsd: number;
  mailFrom: string;
  adminEmail?: string;
  /** Se presente, solo queste email possono accedere (prova con amici in sandbox). */
  allowedEmails?: string[];
  guardrailId?: string;
}

function num(value: string, name: string, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < min || parsed > max) {
    throw new Error(`Configurazione non valida: ${name}=${value}`);
  }
  return parsed;
}

export function loadConfig(env: Env): Config {
  if (env.POLAR_ENV !== "sandbox" && env.POLAR_ENV !== "production") {
    throw new Error("POLAR_ENV deve essere 'sandbox' o 'production'");
  }
  const plans = JSON.parse(env.PLANS) as Plan[];
  if (!Array.isArray(plans) || plans.length === 0) throw new Error("PLANS vuoto");
  const rawPool = JSON.parse(env.MODEL_POOL) as Array<string | PoolModel>;
  if (!Array.isArray(rawPool) || rawPool.length === 0) throw new Error("MODEL_POOL vuoto");
  const modelPool = rawPool.map((m) => (typeof m === "string" ? { id: m, label: m } : m));
  if (modelPool.some((m) => !m.id || !m.label)) throw new Error("MODEL_POOL: ogni modello vuole id e label");
  return {
    polarApi: env.POLAR_ENV === "production" ? "https://api.polar.sh" : "https://sandbox-api.polar.sh",
    successUrl: env.CHECKOUT_SUCCESS_URL,
    plans,
    modelPool,
    visionModel: env.VISION_MODEL || undefined,
    margin: num(env.MARGIN, "MARGIN", 0, 0.9),
    topup: env.TOPUP_PRODUCT_ID && env.TOPUP_PRODUCT_ID !== "SOSTITUIRE"
      ? {
        productId: env.TOPUP_PRODUCT_ID,
        margin: num(env.TOPUP_MARGIN ?? "0.10", "TOPUP_MARGIN", 0, 0.9),
        minCents: num(env.TOPUP_MIN_CENTS ?? "500", "TOPUP_MIN_CENTS", 100, 100000),
        maxCents: num(env.TOPUP_MAX_CENTS ?? "20000", "TOPUP_MAX_CENTS", 100, 1000000),
        validDays: num(env.TOPUP_VALID_DAYS ?? "365", "TOPUP_VALID_DAYS", 1, 3650),
      }
      : undefined,
    paymentFeePercent: num(env.PAYMENT_FEE_PERCENT, "PAYMENT_FEE_PERCENT", 0, 0.5),
    paymentFeeFixedCents: num(env.PAYMENT_FEE_FIXED_CENTS, "PAYMENT_FEE_FIXED_CENTS", 0, 500),
    openrouterFee: num(env.OPENROUTER_FEE, "OPENROUTER_FEE", 0, 0.5),
    eurToUsd: num(env.EUR_TO_USD, "EUR_TO_USD", 0.5, 2),
    lowBalanceUsd: num(env.LOW_BALANCE_USD, "LOW_BALANCE_USD", 0, 10000),
    mailFrom: env.MAIL_FROM,
    adminEmail: env.ADMIN_EMAIL || undefined,
    allowedEmails: env.ALLOWED_EMAILS?.trim()
      ? env.ALLOWED_EMAILS.split(",").map((e) => e.trim().toLowerCase()).filter(Boolean)
      : undefined,
    guardrailId: env.OPENROUTER_GUARDRAIL_ID || undefined,
  };
}
