# Task per Antigravity — consolidamento ingest/outline/review/recall

I file numerati in questa cartella sono già il piano di implementazione completo, pronto per
essere eseguito: NON produrre un tuo piano di implementazione separato prima di iniziare.
Leggi ogni file di task e implementa direttamente quanto descritto.

## Stato

01-34 completati, revisionati e pushati (dettagli nei rispettivi commit `git log`). Task 35
(fix deadlock trascrizione macparakeet-cli — `--output-dir` mancante causava un deadlock sul
buffer del pipe per lezioni lunghe), 36 (bugfix puntuali wizard `rt config`), 37 (inserimento
chiavi API in batch), 38 (primo redesign a blocchi del wizard, risultato incompleto rispetto
alla spec — corretto dal Task 43), 39 (Telegram discovery con retry, `rt config --topics`):
completati, verificati manualmente riga per riga (non fidandosi del solo resoconto testuale di
Antigravity, che in almeno due giri ha riportato percorsi di file e nomi di variabili
inventati), 643/643 test.

Task 40 (rimozione completa di `review_asr`, mai usato in pratica; rename interno completo
`review_science`→`review`, nessuna retrocompatibilità richiesta), 41 (rilevamento ASR
statistico deterministico su confidenza per-parola, nuova classe issue `ERR_ASR_ST`, fix di un
bug reale in `ledger.py` che avrebbe scartato silenziosamente le correzioni utente su questo
tipo di issue), 42 (flag `--asr-llm` per raffinare i candidati statistici via LLM), 43 (card
carousel letterale per `rt config` con `rich.Live`+`read_single_key`, sostituisce il Task 38):
completati e verificati, 636/636 test.

Un'indagine approfondita su un 429 rate-limit riportato durante test reali (round-robin su 12
chiavi Google, 4 account) ha escluso bug di instradamento lato RT (verificato sui log di
telemetria reali) e un limite di quota per-progetto documentato (verificato con un probe
empirico e col dashboard Google AI Studio, quota ampiamente disponibile al momento del
fallimento) — conclusione: quasi certamente un meccanismo anti-abuso non documentato di Google
che aggrega il traffico tra chiavi/account correlati, non risolvibile aggiungendo altre chiavi.

Task 44 (`os.environ` non aggiornato in `_update_env_file`, chiavi non riconosciute nella
stessa sessione di `rt config`), 45 (fix Task 35 mai applicato a `recall_stt.py`, risposte
vocali in active recall rotte), 46 (bug di rendering nel carosello `rt config`, card che si
accumulano), 47 (stesso bug in `outline_review.py`, migrato a `rich.Live` + frecce
sinistra/destra), 48 (notifica Telegram build completata mostra data/argomenti/materia invece
del percorso file), 49 (`/list` distingue lezione mancante da lezione fuori `lessons_root`), 50
(bottoni recall con testo modificato in place e audio in risposta al messaggio originale), 51
(notifica "sto generando le domande" prima del primo batch di recall), 52 (`llm_debug.log`
registra `credential_ref`/`route_id`/`failure_class` per chiamata), 53 (fallback per-fase
configurabili da `rt config`, mitigazione pratica al 429 sopra): completati e verificati,
650/650 test.

