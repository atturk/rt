const enc = new TextEncoder();

function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

function fromBase64(value: string): Uint8Array<ArrayBuffer> {
  const s = atob(value);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

export function randomToken(bytes = 32): string {
  const buf = crypto.getRandomValues(new Uint8Array(bytes));
  return toBase64(buf).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Codice numerico a 6 cifre senza bias di modulo. */
export function randomCode(): string {
  const buf = new Uint32Array(1);
  const limit = Math.floor(0xffffffff / 1_000_000) * 1_000_000;
  do crypto.getRandomValues(buf); while (buf[0] >= limit);
  return String(buf[0] % 1_000_000).padStart(6, "0");
}

export async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", enc.encode(value));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function aesKey(secretB64: string): Promise<CryptoKey> {
  const raw = fromBase64(secretB64);
  if (raw.length !== 32) throw new Error("KEY_ENCRYPTION_SECRET deve essere base64 di 32 byte");
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

/** Cifra la chiave OpenRouter prima di salvarla nel database. */
export async function encryptSecret(plain: string, secretB64: string): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await aesKey(secretB64), enc.encode(plain));
  return `${toBase64(iv)}.${toBase64(new Uint8Array(data))}`;
}

export async function decryptSecret(sealed: string, secretB64: string): Promise<string> {
  const [ivB64, dataB64] = sealed.split(".");
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromBase64(ivB64) }, await aesKey(secretB64), fromBase64(dataB64),
  );
  return new TextDecoder().decode(plain);
}

/**
 * Verifica la firma di un webhook Polar (Standard Webhooks): HMAC-SHA256 di
 * "{id}.{timestamp}.{body}". Polar usa come chiave i byte del segreto così come lo mostra.
 * Rifiuta timestamp più vecchi di 5 minuti per evitare repliche.
 */
export async function verifyStandardWebhook(
  secret: string, id: string, timestamp: string, body: string, signatureHeader: string,
  nowSeconds = Math.floor(Date.now() / 1000),
): Promise<boolean> {
  const ts = Number(timestamp);
  if (!id || !Number.isFinite(ts) || Math.abs(nowSeconds - ts) > 300) return false;
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(`${id}.${timestamp}.${body}`));
  const expected = toBase64(new Uint8Array(mac));
  return signatureHeader.split(" ").some((part) => {
    const [version, sig] = part.split(",");
    return version === "v1" && sig !== undefined && timingSafeEqual(sig, expected);
  });
}

export async function signStandardWebhook(secret: string, id: string, timestamp: string, body: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(`${id}.${timestamp}.${body}`));
  return `v1,${toBase64(new Uint8Array(mac))}`;
}
