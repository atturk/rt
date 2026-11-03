/** Client minimo della Management API di OpenRouter (solo gestione chiavi e saldo). */
const BASE = "https://openrouter.ai/api/v1";

export interface KeyInfo {
  hash: string;
  usage: number; // USD spesi in totale con la chiave
  limit: number | null;
  disabled: boolean;
}

export interface OpenRouterAdmin {
  createKey(name: string, limitUsd: number): Promise<{ hash: string; key: string }>;
  getKey(hash: string): Promise<KeyInfo>;
  updateKey(hash: string, patch: { limit?: number; disabled?: boolean }): Promise<void>;
  assignGuardrail(guardrailId: string, hash: string): Promise<void>;
  credits(): Promise<{ total: number; used: number }>;
}

export class OpenRouterError extends Error {}

export function openRouterAdmin(managementKey: string, fetchImpl: typeof fetch = fetch): OpenRouterAdmin {
  async function call(method: string, path: string, body?: unknown): Promise<any> {
    const resp = await fetchImpl(`${BASE}${path}`, {
      method,
      headers: { Authorization: `Bearer ${managementKey}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!resp.ok) throw new OpenRouterError(`OpenRouter ${method} ${path}: HTTP ${resp.status}`);
    return resp.json();
  }
  const info = (d: any): KeyInfo => ({
    hash: d.hash, usage: Number(d.usage ?? 0), limit: d.limit ?? null, disabled: Boolean(d.disabled),
  });
  return {
    async createKey(name, limitUsd) {
      const res = await call("POST", "/keys", { name, limit: limitUsd });
      return { hash: res.data.hash, key: res.key };
    },
    async getKey(hash) {
      return info((await call("GET", `/keys/${hash}`)).data);
    },
    async updateKey(hash, patch) {
      await call("PATCH", `/keys/${hash}`, patch);
    },
    async assignGuardrail(guardrailId, hash) {
      await call("POST", `/guardrails/${guardrailId}/assignments/keys`, { key_hashes: [hash] });
    },
    async credits() {
      const d = (await call("GET", "/credits")).data;
      return { total: Number(d.total_credits), used: Number(d.total_usage) };
    },
  };
}