Task 54 (`rt -v`/`rt -u`, versione e aggiornamento senza che l'utente veda mai un comando git):
completato e verificato, 670/670 test. Corretto in revisione un piccolo bug reale: il messaggio
di `rt -v` confondeva "nessun tag ancora pubblicato sul remote" con "errore di connessione"
(stesso valore `None` per entrambi i casi) — ora distinti.

Terzo giro di test reale (installazione da zero → run → recall su MacBook Air, indagine via
SSH). Diversi fix applicati DIRETTAMENTE in chat (non task Antigravity, già committati in
`9df3d59`), il più grave dei quali: `rt config --topics` scriveva `{chat_id,
message_thread_id}` invece di un int semplice in `telegram.topics`, violando lo schema
Pydantic e mandando in crash QUALUNQUE comando `rt` — corretto (ora salva sempre un int, con
avviso se il link appartiene a un gruppo diverso da quello già configurato: RT supporta un solo
gruppo Telegram per bot). Altri fix diretti: rimossi topic/valori d'esempio da
`config.example/general.yaml` trattati come reali dopo il bootstrap (stesso pattern del bug
Task 36 sul bot token, ma per i topic); nome di default di un nuovo profilo modello ora sempre
`provider_casa_modello` con trattini/punti preservati; riepilogo finale di `install.sh`; hint
di `rt run` senza provider configurato; feedback ephemeral sul bottone "Non lo so"; prompt
`lessons_root` ripulito; riferimento all'unità nelle domande quiz (Poll) quando derivano da
una sola unità.

Discussi con l'utente i tre punti lasciati in sospeso dal giro precedente: TUTTI E TRE decisi.
(1) Duplicazione delle card + Option+Backspace + tema: invece di continuare a rincorrere bug
puntuali sull'accoppiata `rich.Live`+parsing ANSI manuale (`rt/core/keyboard.py`), si migrano le
4 schermate interattive da terminale a Textual (stessa softwarehouse di Rich, ridisegna l'intero
schermo per frame invece di tracciare righe da cancellare, gestisce l'input da tastiera con un
proprio sistema di keybinding, ha temi chiaro/scuro nativi) — risolve strutturalmente tutti e tre
i problemi invece di tre fix scollegati. Task 60 (tema, sul motore vecchio) RIMOSSO, superato.
Nessun task per Option+Backspace: superato dalla gestione tasti nativa di Textual, non serve più
un parsing ANSI a mano. Aggiunti i Task 64-68 (migrazione in 5 passi: pilota su
`outline_review.py`, poi `issue_review.py`, poi il carosello ruoli-fase di `configure.py`, poi la
pulizia "stale" di `recall_session.py`, infine rimozione di `keyboard.py`) — Antigravity si ferma
dopo il Task 64 (pilota) in attesa di conferma prima di proseguire sugli altri 3 file, per
contenere il rischio di un cambio di motore su tutta la UI da terminale. (2) Fallback +
round-robin: confermato il comportamento richiesto (esaurire il pool round-robin prima di
scattare il fallback, tornare subito al round-robin dopo un uso, cooldown configurabile — default
30s — solo al secondo fallback consecutivo) → Task 63, vera macchina a stati in
`rt/llm/router.py`.

## Task da fare, in ordine

1. **63** — Il fallback deve esaurire il pool round-robin prima di scattare (oggi un SINGOLO 429
   su round-robin salta subito a `fallback.rate_limit`), tornare al round-robin dopo un uso, e
   applicare un cooldown (default 30s, configurabile) solo al secondo fallback consecutivo.
   Richiede stato persistente per job in `RoutingEngine` (`rt/llm/router.py`).
2. **55** — Pricing OpenRouter sempre "pending": nessun codice interroga il campo `pricing`
   dell'endpoint `/models` di OpenRouter (a differenza di Google, che matcha una tabella
   statica). Rileva il prezzo reale in fase di configurazione e mostralo invece di chiedere
   genericamente "vuoi configurare un pricing custom?".
3. **56** (CRITICO) — Creare un secondo pool round-robin "separato" per lo stesso provider può
   silenziosamente sovrascrivere le chiavi di un profilo già esistente (stessi identificatori
   `google_1`/`google_2`/... rigenerati da zero). Rischio reale di corruzione configurazione.
4. **57** — Chiarire che solo il Primario è obbligatorio nel carosello (i 5 fallback sono
   sempre opzionali) + mostrare il numero di chiavi round-robin nel riepilogo finale.
5. **58** — Il messaggio "sto generando le domande" (Task 51) deve auto-cancellarsi quando
   arriva la prima domanda, invece di restare a floodare la chat.
6. **59** — `/recall <N>` in risposta diretta al messaggio di `/list` deve usare N come
   posizione nella lista mostrata, non come ricerca testuale per data/titolo.
7. **61** — Riorganizza `rt -h`: italiano, "Comandi principali" (config/run/review/recall/
   status/telegram-daemon) separati dalle sottofasi della pipeline e dai comandi diagnostici,
   niente ridondanza tra `usage:` e l'elenco sotto, aggiunta sezione Esempi.
