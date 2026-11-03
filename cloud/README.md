# RT Cloud

Backend della **modalità facilitata** di RT: l'utente paga un abbonamento mensile e riceve una chiave
OpenRouter con un tetto di spesa, senza creare account né configurare chiavi. Chi preferisce resta in
BYOK e non passa mai di qui.

Gira su Cloudflare Workers con un database D1. Costo a questi volumi: zero (piano gratuito).

## Cosa fa e cosa non fa

- Login con codice via email (niente password).
- Checkout e portale abbonamento su Polar, che fa da Merchant of Record (IVA e fatture).
- Su ogni pagamento riuscito crea o ricarica la chiave OpenRouter dell'utente.
- Ogni ora controlla il saldo OpenRouter e manda un'email se è basso.
- **Non vede mai lezioni, prompt o risposte**: l'app RT parla direttamente con OpenRouter usando la
  chiave dell'utente. Nel database ci sono solo email, stato dell'abbonamento, pagamenti e la chiave
  OpenRouter cifrata.

## Come funzionano i soldi

Per ogni pagamento la quota AI dell'utente (in USD, l'unità di OpenRouter) è:

```
quota = (totale − IVA − commissione stimata) × (1 − MARGIN) ÷ (1 + OPENROUTER_FEE) × EUR_TO_USD
```

Con IVA italiana: 3,99 € al mese danno circa 2,05 $, 17,99 € ogni 6 mesi circa 10,6 $, 29,99 € all'anno
circa 18 $. Il credito di un piano lungo arriva tutto al pagamento e vale per l'intero periodo. A ogni rinnovo il tetto della chiave diventa
**speso finora + quota del mese**: il credito non usato del mese prima non si somma (use it or lose
it). OpenRouter addebita solo i token consumati, quindi il credito non usato non va comprato: resta
come incasso su Polar. Quando l'abbonamento finisce davvero (`subscription.revoked`) il credito del
periodo si azzera e la chiave viene disattivata, a meno che restino ricariche.

### Ricariche extra

Chi ha un abbonamento in corso può comprare una ricarica a importo libero (da `TOPUP_MIN_CENTS`, 5 €,
a `TOPUP_MAX_CENTS`, 200 €) con margine `TOPUP_MARGIN` (10%): 20 € danno circa 13,3 $. Il credito sta
in due tasche separate:

- **credito del periodo**: si usa per primo e a ogni rinnovo riparte dalla quota del piano, quello non
  usato si perde;
- **ricariche**: si usano solo quando il credito del periodo è finito, non si perdono al rinnovo né
  alla disdetta, e scadono dopo `TOPUP_VALID_DAYS` (365 giorni; le azzera il cron).

A ogni evento (rinnovo, ricarica, disdetta, scadenza) il Worker legge quanto ha speso la chiave
dall'ultimo conteggio, lo scala prima dal periodo e poi dalle ricariche (la più vicina alla scadenza
per prima) e porta il tetto a **speso finora + credito residuo**. Il saldo ricariche mostrato
nell'app è quello dell'ultimo conteggio; il credito totale rimasto è sempre quello letto da
OpenRouter.

La tabella `orders` registra ogni pagamento con la quota data, per controllare i margini reali.

## API usata dall'app

| Rotta | Cosa fa |
|---|---|
| `GET /v1/plans` | piani e modelli disponibili |
| `POST /v1/auth/start` `{email}` | manda il codice (max 5 all'ora) |
| `POST /v1/auth/verify` `{email, code}` | restituisce `{token}` di sessione |
| `GET /v1/me` | stato dell'abbonamento, chiave OpenRouter (se attivo), modelli |
| `POST /v1/checkout` `{plan}` | URL del checkout Polar |
| `POST /v1/topup` `{amount_cents}` | URL del checkout Polar per una ricarica extra |
| `POST /v1/portal` | URL del portale Polar (disdetta, carta, fatture) |
| `POST /v1/auth/logout` | chiude la sessione |
| `POST /webhooks/polar` | webhook firmati di Polar |

Il saldo residuo l'app lo legge direttamente da OpenRouter con la chiave dell'utente
(`GET https://openrouter.ai/api/v1/key`).

## Messa in funzione

Servono account su Cloudflare, Polar, OpenRouter e Resend (per le email). Si parte in **sandbox**:
pagamenti finti con la carta `4242 4242 4242 4242`, chiavi OpenRouter vere ma con tetti di centesimi.

1. **OpenRouter.** Carica il saldo iniziale (consigliati 15 $, sopra quella soglia la commissione è
   solo 5,5%) e attiva la ricarica automatica. Crea una **Management key** (Settings › Management
   keys). Lascia spento *Input & Output Logging*. Facoltativo ma consigliato: crea una **Guardrail**
   con la lista dei modelli del pool e Zero Data Retention, e annota il suo id.
2. **Polar.** Su [sandbox.polar.sh](https://sandbox.polar.sh) crea l'organizzazione, un prodotto
   per ogni piano (3,99 € mensile, 17,99 € ogni 6 mesi, 29,99 € annuale) e annota gli id. Per le
   ricariche crea un prodotto **una tantum** con prezzo **a scelta del cliente** (minimo 5 €) e mettine
   l'id in `TOPUP_PRODUCT_ID`. Crea un access token. Aggiungi un
   webhook verso `https://<tuo-worker>/webhooks/polar` con gli eventi `order.paid` e
   `subscription.*`, e annota il segreto.
3. **Resend.** Verifica un dominio (o usa quello di prova) e crea una API key.
4. **Cloudflare.**
   ```sh
   cd cloud
   npm install
   npx wrangler login
   npx wrangler d1 create rt-cloud          # copia l'id in wrangler.toml
   npm run db:migrate
   npx wrangler secret put OPENROUTER_MANAGEMENT_KEY
   npx wrangler secret put POLAR_ACCESS_TOKEN
   npx wrangler secret put POLAR_WEBHOOK_SECRET
   npx wrangler secret put RESEND_API_KEY
   npx wrangler secret put ADMIN_EMAIL               # dove arrivano gli avvisi sul saldo
   npx wrangler secret put OPENROUTER_GUARDRAIL_ID   # facoltativo
   openssl rand -base64 32 | npx wrangler secret put KEY_ENCRYPTION_SECRET
   ```
   Poi in `wrangler.toml` metti in `ALLOWED_EMAILS` le email degli amici che provano (in sandbox
   è obbligatorio: la carta di prova è finta ma il credito OpenRouter è vero), e l'id del prodotto Polar in `PLANS`, i modelli in `MODEL_POOL`,
   il mittente in `MAIL_FROM`, e pubblica con `npm run deploy`.

**Il `KEY_ENCRYPTION_SECRET` non va mai cambiato né perso**: senza, le chiavi salvate non si
leggono più.

### Passare ai pagamenti veri

1. Ricrea prodotto, access token e webhook su [polar.sh](https://polar.sh) (la sandbox è separata).
2. Aggiorna `PLANS` e i segreti Polar, metti `POLAR_ENV = "production"` e ripubblica.

Prima di farlo: conferma da OpenRouter che il caso d'uso è permesso (i Termini standard vietano la
rivendita di accesso alle API) e sistema la parte fiscale.

## Sviluppo

```sh
npm test          # vitest, con un D1 finto sopra node:sqlite e lo schema vero
npm run typecheck
```
