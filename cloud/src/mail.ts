export interface Mailer {
  send(to: string, subject: string, text: string): Promise<void>;
}

/** Invio email tramite Resend (piano gratuito: 3000 email al mese). */
export function resendMailer(apiKey: string, from: string, fetchImpl: typeof fetch = fetch): Mailer {
  return {
    async send(to, subject, text) {
      const resp = await fetchImpl("https://api.resend.com/emails", {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ from, to: [to], subject, text }),
      });
      if (!resp.ok) throw new Error(`Resend: HTTP ${resp.status}`);
    },
  };
}
