# Task per Antigravity — consolidamento ingest/outline/review/recall

I file numerati in questa cartella sono già il piano di implementazione completo, pronto per
essere eseguito: NON produrre un tuo piano di implementazione separato prima di iniziare.
Leggi ogni file di task e implementa direttamente quanto descritto.

**Stato**: 01-22 sono già stati implementati e revisionati (con diversi fix applicati
direttamente in revisione: due bug reali di risoluzione credenziali/token già configurati che
impedivano il pre-riempimento dei prompt su una riesecuzione di `rt config`, un timeout della
discovery Telegram troppo corto rispetto alla specifica, rimozione di alias morti lasciati dalla
migrazione MacWhisper→macparakeet-cli) e pushati — non rifarli, non toccare quel codice se non
indicato esplicitamente da un task attivo. 01-29 sono completati, revisionati e pushati (in
revisione del Task 29 è stata trovata e rimossa una modifica non richiesta a
`find_compatible_python`/`requirements.txt` basata su una premessa rivelatasi falsa in un test
empirico diretto — verifica sempre empiricamente prima di escludere una versione Python). Il
lavoro corrente da eseguire è **30**: sostituisce il prompt testuale `read -rp [S/n]`
(introdotto nel Task 29) con un menu `questionary` in stile `rt config`, con un piccolo bootstrap
anticipato del venv (solo `questionary`, per non perdere il parallelismo del download introdotto
nel Task 28) e fallback al prompt testuale se il bootstrap fallisce. Task 31 completato (a fine
installazione, se il terminale è interattivo, sostituisce la shell corrente con una fresca via
`exec "$SHELL" -l`, riepilogo finale con `rt` invece di `./bin/rt`). `install.sh` ora funziona
end-to-end su un MacBook Air reale (verificato) — inclusi due fix diretti trovati in revisione:
`bin/rt` confrontava il realpath dell'eseguibile invece di `sys.prefix` per capire se rieseguirsi
nel venv (mai scattava quando l'interprete che crea il venv è lo stesso risolto da `python3`
bare, caso comune), e il menu `questionary` della scelta STT non veniva mai disegnato perché il
call site lo invocava dentro `$(...)`, trasformando in una pipe lo stdout ereditato dal
sottoprocesso python. Il lavoro corrente da eseguire è **32-34**, tutti su `rt/pipeline/configure.py`
a valle di un primo vero test del wizard sull'Air: **32** rimuove il bootstrap "generale"
obbligatorio (si va dritti al loop per-fase), raggruppa i 5 job di recall e i 2 di immagini in
una domanda ciascuno, aggiunge "lascia vuoto per ora", sistema due messaggi fuorvianti — **33**
sostituisce la lista modelli con `questionary.autocomplete` (ricerca testuale dinamica) e
aggiunge conferma+possibilità di tornare indietro sulla selezione — **34** aggiunge
`rt config --models` (gestione/modifica profili salvati) e `rt config --telegram` (salta dritto
alla sezione Telegram).

## Ordine di esecuzione

32 va fatto per primo (ridisegna la struttura su cui si appoggiano 33 e 34). 33 e 34 sono
indipendenti tra loro, ordine libero dopo il 32.

## Dopo OGNI task numerato (obbligatorio, non solo alla fine)

1. Esegui `python3 -m pytest tests/ -q`.
2. Se i test falliscono: diagnostica e correggi tu stesso il problema, e ripeti finché la
   suite passa — non fermarti solo perché un test fallisce al primo giro. Fermati a chiedere
   aiuto solo se dopo un paio di tentativi reali resti bloccato senza aver capito la causa.
3. Una volta che i test passano per QUESTO task: fai un `git commit` separato per QUEL task
   (messaggio tipo "Task 0N: <breve descrizione>"). **Non fare `git push`** in nessun caso —
   il push avverrà solo alla fine, dopo la revisione di tutti i task. Poi passa direttamente
   al task numerato successivo, senza fermarti a chiedere conferma.

Un commit per task completato e verificato permette di isolare subito quale task ha
introdotto un problema, invece di dover analizzare un diff enorme e indistinguibile a fine
lavoro — ma non serve fermarsi ad aspettare conferma tra un task e l'altro.

Riferimento: piano approvato per i task 01-12 in
`/Users/attilioturco/.claude/plans/ok-adesso-vorrei-fare-reactive-spark.md`; piano approvato
per i task 13-17 (feature "add-images") in
`/Users/attilioturco/.claude/plans/discutiamo-prima-il-punto-flickering-chipmunk.md` (i task
18-22 non hanno un piano separato, sono autosufficienti — decisioni prese direttamente in chat:
RT resta un checkout git auto-contenuto niente packaging pip/pipx per il 18; sostituzione
MacWhisper→macparakeet-cli e design del wizard `rt config` con discovery live Telegram invece
del link-paste, per motivazioni spiegate nei task 19-22 stessi).

Quando tutti i task sono completati (o se ti sei fermato bloccato su un task), segnalalo in
chat con un riepilogo breve per task: file toccati, output dei test, e — importante — cosa
non hai fatto o non sei sicuro sia corretto. I commit separati e il diff completo verranno
revisionati e poi pushati.

## Nota su un bug di portabilità ricorrente nei giri precedenti

Più task nei round precedenti hanno usato `Optional[...]`/`List[...]` (e simili da `typing`)
come annotazione di tipo senza il corrispondente `from typing import ...` in cima al file.
Funziona per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo differito
di default, PEP 649) ma darebbe `NameError` all'import su Python <3.14. Quando aggiungi o
modifichi una firma di funzione con un'annotazione da `typing`, verifica sempre che sia
importata esplicitamente in quel file — non dare per scontato che "i test passano" sia una
prova sufficiente, dato che i test girano nello stesso ambiente Python 3.14 che maschera il
problema.
