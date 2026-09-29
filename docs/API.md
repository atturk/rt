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
| `GET /lessons?materia=&state=&q=` | Elenco con stato fasi, issue pendenti, costo (`q`: testo su cartella, titolo, argomenti, materia; la SPA carica l'elenco completo e filtra nel browser) | dashboard `rt` |
| `GET /lessons/{id}` | Dettaglio: fasi con motivo, costi, outline approvata, audio; `actions` dice se recall, immagini e download sono disponibili e, se no, cosa manca (bastano prepare, outline e rewrite VALID) | `rt status`, `rt cost` |
| `GET /lessons/{id}/phases` | Freschezza fasi e report di validazione; la fase `build` ha `warnings`, gli avvisi di integrità della revisione (review non aggiornata, incompleta o mancante, issue da valutare, issue orfane) che non bloccano il build; `manual_validation` (quando, da dove, stato di prima) se la fase è stata validata a mano e non più eseguita | `rt validate-outline`, `rt validate-draft`, `rt status` |
| `POST /lessons/{id}/phases/{fase}/validate` | Segna una fase STALE (o parziale ma completa) come VALID con i file attuali, senza rieseguirla. `409 phase_not_validatable` se l'artefatto manca o non è valido, se una fase a monte non è valida (va validata o eseguita prima) o se la fase resterebbe incompleta; `409 lesson_busy` con un job in coda o in esecuzione, `409 document_edit_busy` con l'editor aperto. Le fasi a valle si ricalcolano dalle loro impronte | `rt validate-phase <lezione> <fase>` |
| `GET /lessons/{id}/document` | Markdown, HTML sanificato, timecode per unità (da `segments.json`); nell'HTML l'intestazione di ogni unità ha `data-unit-id` e la riga del suo timecode `data-unit-timecode`. `final` è vero solo con il documento finale aggiornato; altrimenti è l'anteprima, cioè quello che il build produrrebbe ora | anteprima / file finale |
| `GET /lessons/{id}/audio` | Audio della lezione, con `Range`; solo file audio della lezione (cartella o `media/`) | — |
| `GET /lessons/{id}/export?format=markdown\|zip&scope=final\|all` | Download: Markdown finale (`markdown`), oppure zip con Markdown, errori concettuali e immagini (`final`) o con tutti i file della lezione (`all`). Senza documento finale aggiornato, con la bozza pronta, esporta l'anteprima: "(anteprima)" nel nome dei file e un `LEGGIMI - anteprima.txt` nello zip | `rt export` |
| `GET /lessons/{id}/outline` | Albero dell'outline e approvazione | approvazione outline |
| `GET /lessons/{id}/issues?status=pending\|all` | Issue con contesto (unità, timecode, finestra audio) e decisione | `rt review` |
| `GET /lessons/{id}/decisions` | Ledger (`review_decisions.json`) | `rt status --issues` |
| `GET /costs` | Costi LLM di tutte le lezioni, per lezione e per job | `rt cost` |

Il riepilogo di ogni lezione in `GET /lessons` (freschezza delle fasi, issue pendenti, costi)
richiede centinaia di letture; il processo dell'API lo tiene in cache per lezione. La chiave è
un'impronta degli input calcolata a ogni richiesta con due query (nome, hash, mtime e
dimensione dei file della lezione nel DB; numero e ultimo id delle chiamate LLM) più uno `stat`
dei file per le lezioni ancora in cartella: ogni scrittura, anche dal worker, dalla CLI o dal bot,
cambia l'impronta e la lezione si ricalcola. Con 20 lezioni la prima richiesta costa circa
0,9 s, le successive circa 40 ms.

### Impostazioni (RT4-E4)

La logica vive in `rt/services/settings_service.py` e `rt/services/connections_service.py`
(spostati da `rt/web/`, che li reimporta per Gradio). Nessuna risposta contiene un valore
segreto: solo `set: true/false` (per token e Chat ID di Telegram anche un'anteprima con primi e
ultimi caratteri; il valore completo solo con `POST /settings/telegram/reveal`).

