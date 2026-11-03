import type { Config } from "./env";

/**
 * Quanto credito AI (in USD, l'unità dei tetti OpenRouter) riceve l'utente per un pagamento.
 *
 * quota = (totale − IVA − commissione di pagamento) × (1 − margine) ÷ (1 + fee OpenRouter) × cambio
 *
 * Gli importi arrivano in centesimi di euro, come li manda Polar. La commissione di pagamento è
 * una stima prudente (percentuale + fisso); il margine reale si legge dalla tabella orders.
 */
export function quotaUsd(totalCents: number, taxCents: number, cfg: Config): number {
  const fee = totalCents * cfg.paymentFeePercent + cfg.paymentFeeFixedCents;
  const netCents = totalCents - taxCents - fee;
  if (netCents <= 0) return 0;
  const usd = ((netCents / 100) * (1 - cfg.margin)) / (1 + cfg.openrouterFee) * cfg.eurToUsd;
  return Math.floor(usd * 100) / 100; // arrotondato per difetto al centesimo
}
