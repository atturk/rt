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

## Task da fare, in ordine

1. **54** — `rt -v` (versione corrente + confronto con l'ultima disponibile su GitHub) e
   `rt -u` (aggiornamento via git, senza che l'utente veda mai un comando git). Vedi il file
   task per i dettagli UX e di implementazione.

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