| Metodo e percorso | Cosa fa | Equivalente CLI |
|---|---|---|
| `GET /settings` | Cartella lezioni, trascrizione, Telegram, sei fasi, connessioni, credenziali, pricing, ricerca web (`web_search`); `data_dir` (dove stanno `rt.db` e `media/` per questo processo) e `setup_required` (cartella lezioni non impostata o inesistente: la SPA apre la configurazione guidata) | `rt config` |
| `PUT /settings/lessons-root` | Cartella delle lezioni | `rt config` |
| `PUT /settings/worker` | Job in parallelo del worker di `rt web` (1-4, default 2); `GET /settings` riporta anche i worker attivi ora | `rt worker --concurrency` |
| `PUT /settings/transcription` | Motore STT (macparakeet o server compatibile) | `rt config` |
| `PUT /settings/telegram` | Token, chat, topic per materia | `rt config --telegram` |
| `POST /settings/connections` | Nuova connessione (provider, base URL, chiavi) | `rt config --models` |
| `POST /settings/connections/{name}/models` | Aggiunge un modello | `rt config --models` |
| `PUT /settings/phases/{job}` | Connessione e modello per outline, rewrite, review, recall, image_description, image_unit_judge | `rt config --models` |
| `GET/PUT /settings/routes/{job}/{role}` | Route primaria, secondaria, fallback | file `config/*.yaml` |
| `PUT /settings/pricing` | Pricing custom per provider e modello | `rt config` |
| `POST /settings/models/test` | Prova connessione e modello (anche non salvati): chiamata minima e sincrona (prompt di poche parole, 16 token di uscita, timeout 20 s) con esito, latenza, stato HTTP ed errore del provider sanificato; con `mock` o `RT_API_MOCK=1` risponde subito senza rete | — |
| `PUT /settings/web-search` | URL base di SearXNG (`searxng_base_url` in `general.yaml`, vuoto lo toglie); letto da `add_images` | `config/general.yaml` |
| `POST /settings/web-search/test` | Ricerca immagini di prova su SearXNG (timeout 10 s): numero di risultati, o l'errore (anche il formato json non abilitato) | — |
| `PUT /settings/notices` `{notice, dismissed}` | "Non mostrare più" per gli avvisi della SPA (`preview_edit_beta`, `preview_edit_issues`), salvato in `ui.dismissed_notices` di `general.yaml`; `GET /settings` li riporta in `notices.dismissed` | — |
| `PUT /secrets/{name}` | Scrive un segreto dichiarato (archivio cifrato se inizializzato, altrimenti `.env`) | `rt secrets set` |
| `GET /telegram/daemon`, `POST /telegram/daemon/start`, `/stop` | Stato, avvio e arresto del bot | `rt telegram-daemon` |
| `POST /settings/telegram/reveal` `{field: bot_token\|chat_id}` | Valore completo del token o del Chat ID, solo su richiesta esplicita (`Cache-Control: no-store`); `GET /settings` ne dà solo l'anteprima (`bot_token_preview`, `chat_id_preview`, es. `1234…wXyZ`) | — |
| `POST /settings/telegram/test-topic` `{topic_id, materia}` | Invia nel topic "Questo è il topic di MATERIA"; esito nella risposta | — |
| `GET /settings/telegram/listen-messages` | Messaggi ricevuti durante l'ultimo ascolto riuscito dei topic (quanti, se già cancellati) | — |
| `POST /settings/telegram/listen-messages/delete` | `deleteMessage` solo di quei messaggi (mai quelli di servizio): quanti eliminati e quali no, con il motivo (più vecchi di 48 ore, permessi) | — |
| `GET /telegram/notifications?limit=` | Ultime notifiche inviate dal bot (lezione pronta, issue, prove dei topic), dal registro `notifications.jsonl` nella cartella di stato Telegram | — |
| `POST /system/choose-folder` `{start?}` | Finestra di Finder (`osascript` 'choose folder') e percorso POSIX scelto; `unavailable` fuori da macOS (o con `RT_NATIVE_FOLDER_PICKER=0`), `cancelled` se annullata. Solo da loopback | — |
| `GET /system/folders?path=` | Sottocartelle (niente file, niente cartelle nascoste) di una cartella della home, per il navigatore della SPA. Solo da loopback e dentro la home | — |

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
| `POST /lessons/{id}/document/check` `{markdown}` | Anteprima renderizzata (HTML sanificato) del Markdown in modifica ed errori che ne impedirebbero il salvataggio, `[{line, message}]`; non salva niente | — |
| `PUT /lessons/{id}/document/draft` `{markdown}` | Modifica dell'anteprima (RT4-FA3, beta): riporta il Markdown nella bozza per unità. Titoli di sezioni e unità e timecode vanno in `document_edits.json`; il timecode (riga sotto il titolo dell'unità, `MM:SS` o `H:MM:SS`) deve stare nella durata dell'audio, crescere da un'unità alla successiva e viene spostato all'inizio del segmento che lo contiene. Le unità cambiate non ricevono più le decisioni della revisione (sono già nel testo); le issue il cui testo non c'è più diventano orfane, non si cancellano. Il documento finale diventa da ricreare (`build_status: STALE`). Errori: `422 document_invalid` con `details.errors` `[{line, message}]` (sezioni o unità aggiunte, tolte o spostate, timecode fuori dall'audio o fuori ordine, unità vuote, immagini inesistenti, rielaborazione non aggiornata); `409` con un job in corso sulla lezione | modifica a mano del Markdown esportato |
| `POST /lessons/{id}/images` (multipart `files`, `web_search`, `units`) | Job `add_images`: `web_search` è il numero di immagini da cercare sul web **per ogni unità** (una ricerca per unità, 1-10), `units` limita la ricerca alle unità scelte (vuoto = tutte). Senza SearXNG configurato risponde subito `409 searxng_not_configured`, senza accodare il job | `rt add-images [--web-search N] [--units 1.1,2.3]` |
| `GET /lessons/{id}/images`, `GET /lessons/{id}/assets/images/{nome}` | Immagini integrate (descrizione, origine, presenza nel documento mostrato da `/document`) e file per l'anteprima: l'HTML di `/document` le richiama come `assets/images/{nome}` | `rt add-images` |
| `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel` | Stato e annullamento; `retry_of` e `retried_by` collegano un job fallito e il suo nuovo tentativo | `rt jobs` |
| `POST /jobs/{id}/close` | Chiude un job in attesa delle issue della review o dell'approvazione della scaletta senza annullarlo: finisce `succeeded` con `result.closed` (`kind`, `message`), le issue restano da valutare (o la scaletta da approvare) e decidere dopo non fa ripartire il job. `409 job_not_closable` se il job non è in attesa o aspetta i dati della lezione | `rt jobs close ID` |
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
| `GET /lessons/{id}/recall/session` | Sessione in corso qui (`web`) e su Telegram (`telegram`), ultimo riepilogo (`last`), ultima richiesta al bot (`command`) | — |
| `POST .../recall/session/end` | Termina la sessione della web app e ne salva il riepilogo (domande, risposte date, quiz giusti); 404 se non ce n'è una | uscita da `rt recall` |
| `GET /recall/telegram` | Bot pronto per il recall (`configured`, `running`) e sessioni in corso su Telegram per tutte le lezioni | — |
| `POST /lessons/{id}/recall/telegram/start` `{qtype}` | Chiede al bot di avviare il recall nel topic della materia (202; l'esito in `/recall/session`); 409 se il bot non è configurato o è fermo, o se c'è già una sessione | `rt recall --channel telegram`, `/recall` nel bot |
| `POST /recall/telegram/sessions/{id}/stop` | Interrompe una sessione su Telegram: il bot la chiude e scrive nel topic «Sessione interrotta dall'app» | `/quit` nel bot |
| `POST /settings/test-credential` | Job `credential_test`: chiamata minima, esito sanificato | — |
| `POST /settings/telegram/listen-topics` | Job `telegram_listen_topics`: ascolta 20 s i messaggi al bot (getUpdates) e restituisce `chat_id` e `topics` visti, `names` (nome del topic da `forum_topic_created`/`forum_topic_edited` o dal `reply_to_message`), `materie` (materia nota che coincide con il nome) e `messages` (chat e message id dei messaggi degli utenti, per la cancellazione) | web Gradio "Ascolta topic" |

Il build (`run_phase` con `phase: build`) richiede prepare, outline e rewrite aggiornati; la
review non è una dipendenza (i suoi problemi sono gli avvisi di `GET /phases`). Il job
`add_images` lavora sulla bozza: salva il posizionamento delle immagini
(`assets/images/placement.json`), che l'anteprima mostra subito e il build successivo include;
un documento finale già creato diventa STALE.

Nelle fasi a unità gli eventi `phase_progress` portano `current`/`total` (posizione dell'unità
nella lezione), `unit_id`, `unit_title` e `failed` (unità non riuscite finora); `phase_completed`
ha `partial: true` se alcune unità sono fallite (`result.failed_units` con unità, etichetta e
messaggio). Una fase parziale ferma la pipeline e il job fallisce con il motivo leggibile.
`POST /lessons/{id}/jobs` accetta `mock_fail_once` (`rewrite` o `review`, solo con `mock=true`)
per i test: la prima unità di quella fase fallisce una volta con una risposta fuori schema.

**Sessioni di recall (RT4-FA7).** La tabella `recall_sessions` è il registro condiviso delle
sessioni: la web app apre la sua con la prima domanda (`/recall/next`) e la chiude con
`/recall/session/end`; il daemon Telegram registra e chiude le sue (da `/recall`, `/quit`, fine
della riserva o interruzione dall'app). L'API non parla con Telegram: scrive le richieste nella
tabella `telegram_commands` e il daemon le esegue ogni due secondi, scrivendone l'esito. Mentre
una sessione è su Telegram la web non pone domande di quella lezione (`409
telegram_session_active`), e viceversa.

Le decisioni registrano `channel=api` e l'attore. Con un job in esecuzione sulla lezione le
decisioni rispondono `409 lesson_busy`. I file caricati vanno in
`<lessons_root>/.rt/uploads/` e si cancellano quando il job finisce (restano se si ferma su una decisione); il limite di
dimensione è `RT_API_MAX_UPLOAD_MB` (default 2048).

`rt worker --mock` esegue ogni job in mock qualunque cosa chieda il client (LLM finto, risposte
vocali senza trascrizione, immagini dal web generate senza SearXNG, giudice delle immagini che
le mette nella prima macro-sezione): lo usa il server dei test end-to-end della SPA
(`scripts/e2e_server.py`), insieme al bot Telegram finto (`RT_TELEGRAM_FAKE=1`: prende il PID
file, non riceve aggiornamenti ed esegue le richieste della web app con domande in mock sulla
Bot API di `RT_TELEGRAM_API_URL`).

## Parità con la CLI (RT4-E5)

`docs/RT4_PARITY.md` riporta la tabella del piano con lo stato di ogni riga.
`tests/test_api_parity.py` esegue ogni processo via CLI e via API su due copie della stessa
lezione in mock e confronta file, fasi, ledger e costi; `tests/test_api_persistence.py`
rilegge ogni scrittura da un processo nuovo.
