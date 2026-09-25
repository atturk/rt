# Architettura del Sistema RT 2.0

## 1. Visione Generale

Il sistema RT 2.0 è progettato per risolvere la fragilità insita nei workflow che utilizzano il linguaggio naturale e il Markdown come protocolli di stato interno.

```text
                    ┌─────────────────────┐
                    │      AUDIO/ASR      │
                    │   (macparakeet-cli) │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │ SEGMENTS + TIMESTAMP│ (Codice Deterministico)
                    │   (segments.json)   │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │   GLOBAL OUTLINE    │ (LLM: coordinate segment_id)
                    │    (outline.json)   │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │  CHAPTER REWRITE    │ (LLM: sliding window + provenance)
                    │     (draft.json)    │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │ DETERMINISTIC CHECK │ (Validazione monotonicità e copertura)
                    └──────────┬──────────┘
                               ↓
                 ┌─────────────┴─────────────┐
                 ↓                           ↓
        ┌────────────────┐          ┌────────────────┐
        │   ASR REVIEW   │          │ SCIENCE REVIEW │
        │  (GREEN/YELLOW/│          │ (Critic: DOC/  │
        │      RED)      │          │ RECON/CHECK)   │
        └───────┬────────┘          └───────┬────────┘
                └─────────────┬─────────────┘
                              ↓
                    ┌─────────────────────┐
                    │  HUMAN REVIEW ONLY  │ (Solo YELLOW/RED)
                    │(review_decisions.js)│
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │ DETERMINISTIC BUILD │ (Assemblaggio Markdown puro)
                    │  (rielaborato.md)   │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │ TELEGRAM / OBSIDIAN │
                    └─────────────────────┘
```

---

## 2. Separazione delle Responsabilità

### Responsabilità Deterministica (Codice Python Puro)
- Normalizzazione e parsing dei timestamp in secondi (`float`).
- Generazione degli ID stabili dei segmenti (`seg_000001` ... `seg_N`).
- Tracciamento della macchina a stati in `info.yaml` e `manifest.json`.
- Validazione dell'outline: verifica che i segmenti esistano, siano ordinati cronologicamente e che non ci siano inversioni temporali.
- Calcolo della copertura del trascritto (percentuale coperta, segmenti omessi).
- Confidence gating numerico delle issue ASR.
- Persistenza del `review_decisions.json` (decision ledger).
- Final build: rendering del Markdown con timestamp rigorosamente calcolati dalla formula `segments[start_segment_id].start_seconds`.

### Responsabilità Cognitiva (Job LLM Specializzati)
- **Outline Job**: analisi concettuale del contenuto globale e ripartizione in macro-argomenti e unità didattiche brevi (2-6 minuti).
- **Rewrite Job**: riscrittura in prosa accademica fluida, eliminando il parlato e garantendo continuità didattica senza allucinare dettagli esterni.
- **ASR Review Job**: individuazione delle parole stravolte dall'ASR e proposta di correzioni fonetico-biomediche.
- **Science Review Job (Critic)**: revisione avversaria indipendente per identificare contraddizioni scientifiche distinguendo errori del docente da allucinazioni della ricostruzione.

### Responsabilità Umana (Human-in-the-Loop)
- Intervento limitato esclusivamente ai casi a media/bassa confidenza (**YELLOW** e **RED**), con ascolto audio contestualizzato (`Ascolta MM:SS - MM:SS`).

---

## 3. Gestione della Provenance e Garanzia sui Timestamp

Il problema principale dei sistemi LLM tradizionali è l'allucinazione temporale: l'LLM inserisce timestamp plausibili ma non accurati (es. `36:30` generato come stringa).

Nel nostro sistema:
1. All'LLM è severamente vietato restituire timestamp nei campi dell'outline o del draft.
2. L'LLM restituisce unicamente `start_segment_id: "seg_000184"`.
3. Il renderer deterministico esegue:
   ```python
   start_sec = segments_dict["seg_000184"].start_seconds
   rendered_timestamp = format_timestamp(start_sec)
   ```
