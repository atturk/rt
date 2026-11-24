# Piano A: scaletta automatica, notifiche Telegram a scelta, verifica in parallelo, due correzioni batch

Branch: `agy/4.3.9-notifiche` (parte da `claude/rt-4.3.9-beta`). Solo codice e test unitari, niente verifiche
nell'app. Prima di tutto `git pull` del branch. Un commit per punto, push sul branch.
NON toccare l'aspetto generale delle Impostazioni: lo rifà il piano B subito dopo. Qui aggiungi solo i
controlli nuovi con i componenti che ci sono (`Section`, `Field`, `SettingsSelect`, `Checkbox` di
`frontend/src/components/settings/common.tsx`).

## 1. Scaletta: aspetta sempre / dopo N secondi / procedi sempre (default: procedi sempre)
Oggi c'è solo `ui.outline_auto_approval_seconds` (default 10, 0 = aspetta sempre), vedi
`rt/core/config.py` ~325, `rt/services/outline_service.py` `start_outline_timer`,
`rt/services/pipeline_service.py` ~171, `rt/services/settings_service.py` ~416/520,
`frontend/src/components/settings/preferences.tsx` (`OutlineSettingsSection`, «Approva da sola dopo»).
- Config: nuovo `ui.outline_mode: Literal["auto", "timer", "manual"] = "auto"`; `outline_auto_approval_seconds`
  resta per la modalità `timer` (default 10, min 1). Migrazione in lettura: se nel file c'è
  `outline_auto_approval_seconds: 0` e manca `outline_mode` → `manual`; se c'è un valore > 0 senza
  `outline_mode` → `auto` (il default nuovo vale anche per chi aveva 10, scelta di Attilio).
- `auto`: in `pipeline_service`, quando la scaletta è pronta, la si approva subito
  (`approve_outline(lesson_dir, actor="server", channel="server")`) senza fermare il job su
  `outline_approval` e senza timer; la lavorazione prosegue nello stesso job.
- `timer`: comportamento di oggi con i secondi impostati.
- `manual`: aspetta sempre l'utente (come oggi con 0).
- API impostazioni (`settings_service` + schema): `modalita_scaletta` ("auto"|"timer"|"manual") e
  `secondi_approvazione`. Rigenera `docs/openapi.json` e `frontend/src/api/schema.d.ts`.
- UI (preferences.tsx, sezione Scaletta): un `SettingsSelect` «Approvazione della scaletta» con
  «Procedi sempre in automatico» / «Aspetta qualche secondo, poi procedi» / «Aspetta sempre me»;
  il campo dei secondi compare solo con la seconda scelta.
- `rt/telegram/notify.py` `_outline_auto_approved()` → true se la modalità è `auto` o `timer`.
- Test: migrazione (0 → manual, 10 → auto, campo presente → invariato); in `auto` il job non entra in
  attesa e la scaletta risulta approvata; in `manual` sì; nessuna notifica `outline_approval` in auto/timer.

