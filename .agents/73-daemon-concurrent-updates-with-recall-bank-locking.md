# Task 73 — Abilita `concurrent_updates` nel demone Telegram, con locking del recall bank

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

L'utente ha segnalato che il terminale che ospita `rt telegram-daemon` sembra "freezare"
completamente mentre genera domande di recall o valuta una risposta: durante quella finestra,
qualunque altro comando/bottone Telegram in arrivo non viene processato fino al termine.

**Causa reale (non un thread bloccante)**: `rt/telegram/daemon.py`, riga ~1066,
`Application.builder().token(cfg.bot_token).build()` NON imposta `.concurrent_updates(True)`.
Per default, python-telegram-bot processa gli update **uno alla volta**: anche se il lavoro pesante
è già correttamente delegato a `run_in_executor` (verificato: tutte le chiamate a
`start_recall_via_telegram`/`handle_recall_answer`/generazione domande lo fanno già), l'intero
handler resta "in corso" finché quel future non si risolve, e PTB non dispatcha il prossimo update
nel frattempo. Non è quindi un problema di codice bloccante, ma di configurazione del dispatcher.

**Rischio da mitigare PRIMA di abilitare la concorrenza**: `rt/pipeline/recall.py::
load_recall_bank`/`save_recall_bank` (righe 38/50) — il file `<lesson_dir>/_state/
recall_questions.json`/banco risposte — NON ha alcun locking, a differenza di `rt/telegram/
registry.py` e `rt/telegram/session.py` che già proteggono le proprie letture/scritture con un
lock a file (`_acquire_lock`/`_release_lock`, righe 24-48 di `registry.py` — meccanismo a file
`O_CREAT|O_EXCL`, con rilevamento di lock "stale" oltre 30s, nessuna dipendenza esterna). Se due
update Telegram per la STESSA lezione vengono processati in parallelo (es. l'utente preme un
bottone mentre una generazione è ancora in corso), un ciclo lettura→modifica→scrittura non
protetto rischia un "lost update" (la scrittura più recente sovrascrive quella dell'altra,
perdendo dati). Ci sono almeno 10 punti che chiamano `save_recall_bank` dopo un
`load_recall_bank`: `rt/pipeline/recall.py` (righe 147, 186, 202, 220, 461, 558) e
`rt/pipeline/recall_session.py` (righe 623, 643, 679, 686, questi ultimi nella schermata Textual
di pulizia "stale", terminale non Telegram — proteggili comunque per coerenza, dato che un
processo terminale e uno Telegram potrebbero operare sulla stessa lezione in momenti diversi ma
sovrapposti).

## Modifica

### 1. Abilita la concorrenza nel demone

In `rt/telegram/daemon.py`, cambia `Application.builder().token(cfg.bot_token).build()` in
`Application.builder().token(cfg.bot_token).concurrent_updates(True).build()`.

### 2. Locking del recall bank (PRIMA o insieme al punto 1, non dopo)

- Aggiungi un lock a file per il recall bank, scoped alla singola lezione (non un lock globale
  condiviso tra lezioni diverse — ogni lezione ha il proprio `_state/`, il file di lock va lì
  dentro, es. `<lesson_dir>/_state/.recall_bank.lock`). Puoi riusare la STESSA logica di
  `_acquire_lock`/`_release_lock` di `registry.py` (stesso meccanismo `O_CREAT|O_EXCL` + rilevamento
  stale-lock) — se ha senso, estraila in un piccolo modulo condiviso (es. `rt/core/filelock.py`)
  invece di duplicare la funzione in due punti diversi del codice; valuta tu se il refactor vale
  la pena o se è più sicuro semplicemente copiare la stessa logica adattata al path del lock.
- Il modo più robusto per evitare che i ~10 call site debbano ricordarsi di acquisire/rilasciare
  il lock manualmente (rischio di dimenticanza futura): valuta di centralizzare il pattern in una
  funzione tipo `update_recall_bank(lesson_dir, mutator_fn) -> RecallBank` in `rt/pipeline/
  recall.py`, che internamente acquisisce il lock, fa `load_recall_bank`, applica `mutator_fn`
  (una funzione che riceve il `RecallBank` e lo modifica in place, o lo ritorna modificato), fa
  `save_recall_bank`, rilascia il lock — poi migra i call site esistenti a usarla invece del
  pattern attuale "load, modifica manuale, save" ripetuto ovunque. Se risulta troppo invasivo
  cambiare tutti i call site in un colpo solo, va bene anche wrappare ciascuno dei ~10 punti con
  un context manager esplicito (`with recall_bank_lock(lesson_dir): ...`) mantenendo la struttura
  attuale — scegli l'approccio che minimizza il rischio di introdurre regressioni, spiega la scelta
  nel riepilogo finale.
- Il lock deve coprire l'INTERO ciclo load→modifica→save, non solo la scrittura finale (altrimenti
  non previene il problema: due processi potrebbero comunque leggere lo stesso stato stale prima
  che uno dei due scriva).

## Test

- Test che verifica che `Application.builder()` nel demone abbia `concurrent_updates(True)`
  impostato (ispeziona la configurazione dell'oggetto costruito, o mocka `ApplicationBuilder` e
  verifica che il metodo sia stato chiamato con `True`).
- Test che simula due "aggiornamenti" concorrenti sullo stesso recall bank (es. due thread/processi
  che tentano un load-modifica-save in sovrapposizione, usando `threading` per orchestrare la
  sovrapposizione in un test deterministico) e verifica che NESSUNA modifica vada persa — entrambe
  le modifiche devono risultare presenti nel file finale, non solo l'ultima scrittura vince.
- Test che verifica che un lock "stale" (vecchio di oltre 30s, simulando un crash) venga rilevato e
  rimosso invece di bloccare per sempre le operazioni successive (stesso comportamento già testato
  per `registry.py`, se esiste un test analogo lì da cui prendere ispirazione).
- Esegui la suite esistente di `tests/test_recall_session.py`/test relativi a `recall.py` e
  verifica che il locking aggiunto non introduca deadlock o rallentamenti anomali nei test
  esistenti (un singolo processo/thread che acquisisce e rilascia il proprio lock ripetutamente
  deve continuare a funzionare senza intoppi).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non introdurre nuove dipendenze esterne (niente `filelock`/`portalocker` da pip) — il meccanismo a
file `O_CREAT|O_EXCL` già usato in `registry.py` è sufficiente e coerente con lo stile del
progetto (commento esplicito in `registry.py` riga 6: "nuova dipendenza (niente 'filelock')").

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se possibile, test manuale: avvia il demone, avvia una generazione di domande lunga (più
   unità), e mentre è in corso prova a interagire con un ALTRO comando/bottone nella stessa chat —
   deve rispondere subito, non restare in coda fino al termine della generazione.