4. Se il segmento non esiste nei metadati sorgente, la pipeline si blocca con un errore esplicito.
5. In questo modo si garantisce in modo deterministico che nessun timestamp nel documento finale sia disallineato rispetto a `segments.json`.

> **Nota di precisione**: Questa garanzia copre la coerenza deterministica tra il documento finale e `segments.json`; l'accuratezza di `segments.json` rispetto alla registrazione reale dipende a sua volta dalla correttezza del parsing iniziale della trascrizione grezza.

---

## 4. LLM Routing Engine, Multi-Provider Architecture e Telemetria

Il sottosistema LLM di RT 2.0 disaccoppia interamente i 3 job cognitivi (`outline`, `rewrite`, `review`) dai provider fisici e dalle credenziali attraverso un Routing Engine centrale, multi-provider e multi-modello:

```text
RT Cognitive Jobs (outline, rewrite, review)
                               ↓
                        LLMClient Gateway
                               ↓
                  ┌─────────────────────────┐
                  │   RoutingEngine (RT)    │
                  │ - Round-Robin Scheduler │
                  │ - Error-Aware Failover  │
                  │ - Loop Protection       │
                  │ - Output Explosion Guard│
                  └────────────┬────────────┘
                               ↓
                  ┌─────────────────────────┐
                  │   CredentialRegistry    │
                  │ (google_1, google_2,    │
                  │  openrouter, deepseek)  │
                  └────────────┬────────────┘
         ┌─────────────────────┼─────────────────────┬─────────────────────┐
         ↓                     ↓                     ↓                     ↓
   Google Gemini        Google Gemini             DeepSeek            OpenRouter
 (Project 1: google_1) (Project 2: google_2) (api.deepseek.com)  (openrouter.ai/api/v1)
```

### Caratteristiche Chiave:

1. **Scheduling Policy (Primary vs Round-Robin N-way)**:
   - Ciascun job può definire una singola route `primary` (+ opzionale `secondary`), oppure una lista
     `primary_routes` di N route (es. 9 chiavi per lo stesso provider).
   - Con `round_robin: true`, le chiamate successive dello stesso job alternano in modo deterministico
     e thread-safe su tutte le route configurate, in ordine ciclico (utile per distribuire il carico
     tra più account/progetti con quote indipendenti — vedi `docs/CONFIGURATION_REFERENCE.md`).

2. **Google Dual-Key (Due Progetti Indipendenti)**:
   - Supporto nativo per due account/progetti Google distinti (`google_1` mappato su `GOOGLE_API_KEY_1`, `google_2` mappato su `GOOGLE_API_KEY_2`).
   - Quote e rate limit separati con failover trasparente tra le chiavi.

3. **Tassonomia degli Errori & Error-Aware Failover**:
   Tutti gli errori HTTP e i blocchi del provider vengono classificati in classi formali:
   - `TimeoutFailure`: deadline wall-clock superata -> esaurisce eventuali retry bounded locali sulla stessa route, poi commuta su `fallback.timeout`.
   - `RateLimitFailure`: HTTP 429 / quota esaurita -> commuta immediatamente su `fallback.rate_limit`.
   - `SafetyFailure`: content filter / promptFeedback / finishReason Gemini/OpenRouter -> commuta su `fallback.safety`.
   - `AuthenticationFailure`: HTTP 401/403 -> commuta su `fallback.auth` (cambio credenziale/provider esplicito senza riprovare la chiave invalida).
   - `OutputLimitFailure`: superamento limite rigido caratteri -> retry bounded same-route (fino a 2 tentativi extra con payload invariato per campionare un backend diverso), poi failover su `fallback.generic`.
   - `ReasoningRequiredFailure`: il modello selezionato (tipicamente dietro un router aggregatore come `openrouter/free`) impone il reasoning obbligatorio non configurato -> retry bounded sulla stessa route (fino a 2 tentativi extra), con escalation locale di `thinking=true` limitata all'ultimo tentativo e mai persistita in config; se anche questo fallisce, commuta su `fallback.generic` come qualunque altro errore non classificato.
   - `SuspiciousFastResponseFailure`: risposta sintatticamente valida ma sospettosamente veloce da un modello free-tier (`< min_elapsed_seconds`, es. 5s per `review`) -> scartata precauzionalmente con same-route retry ed escalation locale a `thinking=true` condivisa con `ReasoningRequiredFailure` (categoria "risposta a basso sforzo"); se esaurita, commuta su `fallback.generic`.
   - `ProviderServerFailure` / `NetworkFailure` / `SchemaFailure`: commutano su `fallback.generic`.

