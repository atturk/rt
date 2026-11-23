# Piano 4 — Modalità batch dei provider (risposta differita, ~50% di costo)

Branch: `agy/4.3.9-notte-batch` (parte dal risultato di `agy/4.3.9-notte-mac`, che ha parallelizzato i loop).
Solo codice e test unitari con provider finti. **Spento di default**: nessuna chiamata reale cambia finché una
rotta non ha `batch: true`. Commit per fase, push dopo ogni fase.

## Idea
Una fase di un job che fa N chiamate indipendenti (verifica per unità, domande per unità, giudice immagini,
classificatore pagine...) le raccoglie, le manda come UN lotto al provider, salva l'id del lotto, mette il job
in stato `waiting_for_provider` e libera il worker. Il worker controlla i lotti aperti ogni 60 s; quando il
lotto è completo salva ogni risposta in una cache per chiave di richiesta e rimette il job in coda. Il job
riparte dalla stessa fase (le fasi sono già idempotenti), le chiamate trovano la risposta in cache e proseguono.
Così la logica delle fasi non cambia: cambia solo cosa succede dentro `LLMClient` quando la rotta è batch.

## 1. Cache delle risposte per richiesta
- Tabella `llm_deferred` (`rt/db/models.py` + migrazione): `key` (sha256 di provider+modello+messaggi+schema+
  parametri, PK), `job_id`, `lesson_path`, `batch_id` nullable, `provider`, `model`, `request` JSON (corpo pronto
  per il provider), `state` ('pending'|'submitted'|'done'|'error'), `response` JSON (NormalizedResponse),
  `error` Text, `created_at`, `updated_at`.
- `rt/llm/deferred.py`: `request_key(...)`, `get(key)`, `put_pending(...)`, `mark_submitted(keys, batch_id)`,
  `store_results(batch_id, results)`, `pending_for_job(job_id)`, pulizia delle righe `done` più vecchie di 7
  giorni e di quelle dei job terminati.

