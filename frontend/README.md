# SPA di RT (fase F)

Interfaccia web di RT 4.0: React + TypeScript + Vite, Tailwind CSS, componenti in stile
shadcn/ui (`src/components/ui`), TanStack Query, React Router. Parla solo con l'API
(`rt api`, `/api/v1`, vedi `docs/API.md`). Da RT4-F8 è la web di RT (`rt web`, vedi
`docs/WEB.md`); la web Gradio (`rt/web`) resta solo con `rt web --legacy`.

## Avvio

```bash
rt web              # API + worker + SPA su http://127.0.0.1:8765, browser già autenticato
```

Sviluppo con ricarica a caldo:

```bash
rt api                    # terminale 1 (e 'rt worker' se servono i job)
cd frontend && npm install && npm run dev   # terminale 2: http://localhost:5173
```

Il server di Vite inoltra `/api` e `/login?code=` a `127.0.0.1:8765` (cambia con
`RT_API_URL`), quindi la SPA è sempre sulla stessa origine dell'API. Per entrare incolla il
token nella pagina di accesso, oppure crea un link con `POST /api/v1/auth/login-link` e
sostituisci l'host con `localhost:5173`.

## Script

| Comando | Cosa fa |
|---|---|
| `npm run gen:api` | Rigenera `src/api/schema.d.ts` da `docs/openapi.json` (dopo `python scripts/export_openapi.py`) |
| `npm run lint` / `npm run typecheck` | oxlint e TypeScript |
| `npm test` | Vitest (unità) |
| `npm run build` | Build in `dist/`, servita da FastAPI su `/` |
| `npm run e2e` | Playwright contro l'API vera (richiede `npm run build`) |

## Convenzioni

- **Nessuno stato di dominio nel frontend.** I dati arrivano dalle query di TanStack Query
  (`src/api/hooks.ts`); dopo ogni scrittura la mutation invalida le query interessate e la
  pagina rilegge dall'API. Un valore mostrato come salvato deve esserlo sul backend. Nel
  browser restano solo preferenze dell'interfaccia (tema) e filtri nell'URL.
- **Solo il client generato.** Niente `fetch` scritti a mano: `api.GET/POST/...` di
  `src/api/client.ts` (openapi-fetch) con i tipi di `schema.d.ts`, e `unwrap()` per avere i
  dati o un `ApiError` con `code` e `message` dell'API. L'header `X-CSRF-Token` si aggiunge da
  solo alle scritture leggendo il cookie `rt_csrf`. Serve un endpoint nuovo? Aggiungilo in
  `rt/api` con i suoi test, riesporta lo schema e rigenera il client.
- **Una area, un file di rotte.** `src/routes/<area>.tsx` esporta un `Area` (rotte sotto il
  layout autenticato e voci di menu); `src/routes/index.tsx` li elenca. Così le schermate
  delle fasi F2-F6 si sviluppano in parallelo senza toccare gli stessi file.
- **Job ed eventi live.** `src/api/jobs.ts`: `useJobEvents` apre `GET /jobs/{id}/events`
  con `EventSource` (unica eccezione al client generato: openapi-fetch non fa streaming; il
  percorso resta tipizzato). Il browser riprende da solo con `Last-Event-ID`; ogni evento fa
  rileggere il job dall'API, la fine anche lezioni e scaletta. Chi mostra l'avanzamento di un
  job (es. la vista lezione) usa `<JobLive jobId=… />` invece del polling. Gli upload passano da
  `xhrFetch` (`src/api/upload.ts`) per avere la barra di avanzamento, sempre con `api.POST`.
- **Aree attuali**: `lessons` (dashboard e lezione), `recall` (`/recall`, `/lezioni/:id/recall`),
  `images` (`/immagini`, `/lezioni/:id/immagini`), `telegram` (`/bot`; il pannello
  `components/TelegramBotPanel.tsx` si può mettere anche nelle impostazioni). Gli hook di un'area
  stanno in `src/api/<area>.ts`; `src/api/jobStatus.ts` segue un job (`GET /jobs/{id}`) e
  `components/JobProgress.tsx` ne mostra l'avanzamento.
- **Lezioni per id.** Solo gli id numerici e gli endpoint dell'API: mai percorsi di cartelle
  o file su disco.
- **Testi in italiano**, etichette accessibili (`aria-label`, `<label>`), tema chiaro e scuro.
- **Playwright per ogni schermata** (`e2e/`): contro l'API vera servita da
  `scripts/e2e_server.py` (lezioni di prova, worker con `--mock`, bot Telegram finto, microfono finto di Chromium nei test vocali), con ricarica della pagina
  dopo ogni modifica e verifica rileggendo dall'API. Aggiorna la colonna "SPA (F7)" di
  `docs/RT4_PARITY.md` per le righe coperte.
- **Accessibilità controllata con axe** (`e2e/a11y.spec.ts`): ogni pagina nuova va aggiunta
  all'elenco del test, che la controlla nei due temi con le regole WCAG 2 A/AA.

Playwright usa il Chromium che installa `npx playwright install chromium`; per usarne un
altro imposta `PW_CHROMIUM_PATH`. L'interprete Python del server di prova è `RT_PYTHON`
(default `python3`).
