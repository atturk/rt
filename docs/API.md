# API REST di RT (RT 4.0, fase E)

L'API espone a una web app (la SPA della fase F) e a script tutto quello che oggi si fa
dalla CLI. Usa solo il service layer (`rt/services`) e il database (`rt/db`): nessuna
logica di dominio vive in `rt/api`.

## Avvio

```bash
rt api                 # http://127.0.0.1:8765/api/v1, documentazione su /docs
rt api --reset-token   # genera e mostra un nuovo token
rt api --port 9000
rt api --dev-cors      # consente le richieste della SPA in sviluppo (localhost:5173)
```

- Ascolta solo su `127.0.0.1` per default; `--host` diverso stampa un avviso.
- Al primo avvio stampa un **token** (una sola volta). Nel DB resta solo l'hash
  (tabella `settings`, chiave `api.auth`).
- Autenticazione: `Authorization: Bearer <token>`; nella pagina `/docs` il pulsante
  **Authorize**. La SPA apre una sessione con `POST /api/v1/auth/session` (cookie HttpOnly,
  SameSite=Strict) e ripete il cookie `rt_csrf` nell'header `X-CSRF-Token` per le scritture.
- **Link monouso** (fase F): `rt web` apre il browser su `/login?code=...`, che apre la
  sessione senza incollare il token; lo stesso link si crea con `POST /api/v1/auth/login-link`
  (con il token). Il codice vale 5 minuti e una sola volta.
- `--no-auth` disattiva l'autenticazione, solo su loopback.
- CORS: nessuna origine per default; `--dev-cors` o `RT_API_CORS_ORIGINS=origine1,origine2`.

## SPA sulla stessa origine

Se la build della SPA esiste (`RT_SPA_DIR`, `rt/spa` nelle release o `frontend/dist` in
sviluppo), FastAPI la serve su `/`: i file della build, e `index.html` per ogni altra rotta che
non sia `/api`, `/docs` o `/openapi.json`. Niente CORS in produzione.
`rt web` avvia API, SPA e un `rt worker` insieme (Ctrl+C li ferma tutti).

## Errori

Ogni errore ha la forma `{"error": {"code": "...", "message": "...", "details": ...}}`.
I messaggi passano dal sanificatore delle credenziali; un errore inatteso è un 500 generico.

## Schema

`docs/openapi.json` è lo schema esportato da `python scripts/export_openapi.py` (un test
verifica che sia aggiornato). La SPA ne genera il client TypeScript.

## Endpoint

Tutti sotto `/api/v1` e autenticati, salvo `GET /health` e `POST /auth/session`.
Le lezioni hanno un id numerico stabile (riga `Lesson` del DB): resta lo stesso anche quando
`rt build` rinomina o sposta la cartella.

### Lettura (RT4-E2)

| Metodo e percorso | Cosa restituisce | Equivalente CLI |
|---|---|---|
| `GET /lessons?materia=&state=&q=` | Elenco con stato fasi, issue pendenti, costo | dashboard `rt` |
| `GET /lessons/{id}` | Dettaglio: fasi con motivo, costi, outline approvata, audio | `rt status`, `rt cost` |
| `GET /lessons/{id}/phases` | Freschezza fasi e report di validazione | `rt validate-outline`, `rt validate-draft` |
| `GET /lessons/{id}/document` | Markdown, HTML sanificato, timecode per unità (da `segments.json`); nell'HTML l'intestazione di ogni unità ha `data-unit-id` e la riga del suo timecode `data-unit-timecode` | anteprima / file finale |
| `GET /lessons/{id}/audio` | Audio della lezione, con `Range`; solo file audio della lezione (cartella o `media/`) | — |
| `GET /lessons/{id}/export?format=markdown\|zip&scope=final\|all` | Download: Markdown finale (`markdown`), oppure zip con Markdown, errori concettuali e immagini (`final`) o con tutti i file della lezione (`all`) | `rt export` |
| `GET /lessons/{id}/outline` | Albero dell'outline e approvazione | approvazione outline |
| `GET /lessons/{id}/issues?status=pending\|all` | Issue con contesto (unità, timecode, finestra audio) e decisione | `rt review` |
| `GET /lessons/{id}/decisions` | Ledger (`review_decisions.json`) | `rt status --issues` |
| `GET /costs` | Costi LLM di tutte le lezioni, per lezione e per job | `rt cost` |

