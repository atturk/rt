import { describe, expect, it } from "vitest";
import { decryptSecret, encryptSecret, randomCode, signStandardWebhook, verifyStandardWebhook } from "../src/crypto";

const secret = btoa(String.fromCharCode(...new Uint8Array(32).fill(1)));

describe("crypto", () => {
  it("cifra e decifra la chiave OpenRouter", async () => {
    const sealed = await encryptSecret("sk-or-v1-abc", secret);
    expect(sealed).not.toContain("sk-or");
    expect(await decryptSecret(sealed, secret)).toBe("sk-or-v1-abc");
  });

  it("codici a 6 cifre", () => {
    for (let i = 0; i < 50; i++) expect(randomCode()).toMatch(/^\d{6}$/);
  });

  it("accetta una firma Standard Webhooks valida e rifiuta il resto", async () => {
    const now = 1_800_000_000;
    const sig = await signStandardWebhook("whsec", "msg_1", String(now), "{}");
    expect(await verifyStandardWebhook("whsec", "msg_1", String(now), "{}", sig, now)).toBe(true);
    expect(await verifyStandardWebhook("whsec", "msg_1", String(now), "{ }", sig, now)).toBe(false);
    expect(await verifyStandardWebhook("altro", "msg_1", String(now), "{}", sig, now)).toBe(false);
    // timestamp troppo vecchio: replica
    expect(await verifyStandardWebhook("whsec", "msg_1", String(now), "{}", sig, now + 600)).toBe(false);
    // più firme nell'header, una buona
    expect(await verifyStandardWebhook("whsec", "msg_1", String(now), "{}", `v1,xxx ${sig}`, now)).toBe(true);
  });
});