4. **Loop Protection & Bounded Chains**:
   - `visited_routes`: set immutabile di route già tentate (`{provider}|{model}|{credential}`) che impedisce rigorosamente cicli di routing.
   - `max_attempts`: cap globale della catena di esecuzione dell'unità cognitiva.

5. **Output Explosion Guard (Hard Limit)**:
   - Hard limit configurabile (`max_output_chars: 45000` di default) monitorato attivamente chunk-per-chunk durante lo streaming SSE.
   - Interrompe tempestivamente risposte runaway prima dello spreco di token e quote, scatenando il failover.

6. **Telemetria con `execution_id` e Albero delle Esecuzioni**:
   Ogni unità cognitiva genera un `execution_id` univoco condiviso da tutti i tentativi e fallback della catena:
   - `execution_id`: traccia l'intero albero di fallback dell'unità.
   - `attempt` e `parent_attempt`: ricostruiscono la genealogia del routing.
   - `route_id`, `route_role`, `credential_ref`, `failure_class`, `fallback_reason`.
   - Redazione assoluta dei secret: nessun token o API key è presente nei record o messaggi di errore.

7. **Estendibilità & Provider Generico `openai_compatible`**:
   - Supporto nativo per qualsiasi endpoint compatibile con OpenAI Chat Completions API (es. Mistral AI ufficiale, OpenAI ufficiale, Groq, Together.ai, endpoint locali vLLM/Ollama).
   - Registrazione dichiarativa di credenziali custom direttamente via la chiave `credentials:` in `config/general.yaml` senza necessità di modificare il codice sorgente.

8. **Prezzi Custom Dichiarativi (`pricing:`)**:
   - Possibilità di sovrascrivere o definire tariffe USD esatte per token di input, output e reasoning nella configurazione `pricing:` (con priorità assoluta sulle stime hardcoded in `rt/llm/pricing.py`), con esempi dettagliati in `config.example/`.


---

Il workflow RT 2.0 formalizza una Directed Acyclic Graph (DAG) rigorosa definita in `UPSTREAM_DEPENDENCIES`:

```mermaid
graph TD
    prepare[prepare: segments.json] --> outline[outline: outline.json]
    prepare --> rewrite[rewrite: draft.json]
    outline --> rewrite
    prepare --> review_asr[review_asr: asr_issues.json]
    rewrite --> review_asr
    prepare --> review_science[review_science: science_issues.json]
    rewrite --> review_science
    prepare --> build[build: Markdown finali]
    outline --> build
    rewrite --> build
    review_asr --> build
    review_science --> build
```

### Semantica della DAG:
1. **`review_asr` dipende da `prepare` e `rewrite`**:
   L'analisi ASR valuta le issue fonetiche e terminologiche rispetto al testo così come compare ora nel draft (`draft.json`), oltre che sulla trascrizione grezza (`segments.json`), poiché la fase di rewrite può aver già corretto (parzialmente, del tutto o per nulla) alcune ambiguità per conto proprio. Se il draft viene riscritto, le issue ASR vanno quindi rigenerate.
2. **`review_science` dipende da `rewrite` e `prepare`**:
   Il critic scientifico valuta la correttezza concettuale del testo effettivamente riscritto nel draft rispetto al discorso pronunciato dal docente (trascrizione sorgente). Qualsiasi modifica all'outline o al draft invalida transitivamente la review scientifica.