### Impostazioni (RT4-E4)

La logica vive in `rt/services/settings_service.py` e `rt/services/connections_service.py`
(spostati da `rt/web/`, che li reimporta per Gradio). Nessuna risposta contiene un valore
segreto: solo `set: true/false`.

| Metodo e percorso | Cosa fa | Equivalente CLI |
|---|---|---|
| `GET /settings` | Cartella lezioni, trascrizione, Telegram, sei fasi, connessioni, credenziali, pricing; `data_dir` (dove stanno `rt.db` e `media/` per questo processo) e `setup_required` (cartella lezioni non impostata o inesistente: la SPA apre la configurazione guidata) | `rt config` |
| `PUT /settings/lessons-root` | Cartella delle lezioni | `rt config` |
| `PUT /settings/worker` | Job in parallelo del worker di `rt web` (1-4, default 2); `GET /settings` riporta anche i worker attivi ora | `rt worker --concurrency` |
| `PUT /settings/transcription` | Motore STT (macparakeet o server compatibile) | `rt config` |
| `PUT /settings/telegram` | Token, chat, topic per materia | `rt config --telegram` |
| `POST /settings/connections` | Nuova connessione (provider, base URL, chiavi) | `rt config --models` |
| `POST /settings/connections/{name}/models` | Aggiunge un modello | `rt config --models` |
| `PUT /settings/phases/{job}` | Connessione e modello per outline, rewrite, review, recall, image_description, image_unit_judge | `rt config --models` |
| `GET/PUT /settings/routes/{job}/{role}` | Route primaria, secondaria, fallback | file `config/*.yaml` |
| `PUT /settings/pricing` | Pricing custom per provider e modello | `rt config` |
| `PUT /secrets/{name}` | Scrive un segreto dichiarato (archivio cifrato se inizializzato, altrimenti `.env`) | `rt secrets set` |
| `GET /telegram/daemon`, `POST /telegram/daemon/start`, `/stop` | Stato, avvio e arresto del bot | `rt telegram-daemon` |

Il bot parte come processo separato in una sessione propria (sopravvive all'API) e il lock
del PID file in `~/.rt/` impedisce i duplicati; lo stop invia SIGTERM. Un servizio launchd
dedicato arriva con la fase G.

### Scritture, job ed eventi live (RT4-E3)

Le operazioni lunghe sono job della coda della fase D (`rt/services/jobs.py`), eseguiti da
`rt worker`: l'endpoint risponde `202` con `job_id` e `worker_available` (falso se nessun
worker è attivo: il job resta in coda finché non ne parte uno). I tipi standard
(`run_pipeline`, `ingest_audio`, `run_phase`, `add_images`, `recall_generate`) sono quelli di
`rt/services/job_handlers.py`; quelli aggiuntivi usati solo dall'API (`rewrite_unit`,
`recall_batch`, `recall_refill`, `recall_evaluate`, `outline_revision`, `credential_test`, `telegram_listen_topics`) stanno in
`rt/services/api_jobs.py`.

