import { handleRequest, type AppDeps } from "./app";
import { balanceCheck, expireTopups } from "./billing";
import { loadConfig, type Env } from "./env";
import { resendMailer } from "./mail";
import { openRouterAdmin } from "./openrouter";
import { polarPayments } from "./polar";
import { Store } from "./store";

function deps(env: Env): AppDeps {
  const cfg = loadConfig(env);
  return {
    cfg,
    store: new Store(env.DB),
    openrouter: openRouterAdmin(env.OPENROUTER_MANAGEMENT_KEY),
    payments: polarPayments(cfg.polarApi, env.POLAR_ACCESS_TOKEN),
    mailer: resendMailer(env.RESEND_API_KEY, cfg.mailFrom),
    webhookSecret: env.POLAR_WEBHOOK_SECRET,
    encryptionSecret: env.KEY_ENCRYPTION_SECRET,
    now: () => Math.floor(Date.now() / 1000),
  };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await handleRequest(request, deps(env));
    } catch (err) {
      console.error(err);
      return new Response(JSON.stringify({ error: { code: "internal", message: "Errore interno" } }), {
        status: 500, headers: { "Content-Type": "application/json" },
      });
    }
  },

  async scheduled(_event: ScheduledEvent, env: Env): Promise<void> {
    const d = deps(env);
    const expired = await expireTopups(d);
    if (expired) console.log("ricariche scadute azzerate", expired);
    const report = await balanceCheck(d);
    console.log("controllo saldo", report);
    if (report.alerts.length && d.cfg.adminEmail) {
      await d.mailer.send(d.cfg.adminEmail, "RT Cloud: controlla il saldo OpenRouter", report.alerts.join("\n"));
    }
  },
};