## 2. LLMClient in modalità batch
- Config rotta (`RouteConfig` in `rt/core/config.py`): `batch: bool = False`. Valido solo se il provider della
  rotta supporta il batch (`supports_batch` nel provider). Per OpenRouter il modello batch è la variante
  `<modello>:batch` (l'utente sceglie il modello; RT aggiunge il suffisso se `batch` è attivo).
- In `call_structured`/chiamate testo: se la rotta è batch e non siamo in mock:
  1. calcola la chiave; se in cache `done` → restituisce la risposta (stesso parsing/validazione/telemetria di
     una risposta sincrona, costo dal `usage` del lotto);
  2. se `error` → solleva l'errore come una chiamata fallita (i retry normali valgono: la chiave si azzera);
  3. altrimenti registra `pending` e solleva `DeferredCall` (nuova eccezione in `rt/llm/errors.py`).
- Immagini (`image_data_url`): OpenRouter batch non accetta base64 per tutti i provider → per le chiamate con
  immagini la rotta batch ricade sulla chiamata sincrona (log "immagini: chiamata immediata").
- Chiamate interattive (chat dello Studio, prove modello in Impostazioni, recall live con l'utente in attesa):
  mai batch. `LLMClient(interactive=True)` o lista di `job_name` esclusi.

## 3. Fasi che raccolgono le chiamate
I loop paralleli (`_parallel_units` in review/recall, `ThreadPoolExecutor` in add_images, classificatore) devono
continuare dopo un `DeferredCall`: raccolgono tutte le chiamate della fase (ognuna registra `pending`), poi
la fase solleva un solo `DeferredPhase(job_id)` alla fine invece di fallire. Helper unico
`run_collecting(items, fn)` in `rt/llm/deferred.py`: esegue tutto, accumula i `DeferredCall`, restituisce i
risultati se nessuno è differito, altrimenti solleva `DeferredPhase`. Le chiamate in sequenza dipendenti (scaletta,
rielaborazione per macro in modalità sequenziale) sollevano `DeferredPhase` alla prima: un lotto da 1 richiesta
(funziona, solo più lento).

## 4. Coda dei job
- `JobState.WAITING_FOR_PROVIDER = "waiting_for_provider"` (attivo, non terminale; `active_lesson` liberato).
  Nel worker (`rt/services/worker.py`), se l'handler solleva `DeferredPhase`: invia i `pending` del job con
  `submit_batch` (un lotto per provider+modello), `mark_submitted`, stato `waiting_for_provider`, evento
  `job_waiting_provider` con numero di richieste e provider, progresso "In attesa del provider (batch)".
- Poller nel worker (thread o passo del loop, ogni 60 s, con backoff su 429): per ogni `batch_id` aperto chiama
  `poll_batch`; a lotto finito `store_results`, poi `resume` del job (stesso meccanismo di `resume` per le
  decisioni, nuovo metodo `resume_after_provider`). Lotto `failed`/`expired`: i job tornano in coda in modalità
  sincrona per quelle chiavi (flag nel payload `batch_fallback: true`) con evento che lo spiega.
- Annullare un job in attesa: stato cancelled, righe `pending/submitted` rimosse (OpenRouter non ha cancel:
  il lotto si lascia finire e si ignora; Gemini ha cancel: chiamarlo).
- UI job (`frontend/src/components/jobs/*`): stato "In attesa del provider" con icona orologio e testo
  "Le risposte arrivano entro 24 ore, a costo ridotto. RT le riceve anche con la finestra chiusa."

## 5. Provider
Interfaccia in `BaseLLMProvider`: `supports_batch` (default False), `submit_batch(requests) -> batch_id`,
`poll_batch(batch_id) -> (status, results|None)`, `cancel_batch` facoltativo.
- **OpenRouter** (`providers/openrouter.py`): `POST /api/v1/batches` con `endpoint="/v1/chat/completions"`,
  `model`, `completion_window="24h"` PRIMA di `requests` nel JSON (altrimenti 400), `requests=[{custom_id: key,
  body: <stesso corpo della chiamata sincrona senza stream>}]`. Stato: `GET /api/v1/batches/{id}`
  (validating/in_progress/finalizing/completed/failed/expired/cancelled); risultati inline in `results`, NON in
  ordine: abbinare per `custom_id`; ogni risultato ha `response` (stessa forma della sincrona → riusare il
  parser esistente) o `error`. Dopo aver salvato: `DELETE /api/v1/batches/{id}`. Gestire 402/413/429.
- **Google** (`providers/google.py`, Gemini API): batch con richieste inline (`batchGenerateContent`), stato del
  job e risultati inline; se le richieste superano il limite inline, dividere in più lotti. Verificare i nomi
  esatti dei campi nella documentazione dell'SDK/REST già usata dal provider; se il provider attuale usa
  l'endpoint compatibile OpenAI, implementare con lo stesso client HTTP. Se non è possibile in modo sicuro,
  lasciare `supports_batch=False` per Google e scriverlo nel commit.
- DeepSeek, compatibili OpenAI generici: `supports_batch=False`.

## 6. Impostazioni → Modelli (nessun interruttore)
Decisione: il batch NON è un'impostazione. È una scelta di modello: nell'elenco dei modelli di ogni fase non
interattiva compaiono anche le varianti batch, es. "Gemini 4 Neon · batch (−50%, risposte entro 24 h)"
(OpenRouter: modelli con variante `:batch` dal loro elenco modelli; Google: stesso modello con `batch: true`).
Scegliere una variante batch imposta `batch: true` sulla rotta. Le altre fasi restano sincrone e non cambiano.
Sotto la scelta, una riga: "Le risposte arrivano più tardi: RT deve poter lavorare in background (Impostazioni →
Generali → Chiudendo con la X)". Le fasi interattive (chat, prove) non mostrano varianti batch.

## Test (tutti con provider finti, nessuna rete)
Chiave stabile; cache done/error/pending; `run_collecting` raccoglie e solleva una volta; worker: DeferredPhase →
waiting_for_provider + submit, poll completo → resume → la fase rilegge dalla cache e il job finisce con lo stesso
risultato della modalità sincrona; lotto expired → fallback sincrono; cancel; immagini → sincrono; chat mai batch;
parser OpenRouter con risultati fuori ordine ed errori per singola richiesta; serializzazione con i campi prima di
`requests`. Fine: pytest dei file toccati + vitest/tsc dei componenti toccati. Righe nel CHANGELOG.