8. **62** — Bottone 📖 (unità testuale in active recall): piega il testo nello stesso messaggio
   del commento (come già fa il bottone 🗣 trascritto, stesso pattern da riusare) invece di un
   messaggio satellite — il bottone 🔊 audio resta invariato (vincolo reale dell'API Telegram:
   non si può aggiungere un allegato audio a un messaggio di solo testo via modifica).
9. **64** (PILOTA Textual) — Migra `outline_review.py` da `rich.Live` a Textual. Fermarsi dopo
   questo task e attendere conferma in chat prima di proseguire.
10. **65** — Migra `issue_review.py` a Textual (solo dopo conferma sul Task 64) — la più
    complessa delle 4: audio in background + editor esterno via `App.suspend()`.
11. **66** — Migra il carosello ruoli-fase di `configure.py` a Textual (solo dopo Task 64/65) —
    il file più grande, va per ultimo tra le 4 schermate.
12. **67** — Migra la pulizia "stale" di `recall_session.py` a Textual (solo dopo Task 64/65,
    indipendente da 66).
13. **68** — Rimuovi `rt/core/keyboard.py`, orfano dopo che 64-67 sono TUTTI completati.

Tutti indipendenti tra loro salvo dove segnalato diversamente nei singoli file (in particolare la
sequenza 64→65/66/67→68 della migrazione Textual, con pausa di conferma dopo il 64).

## In sospeso — decisioni da prendere con l'utente prima di trasformarle in task

Nessuna al momento: i tre punti del giro precedente sono stati tutti decisi (vedi "Stato" sopra e
i Task 63-68).

## Dopo ogni task numerato (obbligatorio, non solo alla fine)

1. Implementa il task.
2. Esegui `python3 -m pytest tests/ -q` **una sola volta, dopo** aver fatto le modifiche — non
   eseguire una suite di baseline prima di iniziare il task, è tempo sprecato: lo stato dei test
   prima delle tue modifiche è già noto (la suite passa per intero alla fine di ogni task
   precedente).
3. Se i test falliscono: diagnostica e correggi tu stesso il problema, ripeti finché la suite
   passa — non fermarti al primo fallimento. Fermati a chiedere aiuto solo se dopo un paio di
   tentativi reali resti bloccato senza aver capito la causa.
4. Una volta che i test passano per QUESTO task: fai un `git commit` separato (messaggio tipo
   "Task N: <breve descrizione>"). **Non fare `git push`** in nessun caso — il push avviene solo
   alla fine, dopo revisione di tutti i task. Poi passa direttamente al task successivo, senza
   fermarti ad aspettare conferma.

Un commit per task completato e verificato permette di isolare subito quale task ha introdotto
un problema, invece di analizzare un diff enorme a fine lavoro.

Quando tutti i task sono completati (o se resti bloccato su uno), segnalalo in chat con un
riepilogo breve per task: file toccati, esito test, e — importante — cosa non hai fatto o non
sei sicuro sia corretto.

## Note permanenti

**Verifica sempre di lavorare nella directory di progetto corretta** prima di trarre
conclusioni da cosa trovi in `config/` (mai tracciata in git, configurazione locale reale
dell'utente) — un'indagine passata ha portato a conclusioni sbagliate per aver ispezionato la
copia di progetto sbagliata.

**Bug di portabilità ricorrente**: quando aggiungi o modifichi una firma di funzione con
un'annotazione da `typing` (`Optional[...]`, `List[...]`, ecc.), verifica sempre che sia
importata esplicitamente in cima al file. Funziona per puro caso in questo ambiente (Python
3.14 valuta le annotazioni in modo differito, PEP 649) ma darebbe `NameError` all'import su
Python <3.14 — "i test passano" non è una prova sufficiente, girano nello stesso ambiente che
maschera il problema.

Riferimento: piano approvato per i task 01-12 in
`/Users/attilioturco/.claude/plans/ok-adesso-vorrei-fare-reactive-spark.md`; piano approvato
per i task 13-17 in
`/Users/attilioturco/.claude/plans/discutiamo-prima-il-punto-flickering-chipmunk.md`. I task
18 in poi sono autosufficienti (contesto e decisioni dentro ciascun file di task).