| Metodo e percorso | Cosa fa | Equivalente CLI |
|---|---|---|
| `POST /lessons` (multipart: `audio`, `date`, `materia`, `argomenti`, `mock`, `run`) | Job `ingest_audio` (solo setup e trascrizione); con `run=true` job `run_pipeline` dall'audio | `rt setup`, `rt run lezione.m4a` |
| `POST /lessons/{id}/jobs` `{type: run_pipeline}` | Pipeline completa | `rt run <cartella>` |
| `POST /lessons/{id}/jobs` `{type: run_phase, phase, unit?}` | Una fase (`unit` solo per il rewrite: job `rewrite_unit`) | `rt prepare/outline/rewrite/review/build` |
| `POST /lessons/{id}/images` (multipart `files`, `web_search`) | Job `add_images` | `rt add-images` |
| `GET /lessons/{id}/images`, `GET /lessons/{id}/assets/images/{nome}` | Immagini integrate (descrizione, origine, presenza nel documento finale) e file per l'anteprima: l'HTML di `/document` le richiama come `assets/images/{nome}` | `rt add-images` |
| `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel` | Stato e annullamento; `retry_of` e `retried_by` collegano un job fallito e il suo nuovo tentativo | `rt jobs` |
| `POST /jobs/{id}/retry` | Riprova un job fallito (RT4-FA1): job nuovo con lo stesso tipo e payload (senza `force` per pipeline e fasi), che riparte dalla fase fallita; `409 lesson_busy` se sulla lezione c'è un altro job attivo, `409 already_retried` (con il job nuovo) se è già stato ripreso, `409 retry_unavailable` se i file caricati non ci sono più | rilanciare lo stesso comando |
| `GET /jobs/{id}/events` | Server-Sent Events; riprende da `Last-Event-ID` o `?after=` | output di `rt run` |
| `GET /workers` | Worker attivi | — |
| `POST /lessons/{id}/outline/approve` | Approva l'outline; il job in attesa riparte da solo | approvazione outline |
| `POST /lessons/{id}/outline/revise` | Job `outline_revision` con feedback | "modifica" nell'approvazione |
| `POST /lessons/{id}/issues/{issue_id}/decision` | accepted, rejected, edited (con testo); con l'ultima decisione il job riparte | `rt review` |
| `POST /lessons/{id}/decisions/undo` | Annulla l'ultima decisione su un'issue | "annulla" in `rt review` |
| `GET /lessons/{id}/recall`, `GET .../recall/history` | Riserva per tipo e stato; domande (con soluzione se già poste) e risposte con valutazione e voto | `rt recall` |
| `POST .../recall/generate`, `POST .../recall/next` | Generazione (job `recall_generate`, o `recall_batch` con `qtype`); prossima domanda, che sotto soglia accoda il rifornimento (job `recall_refill`) come il terminale | `rt recall` |
| `POST .../recall/answer`, `.../answer-voice`, `.../vote`, `.../skip` | Quiz subito; risposte aperte scritte o vocali valutate da un job; voti; salto | `rt recall` |
| `POST /settings/test-credential` | Job `credential_test`: chiamata minima, esito sanificato | — |
| `POST /settings/telegram/listen-topics` | Job `telegram_listen_topics`: ascolta 20 s i messaggi al bot (getUpdates) e restituisce `chat_id` e `topics` visti | web Gradio "Ascolta topic" |

Nelle fasi a unità gli eventi `phase_progress` portano `current`/`total` (posizione dell'unità
nella lezione), `unit_id`, `unit_title` e `failed` (unità non riuscite finora); `phase_completed`
ha `partial: true` se alcune unità sono fallite (`result.failed_units` con unità, etichetta e
messaggio). Una fase parziale ferma la pipeline e il job fallisce con il motivo leggibile.
`POST /lessons/{id}/jobs` accetta `mock_fail_once` (`rewrite` o `review`, solo con `mock=true`)
per i test: la prima unità di quella fase fallisce una volta con una risposta fuori schema.

Le decisioni registrano `channel=api` e l'attore. Con un job in esecuzione sulla lezione le
decisioni rispondono `409 lesson_busy`. I file caricati vanno in
`<lessons_root>/.rt/uploads/` e si cancellano quando il job finisce (restano se si ferma su una decisione); il limite di
dimensione è `RT_API_MAX_UPLOAD_MB` (default 2048).

`rt worker --mock` esegue ogni job in mock qualunque cosa chieda il client (LLM finto, risposte
vocali senza trascrizione, giudice delle immagini che le mette nella prima macro-sezione): lo
usa il server dei test end-to-end della SPA (`scripts/e2e_server.py`), insieme al bot Telegram
finto (`RT_TELEGRAM_FAKE=1`: prende il PID file ma non contatta Telegram).

## Parità con la CLI (RT4-E5)

`docs/RT4_PARITY.md` riporta la tabella del piano con lo stato di ogni riga.
`tests/test_api_parity.py` esegue ogni processo via CLI e via API su due copie della stessa
lezione in mock e confronta file, fasi, ledger e costi; `tests/test_api_persistence.py`
rilegge ogni scrittura da un processo nuovo.
