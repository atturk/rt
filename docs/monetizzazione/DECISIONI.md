# Monetizzazione di RT: decisioni

Documento di riferimento per chi lavora su RT (release, QA, piani agy) senza vedere la chat della
monetizzazione. Si aggiorna lo stesso giorno di ogni decisione, con una riga datata nel
[Registro](#registro). Piano esteso e conti: Claude Doc «Monetizzazione RT: ricerca e piano».

## Obiettivo

RT resta un'app locale e gratuita in cui l'utente porta la propria chiave (**BYOK**, come oggi).
Accanto si aggiunge una **modalità facilitata** a pagamento:

- l'utente si iscrive con l'email, paga un abbonamento e RT si configura da solo, senza chiavi né modelli
  da scegliere;
- una parte del pagamento resta al progetto, il resto diventa credito AI su una chiave OpenRouter
  personale con un tetto di spesa;
- il credito del periodo è *use it or lose it*: quello non usato non si accumula;
- **privacy**: i contenuti delle lezioni vanno da RT direttamente a OpenRouter. Il backend del progetto
  vede solo account, pagamenti e tetti, mai il testo.

## Decisioni prese

| Data | Decisione | Perché |
|---|---|---|
| 2026-11-03 | Fornitore AI: **solo OpenRouter**, con un saldo unico del progetto e una chiave figlia per utente (Management API, campo `limit`) | Una chiave per utente con tetto risolve automazione, privacy e use it or lose it; il minimo di 5 $ per acquisto vale solo per il saldo unico |
| 2026-11-03 | Pagamenti: **Polar** come Merchant of Record (gestisce IVA e fatture), prima in **sandbox** con pagamenti finti e amici | Niente partita IVA europea da gestire per l'IVA OSS; la sandbox permette la prova completa senza soldi veri |
| 2026-11-03 | Tutto va costruito pronto per utenti sconosciuti; l'accordo Enterprise con OpenRouter si chiede **dopo** la prova e **prima** di incassare | I termini standard di OpenRouter sembrano vietare la rivendita |
| 2026-11-03 | Backend in `cloud/` dentro il repo: Cloudflare Worker + D1, codici di accesso via email (Resend), chiavi cifrate AES-GCM, controllo orario del saldo | Costo quasi zero con pochi utenti, nessun server da mantenere |
| 2026-11-03 | Il tetto della chiave si aggiorna a ogni pagamento a «speso finora + quota», non con il reset mensile di OpenRouter | Il webhook di pagamento è l'unico segnale affidabile del rinnovo |
| 2026-11-03 | Margine del progetto sugli abbonamenti: **20%** del netto (dopo IVA e commissioni) | Copre commissioni stimate e saldo anticipato |
| 2026-11-03 | Piani: **3,99 €/mese**, **17,99 €/6 mesi**, **29,99 €/anno**. Il credito dei piani lunghi arriva tutto al pagamento | La commissione fissa pesa molto sul mensile; i piani lunghi la diluiscono |
| 2026-11-03 | Saldo OpenRouter iniziale consigliato 10 $ con ricarica automatica | Se nessuno si abbona non si spende nulla: OpenRouter addebita solo i token usati |
| 2026-11-03 | **Ricariche extra** a importo libero da **5 €** (max 200 €), margine **10%**, solo con abbonamento in corso | Chi sceglie un modello caro o usa molto non deve aspettare il rinnovo |
| 2026-11-03 | Credito in **due tasche**: quello del periodo si usa per primo e si perde al rinnovo; le ricariche si usano dopo, non si perdono al rinnovo né alla disdetta, scadono dopo **12 mesi** | Il breakage sul credito mensile resta; la ricarica non protegge il credito del mese |
| 2026-11-03 | Pool modelli senza fascia alta. **GPT-6 Luna** (`openai/gpt-6-luna`) consigliato e usato anche per le immagini; **DeepSeek V4.1 Flash** (`deepseek/deepseek-v4.1-flash`, legge le immagini); DeepSeek V4 Pro unico modello «intelligente»; immagini generate con Meta Muse Image (GPT Image 2 alternativa) | Modelli economici: più lezioni per euro e più margine. Slug e prezzi da verificare su OpenRouter |
| 2026-11-03 | Oltre al pool consigliato, l'utente può scegliere **qualunque modello OpenRouter** da un catalogo filtrato per capacità (visione, generazione immagini) | Libertà per chi vuole spendere di più, senza mantenere una lista a mano |

## Opzioni scartate

- **LiteLLM come proxy nostro**: costa di più al mese e i contenuti passerebbero da un nostro server.
  Si riconsidera solo se OpenRouter rifiuta la rivendita o chiede prezzi Enterprise assurdi.
- **Reset mensile automatico di OpenRouter** (`limit_reset`): non segue la data di rinnovo reale né i
  piani a 6 o 12 mesi.
- **Piano trimestrale a 9,99 €** e **semestre a 15,99 €**: al loro posto il semestre a 17,99 €.
- **Fascia alta nel pool consigliato** (GPT-6.1 Sol, Sonnet 5.5, Gemini 3.1 Pro, GLM-5.3): circa
  1 $ a lezione, troppo per il credito del piano base. Restano sceglibili dal catalogo.
- **Ricariche senza margine o al 20%**: si è scelto il 10%.

## Domande aperte

1. Risposta di OpenRouter sulla rivendita / accordo Enterprise (da chiedere dopo la prova sandbox).
2. Partita IVA e regime fiscale: da sentire con un commercialista prima dei pagamenti veri.
3. Prezzi e slug esatti dei modelli del pool: la rete delle sessioni cloud non raggiunge
   openrouter.ai, vanno verificati.
4. Polar: verificare in sandbox il prodotto con prezzo «a scelta del cliente» e il campo `amount` del
   checkout per le ricariche.
5. Licenza (AGPL-3.0, PR #159) e backend pubblico: valutare se `cloud/` debba restare nel repo pubblico
   o vivere in un repo privato.
6. URL pubblico del backend: finché `DEFAULT_CLOUD_URL` è vuoto la modalità facilitata resta nascosta.

## Parti di RT toccate

Tutto è nascosto finché il backend non è pubblicato (`DEFAULT_CLOUD_URL = None`, sovrascrivibile con
la variabile d'ambiente `RT_CLOUD_URL`). Senza URL l'app si comporta come oggi.

| Area | File | Cosa cambia |
|---|---|---|
| Backend nuovo | `cloud/` | Worker, migrazioni D1, test (vitest). Escluso da installer e Docker (`.gitattributes`, `.dockerignore`) |
| CI | `.github/workflows/cloud.yml` | typecheck e test di `cloud/` |
| Servizio locale | `rt/services/cloud_service.py` | accesso con codice, checkout, portale, sincronizzazione della chiave |
| API locale | `rt/api/routers/cloud.py`, `rt/api/app.py` | rotte `/api/v1/cloud/*`, registrate prima di `readonly` |
| Segreti | `rt/security/secrets.py` | nuovo segreto `RT_CLOUD_TOKEN` (token di sessione, mai la chiave) |
| Flusso chiavi API | connessione OpenRouter «RT Cloud» creata da sola; le fasi `outline`, `rewrite`, `review`, `recall`, `enrichment_writer`, `enrichment_visualizer` passano su di essa solo se l'utente sceglie la modalità facilitata; `image_description` va al modello con visione |
| Onboarding | `frontend/src/components/settings/wizard.tsx` | scelta «Facilitata» o «Con la mia chiave», mostrata solo se RT Cloud esiste |
| Impostazioni | `frontend/src/routes/settings.tsx`, `frontend/src/components/settings/cloud.tsx`, `frontend/src/api/cloud.ts` | sezione RT Cloud nella pagina Modelli: saldo, aggiorna, portale, ricarica |
| Generati | `docs/openapi.json`, `frontend/src/api/schema.d.ts` | rigenerati con `scripts/export_openapi.py` e `npm run gen:api` |

## Impatto su RT

- **PR #158** (verso `main`): aggiunge i file sopra. Il codice condiviso toccato è poco: `rt/api/app.py`
  (una riga di registrazione del router), `rt/security/secrets.py` (un nome in `EXTRA_SECRET_NAMES`),
  `wizard.tsx` e `routes/settings.tsx`. Nessun cambiamento visibile finché RT Cloud non è pubblicato.
- **Branch `claude/rt-4.3.x`**: la 4.3.7 parte da `main` prima della PR #158, quindi non la contiene. Il
  piano agy 4.3.7 non tocca gli stessi file; l'unico conflitto atteso è nei file generati
  (`docs/openapi.json`, `schema.d.ts`), da risolvere rigenerandoli dopo il merge.
- Ricariche extra (prossima PR): toccano solo `cloud/`, `cloud_service.py`, `routers/cloud.py`,
  `cloud.tsx`, `api/cloud.ts` e i file generati.

## Registro

- 2026-11-03: scelti OpenRouter (LiteLLM scartato), Polar in sandbox, backend Cloudflare in `cloud/`, margine 20%.
- 2026-11-03: piani 3,99 €/mese, 17,99 €/6 mesi, 29,99 €/anno; saldo iniziale 10 $ con ricarica automatica.
- 2026-11-03: PR #158 con backend, app e onboarding; Attilio autorizza il merge.
- 2026-11-03: pool senza fascia alta, GPT-6 Luna consigliato, DeepSeek V4.1 Flash, catalogo OpenRouter filtrato per capacità.
- 2026-11-03: ricariche extra da 5 € con margine 10%, due tasche di credito, scadenza 12 mesi. Implementazione pronta, in arrivo in una PR dopo la #158.
- 2026-11-03: creato questo documento.