## 2. Notifiche Telegram a scelta
File: `rt/telegram/notify.py`, `rt/telegram/notify_log.py`, `rt/telegram/client.py`,
`frontend/src/components/settings/telegram.tsx`, router API di Telegram (cerca `/telegram/notifications`).
- Eventi (chiavi stabili): `lezione_pronta` (on), `verifica_pronta` (on, nuovo), `errore` (on),
  `scaletta_da_approvare` (on, ma parte solo in modalità `manual`), `issue_da_decidere` (on).
  Se trovi altri punti in cui una notifica ha senso (es. job batch rimasto in attesa del provider oltre
  un'ora), elencali nel commit senza attivarli.
- Config: `telegram.notify: Dict[str, bool]` con i default sopra; `send_notification(kind, …)` non invia se
  l'evento è spento. Mappa i `kind` esistenti (`decisione` va diviso nei due eventi).
- `verifica_pronta`: a fine job di verifica manuale (`review_units_job` e `review_part_job` in
  `rt/services/api_jobs.py`) e quando finisce la fase di verifica della pipeline, UNA notifica per job:
  «🔎 Verifica completata» + righe della lezione + «N issue da decidere in RT» (o «Nessuna issue»).
  Mai una per unità.
- Niente doppioni: se nello stesso job sono già partite `issue_da_decidere` e `verifica_pronta`, manda solo
  `verifica_pronta` (che riporta già il numero).
- Pulizia dello storico (CORRETTO da Attilio): NON si cancella nulla su Telegram e non serve salvare i
  message_id. Serve solo svuotare la sezione «Ultime notifiche inviate» di RT: nuovo endpoint
  `DELETE /api/v1/telegram/notifications` che svuota il file di `notify_log` (sotto il suo lock).
- UI telegram.tsx: sotto la configurazione, gruppo «Ricevi una notifica quando…» con un interruttore per
  evento (testo breve + tooltip con un esempio del messaggio). Accanto al titolo «Ultime notifiche inviate»
  un pulsante icona minimale (ghost, cestino, `aria-label="Svuota l'elenco"`, tooltip «Svuota l'elenco: i
  messaggi su Telegram restano»), senza finestra di conferma; dopo, l'elenco mostra «Nessuna notifica».
- Test pytest: evento spento → nessun invio; `verifica_pronta` una sola volta per job; DELETE svuota il log; il token
  non compare negli errori. Vitest per i toggle e
  il cestino.

## 3. Verifica delle unità in parallelo
La verifica della pipeline (`rt/pipeline/review.py` `_run_review`) usa già `_parallel_units` con
`review.parallel_units` (default 4). Il job della verifica avviata a mano dal pannello
(`review_units_job` in `rt/services/api_jobs.py` ~140-170, e `review_part_job`) invece verifica le unità
una alla volta in un `for`.
- Usa lo stesso schema di `_parallel_units` (o un `ThreadPoolExecutor(max_workers=cfg.review.parallel_units)`)
  per `run_review_unit` / `run_review_part`: eventi `ReviewUnitStarted` con `running_units` = tutte quelle in
  corso, `ReviewUnitDone` all'arrivo di ciascuna, `ctx.check_cancelled()` prima di avviarne una nuova,
  gestione di `DeferredCall/DeferredPhase` (batch) uguale a oggi. I risultati restano nell'ordine delle unità.
- Attenzione alle scritture concorrenti su file della lezione (draft, ledger delle issue): controlla che
  `run_review_unit` scriva sotto lock; se no, raccogli i risultati nei thread e scrivi nel thread principale.
- Test: con 6 unità e parallel 3 le chiamate si sovrappongono (finto che dorme) e il ledger finale ha le
  issue di tutte; cancellazione a metà ferma le nuove.

## 4. Due correzioni della modalità batch
- `rt/llm/pricing.py` `calculate_cost`: somma `cost_out` + `cost_reason`, ma per OpenAI/OpenRouter
  (`completion_tokens`) i token di ragionamento sono GIÀ dentro `output_tokens` → costo gonfiato. Controlla in
  `rt/llm/client.py` come arrivano `out_t`/`reas_t` per ogni provider (OpenAI-compatibile, OpenRouter,
  Gemini nativo, Anthropic) e correggi in modo che il ragionamento si conti una sola volta (per i provider in
  cui è incluso: `cost_reason` solo sulla differenza di prezzo se `reasoning_per_million` è diverso, altrimenti
  zero). Test per provider.
- Batch e cambio modello: se l'utente cambia il modello di una fase mentre un job di quella fase aspetta un
  batch del provider, alla ripresa RT deve usare il batch già inviato (provider/modello salvati nella
  chiamata differita), non il modello nuovo, e non perdere il risultato. Cerca in `rt/llm/deferred.py` e nel
  codice di ripresa dove si sceglie il client; correggi e aggiungi un test (modello cambiato tra invio e
  ripresa → il risultato del batch viene usato).

## 5. Bug di Telegram e del worker trovati nei test sulla b8
- CRITICO: «Lezione pronta» non parte mai. `rt/services/pipeline_service.py` `_run` riceve i notifier ma non
  chiama più `notify_build_completed` (tolto per errore in 0eef3eb1). Rimettilo a fine lavorazione riuscita,
  rispettando il toggle `lezione_pronta`. Test: build riuscita → una notifica «Lezione pronta».
- Il worker tiene la chat vecchia dopo un cambio: `load_env_file` con `override=False` non aggiorna
  `TELEGRAM_CHAT_ID`/token già in ambiente. Rileggi le impostazioni Telegram a ogni invio (o ricarica con
  override per quelle chiavi). Test: cambio chat id → l'invio successivo usa quello nuovo.
- `rt/worker.py` `NOTIFY_FAILED_TYPES`: aggiungi `ingest_sources`, `ingest_notes`, `review_unit`, `review_part`.
- Messaggio di errore: includi sempre lezione e materia anche se il job fallisce nella preparazione (prendili
  dal job/lesson id), e niente prefisso tecnico tipo «ValueError:»: frase breve leggibile, dettaglio tecnico
  solo nei log.
- `rt/telegram/client.py`: il retry su 429 dorme `retry_after` senza limite → massimo 30 s e un solo
  tentativo in più, poi rinuncia e segna «non inviata».
- `openrouter_batch_models()` è vuota dopo il riavvio dell'API, quindi il menu dei modelli non mostra le voci
  `:batch`. Popola l'elenco all'avvio (o alla prima richiesta, con cache) e aggiungi un test.
- Salvare una preferenza riscrive `general.yaml` cambiando altre chiavi (es. il modello `jev` diventa
  `classifier`). Salva solo la chiave modificata, senza normalizzare il resto. Test: salvo un'opzione → le
  altre righe del file restano uguali.

## Chiusura
- `CHANGELOG.md`: crea `## 4.3.9b9 — da pubblicare` sopra la b8 (stesso stile). Novità: scaletta che procede
  da sola (scelta in Impostazioni), notifiche Telegram a scelta, storico delle notifiche svuotabile, notifica a verifica
  completata, verifica manuale delle unità in parallelo. Correzioni: costo stimato con i modelli che
  ragionano, risultato batch conservato se cambi modello, notifica «Lezione pronta» di nuovo inviata, chat
  Telegram aggiornata subito, modelli batch nel menu anche dopo il riavvio. Non cambiare `VERSION`.
- Esegui: pytest sui test toccati, `npx vitest run`, `npx oxlint --deny-warnings`, `npm run build`,
  `npm run -s check:bundle` in `frontend/` (budget vicino al limite: niente nuove dipendenze).
- Push su `agy/4.3.9-notifiche`.