3. **Propagazione Transitiva della Staleness**:
   Quando `check_phase_status` analizza una fase, verifica preliminarmente la presenza fisica dei file su disco (`MISSING`) e successivamente attraversa ricorsivamente tutti i nodi a monte della DAG. Se un qualsiasi input a monte risulta `STALE` o `MISSING`, anche la fase a valle viene classificata come `STALE`.
4. **Stato Effettivo Globale (`compute_effective_workflow_state`)**:
   Lo stato del workflow non si fida ciecamente del valore memorizzato in `info.yaml`. Viene calcolato dinamicamente: se `rewrite` o qualsiasi altra fase a monte è `STALE`, il workflow non potrà mai essere considerato `completato`, ma rifletterà lo stadio non valido più arretrato (es. `outline_validata`).

---

## 6. Grounding Conservativo nel Science Critic

Il Science Critic è un **LLM-based scientific plausibility critic**: analizza la plausibilità concettuale del testo tramite un modello linguistico, non un sistema di verifica bibliografica/RAG contro fonti esterne.

Per evitare allucinazioni in cui il modello attribuisce ingiustamente al docente errori generati in realtà dal modello durante il rewrite:
1. **`ERR_DOCENTE`** richiede forte riscontro testuale o lessicale nella trascrizione sorgente del docente (punteggio di grounding $\ge 0.65$). Viene corredato di domanda diplomatica per chiarimenti.
2. **`ERR_RECONSTRUCTION`**: se il claim criticato non ha alcun riscontro nella sorgente ($\le 0.20$), il sistema lo riclassifica automaticamente come allucinazione del modello, sollevando il docente da colpe inesistenti.
3. **`SCIENCE_CHECK`**: in presenza di evidenza parziale o ambigua, la critica viene instradata a revisione umana neutrale senza trarre conclusioni affrettate.

---

## 7. Service layer (RT 4.0, fase A)

Il motore (`rt/pipeline`, `rt/core`) non parla più direttamente con l'utente: le interfacce
(CLI, Telegram, web, in futuro API e worker) passano da `rt/services/`.

- **Eventi** (`rt/services/events.py`): `PhaseStarted`, `PhaseProgress`, `PhaseCompleted`,
  `PhaseFailed` (messaggio già sanificato), `CostUpdated`, `DecisionRequired`, `Notice`. Chi
  ascolta implementa il protocollo `Reporter` (`emit(event)`); ci sono `NullReporter`,
  `ListReporter`, `CallbackReporter`, `FanOutReporter`.
- **Contesto di esecuzione** (`rt/services/context.py`): `RunContext` con `lesson_dir`,
  `force`, `force_mock`, `reporter`, `telemetry` (un `TelemetryStore` per run) e
  `cancel_token`. `run_prepare/outline/rewrite/review/build` accettano `ctx=` opzionale:
  emettono gli eventi di fase e, durante la fase, il client LLM registra i costi nella
  telemetria del contesto (`rt.llm.telemetry.current_telemetry()`, `GLOBAL_TELEMETRY` se non
  c'è contesto). Rewrite e review controllano l'annullamento tra un'unità e l'altra
  (`RunCancelled`); le unità già elaborate restano nel checkpoint.
- **Presentazione a terminale** (`rt/cli_reporter.py`): `CliReporter` traduce gli eventi
  nelle stesse righe di sempre (`[n/N] FASE (...)`, `[SKIP]`, riepilogo costi).
- **Orchestratore** (`rt/services/pipeline_service.py`): `run_pipeline(inputs, options, ctx,
  decisions=None, notifiers=())` esegue setup (se l'input è audio) → prepare → outline →
  rewrite → review (opzionale) → build e restituisce un `PipelineResult` con stato
  `COMPLETED`, `WAITING_FOR_DECISION` (con la `DecisionRequired` pendente),
  `SKIPPED_TRANSCRIPTION` o `FAILED` (con l'eccezione). Le decisioni umane passano da un
  `DecisionProvider`: la CLI passa `CliDecisionProvider` (UI Textual/terminale o Telegram);
  senza provider la pipeline si ferma sulla decisione, oppure con `auto_accept` approva
  outline e issue. La notifica di fine build va ai `Notifier` registrati (la CLI registra
  `TelegramBuildNotifier`). `cmd_run` in `rt/cli.py` fa solo parsing, banner, chiamata al
  servizio, riepilogo costi ed exit code.
- **Setup** (`rt/pipeline/setup.py`): `resolve_setup_request()` produce un `SetupRequest`
  validato senza leggere da stdin. I campi mancanti si chiedono a un `SetupPrompter`
  (implementato in `rt/cli_prompts.py` e passato dalla CLI solo con un TTY); senza prompter
  si usano i default di sempre, oppure con `strict=True` si solleva `MissingSetupFields`
  (l'orchestratore senza `DecisionProvider` la trasforma in `DecisionRequired(setup_metadata)`).
  L'annullamento di un prompt è `SetupCancelled` (exit 0 in CLI), gli errori restano `SetupError`.
- **Outline** (`rt/services/outline_service.py`): `get_outline_review()` (albero JSON e stato),
  `approve_outline(lesson_dir, actor, channel)` (registrata in `_state/outline_approval.json`
  con l'hash di `outline.json`, quindi una revisione la invalida), `is_outline_approved()`,
  `request_outline_revision(lesson_dir, feedback, ctx)`. La UI da terminale (app Textual e
  fallback testuale) è in `rt/tui/outline_review.py`; `rt/pipeline/outline_review.py` tiene
  solo la regola di gating `outline_needs_approval()`.
- **Review delle issue** (`rt/services/review_service.py`): punto unico per elencare le issue
  pendenti con contesto (unità, timecode, finestra audio), registrare una decisione
  (`record_review_decision`, con `channel` cli/telegram/web/api e `actor`), annullare
  l'ultima (`undo_last_decision`), applicare l'auto-accept e sapere se la review è completa.
  Ogni scrittura del ledger avviene sotto il lock a file `.rt.lock` della lezione, quindi CLI,
  daemon Telegram e web possono decidere in parallelo senza perdere decisioni. Il ledger
  resta `review_decisions.json` nello stesso formato: `channel`/`actor` compaiono solo nelle
  decisioni che li hanno. L'app Textual è in `rt/tui/issue_review.py`, l'invio via Telegram
  in `rt/telegram/review_channel.py` (porta `ReviewChannel`), la web usa
  `rt/pipeline/review_actions.py` come adattatore sottile; `rt/pipeline/issue_review.py`
  contiene solo regole pure e non importa più `rt.telegram`.
- **Configurazione** (`rt/services/config_service.py`): percorsi (`config/` nella cwd o nel
  progetto, `.env` accanto), lettura/validazione (`validate_config`) e scrittura atomica di
  YAML e testo, `set_env_var` e `set_secret` (archivio cifrato se inizializzato, altrimenti `.env` con
  chmod 600). Il wizard `rt config` è in `rt/tui/configure/` e, come le
  impostazioni web (`rt/web/settings.py`), scrive attraverso il servizio.
- **Segreti** (`rt/security/secrets.py`, fase C): porta `SecretStore` con
  `EnvSecretStore` (sola lettura) ed `EncryptedFileSecretStore` (`config/secrets.enc`,
  Fernet/MultiFernet, chiave master da `RT_MASTER_KEY` o dal portachiavi). `load_env_file`
  riversa lo store in `os.environ` con priorità ambiente esplicito > store > `.env`, quindi
  `CredentialRegistry` e il daemon Telegram non cambiano. Gestione (init, migrate, list,
  set, unset, rotate) in `rt/services/secrets_service.py`, comando `rt secrets` in
  `rt/cli_secrets.py`. Una futura `DbSecretStore` (fase B) implementerà la stessa porta.
- **Active Recall** (`rt/services/recall_service.py`): stato di sessione per lezione, batch
  iniziale, prossima domanda con rifornimento, valutazione delle risposte, domande stale.
  Canali: `rt/telegram/recall_channel.py` (Telegram) e `rt/tui/recall.py` (terminale e
  revisione delle domande stale). `rt/core/version.run_update` restituisce il codice di
  uscita invece di terminare il processo.
- **Regola di layering** (`tests/test_layering.py`, bloccante dalla fine della fase A):
  `rt/pipeline`, `rt/core` e `rt/services` non importano `textual`, `rich.prompt`,
  `questionary`, `rt.telegram`, `rt.tui`, `rt.web` e non chiamano `input()` o `sys.exit()`.

## 8. Database (RT 4.0, fase B)

Il pacchetto `rt/db` aggiunge un database SQLAlchemy 2.0 con migrazioni Alembic. I file della
cartella lezione restano gli artefatti (audio, JSON, Markdown); il DB è indice, stato e storico.

- **Dove vive**: `RT_DATABASE_URL` (variabile d'ambiente, `off` lo disattiva) >
  `database_url` in `config/general.yaml` > SQLite in `<lessons_root>/.rt/rt.db` (oppure
  `~/.rt/rt.db` se `lessons_root` non è impostato). Postgres funziona passando un URL
  `postgresql://…` (driver da installare a parte).
- **SQLite**: WAL, `foreign_keys=ON`, `busy_timeout` 30 s e transazioni `BEGIN IMMEDIATE`,
  così CLI, daemon Telegram e web scrivono in coda senza errori di lock.
- **Creazione automatica** (fase D, `rt/db/bootstrap.py::ensure_database`): ogni comando `rt`
  (tranne `db`, `config` e `secrets`) crea il DB se manca e applica le migrazioni pendenti
  sotto il lock `rt.db.migrate.lock`; se è già aggiornato costa la sola lettura della
  revisione. Al primo avvio con una `lessons_root` configurata importa da solo le lezioni
  esistenti (come `rt db sync`, una volta, segnato in `settings` con `db.initial_import_done`).
  L'utente non lancia mai comandi di database: `rt db upgrade|sync|check|status` restano per
  la diagnosi. Se il DB è illeggibile il comando si ferma (`DatabaseUnavailable`) con le
  istruzioni per ripristinarlo da un backup o ricrearlo dai file. `RT_DATABASE_URL=off`
  resta solo per sviluppo e test; la coda dei job (sezione 9) richiede il DB.
  Nel codice di libreria `get_database()` resta tollerante (None se il DB manca o è rotto)
  e `require_database()` è la variante che solleva.
- **Modelli** (`rt/db/models.py`): `Lesson`, `PhaseRun`, `Issue`, `ReviewDecision`,
  `LlmCall`, `Setting`, `StateDocument`. Migrazioni in `rt/db/migrations/versions`; `tests/test_db_schema.py`
  esegue `alembic check` per garantire che modelli e migrazioni coincidano.
- **Accesso**: `rt/db/repositories.py`, sempre dentro `rt.db.session.session_scope(db)`.
- **Sincronizzazione** (`rt/db/sync.py`): `rt db sync` importa le lezioni di `lessons_root`
  (info.yaml, fasi dal manifest, issue da `science_issues.json`, ledger) senza modificare i
  file ed è idempotente; `rt db check` elenca le differenze tra DB e file. Il dual-write
  (`dual_write_lesson`) aggiorna la lezione nel DB dopo ogni scrittura di `info.yaml`
  (`rt/core/state.py`), `manifest.json` (`rt/core/manifest.py`) e del ledger: per lezione,
  fasi e issue i file restano la fonte di verità, e un errore del DB diventa solo un avviso.
  Le dashboard continuano a scansionare le cartelle perché mostrano la freschezza calcolata
  al momento (`check_phase_status`), che il DB non conserva.
- **Test**: `tests/conftest.py` spegne il DB per ogni test (`RT_DATABASE_URL=off`); la
  fixture `rt_db` ne crea uno temporaneo.

- **Fonte di verità nel DB** (quando il DB esiste):
  - *Decisioni di review* (`rt/db/ledger_store.py`): `record_decision`,
    `revert_last_decision` e `purge_decisions_by_prefix` scrivono nel DB in una transazione e
    riesportano `review_decisions.json` nello stesso formato (chi legge usa ancora il file).
    Gli annullamenti restano nel DB con `reverted_at`. Se il file cambia fuori da RT (hash
    diverso da `Lesson.ledger_sha`) viene reimportato prima della modifica successiva, ed è
    l'unico caso in cui `rt db sync` tocca il ledger. `review_service` tiene la scrittura
    sotto il lock `.rt.lock` della lezione.
  - *Chiamate LLM* (`rt/db/llm_calls.py`): ogni riga di `llm_debug.log` diventa un `LlmCall`
    (la prima volta per una lezione si importa l'intero log); `rt cost` legge dal DB con
    fallback al file.
  - *Stato del daemon Telegram* (`rt/db/state_documents.py`): `active_sessions.json`,
    `registry.json`, `awaiting_feedback.json`, `recall_preferences.json`,
    `last_lesson_per_topic.json`, `telegram_issue_queue.json` e `telegram_audio_sent.json`
    diventano righe di `state_documents` (chiave = percorso del file). Alla prima lettura il
    JSON esistente viene importato e rinominato `.migrated`, mai cancellato.
  Senza DB tutte queste funzioni scrivono i file come prima.

Nuova migrazione: modificare `rt/db/models.py`, poi generare la revisione con Alembic
(`alembic.command.revision(alembic_config(url), message, autogenerate=True)`) e rileggerla.

## 9. Coda dei job e worker (RT 4.0, fase D)

La coda vive nel database (nessun Redis). `rt/services/jobs.py` definisce la porta `JobQueue`
(`enqueue`, `cancel`, `get`, `list`, `events`, `stream_events`) e l'implementazione
`DbJobQueue` sulle tabelle `jobs`, `job_events` e `workers` (migrazione `0003`).

- **Stati**: `queued` → `running` → `succeeded` | `failed` | `cancelled`, più
  `waiting_for_decision` quando la pipeline si ferma su una decisione umana.
- **Lease**: `rt worker` prende un job con `claim` (su SQLite la transazione è
  `BEGIN IMMEDIATE`, su Postgres `SELECT … FOR UPDATE SKIP LOCKED`) e un thread rinnova
  `lease_until` ogni lease/3 secondi. Se il worker muore il lease scade, `requeue_expired`
  rimette il job in coda (`job_requeued`) e un altro worker lo riprende: l'idempotenza per
  fase e il checkpoint per unità del rewrite evitano di ripagare le chiamate LLM già fatte.
  Dopo `max_attempts` prese (default 3) il job fallisce. Ctrl+C sul worker rimette subito
  in coda il job in corso senza contarlo come tentativo.
- **Una lezione, un job**: mentre un job è `running`, `jobs.active_lesson` vale il percorso
  della lezione ed è `UNIQUE`, quindi il DB rifiuta un secondo job mutante sulla stessa
  lezione. In più worker e `rt run` in processo prendono un `flock` su
  `<lezione>/.rt.job.lock` (`rt/core/process_lock.py`), rilasciato dal sistema se il
  processo muore: `rt run` su una lezione che un job sta elaborando si ferma con un messaggio,
  e il worker rimette in coda un job la cui lezione è occupata da `rt run`.
- **Eventi e annullamento**: `JobEventReporter` scrive ogni evento di `rt/services/events.py`
  in `job_events` e aggiorna `jobs.progress`; l'id crescente dell'evento è il cursore per chi
  segue il job (CLI, API/SSE). `cancel` annulla subito un job in coda o in attesa; per uno in
  esecuzione imposta `cancel_requested`, che il worker vede al successivo evento o battito
  e trasforma in `RunCancelled` tra un'unità e l'altra.
- **Handler**: ogni tipo di job ha un handler registrato in `rt/services/job_handlers.py`
  (`JobInfo`, `RunContext`) → `JobOutcome`. Errori sanificati in `jobs.error`.
- **CLI**: `rt worker [--once] [--concurrency N] [--types …]` esegue i job;
  `rt jobs [list|show ID|cancel ID]` li elenca, mostra e annulla. La tabella `workers` tiene
  il battito dei worker (`has_live_worker`), così CLI e daemon sanno se possono accodare.
