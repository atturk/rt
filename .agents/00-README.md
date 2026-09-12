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
obbligatorio, raggruppa i 5 job di recall e i 2 di immagini in una domanda ciascuno, aggiunge
"lascia vuoto per ora", i due messaggi fuorvianti sono stati sistemati. Task 33: lista modelli
ora con `questionary.autocomplete` (ricerca testuale dinamica) + conferma con possibilità di
tornare indietro. Task 34: `rt config --models` (gestione/modifica profili salvati: rinomina,
riconfigura, API key, pricing, eliminazione) e `rt config --telegram` (salta dritto alla sezione
Telegram) — entrambi verificati anche con test funzionali diretti (rename+delete di un profilo
reale, mutua esclusività dei due flag). **Non ci sono task attivi al momento** — attenzione: il
resoconto testuale di Antigravity per questo giro conteneva nomi di job di recall/immagini
completamente inventati (es. "recall_topics", "recall_persons") che NON esistono nel codice
reale (verificato: il diff usa correttamente `recall_quiz`/`recall_mirata`/ecc. e
`image_description`/`image_unit_judge`) — promemoria a non fidarsi mai del testo del
walkthrough, nemmeno per dettagli apparentemente innocui come nomi di variabili citati nel
resoconto.

## Ordine di esecuzione

1. **Task 35** (indipendente, priorità massima — bug bloccante).
2. **Task 36 → Task 37 → Task 38** in quest'ordine (stesso file, `rt/pipeline/configure.py`).
3. **Task 39** (indipendente, può essere eseguito in qualunque momento rispetto agli altri).

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

## Aggiornamento — primo giro di test reale end-to-end (installazione → run) su MacBook Air

L'utente ha eseguito il primo giro di test reale completo (installazione da zero, `rt config`,
`rt run` su una lezione audio reale di 86 minuti) e riportato una serie di bug e richieste UX,
ora tradotti nei Task 35-39 (dettagli completi in ciascun file). Un fix testuale minore
(riepilogo "prossimi passi" a fine `install.sh`) è stato applicato direttamente in chat, non è
un task Antigravity.

**Task 35 (CRITICO, priorità massima)**: `rt run`/`rt setup` si bloccano indefinitamente e non
completano MAI la trascrizione su una lezione di durata reale. Causa: il comando
`macparakeet-cli transcribe` viene invocato senza `--output-dir`, quindi scrive l'intero JSON
(centinaia di KB per lezioni lunghe, include `wordTimestamps` per ogni parola) su stdout; il
codice fa polling su `proc.poll()` senza mai leggere lo stdout finché il processo non termina →
deadlock sul buffer del pipe (64KB) non appena l'output lo supera. Include anche: fix
`--no-diarize` mancante, fix drag-and-drop con virgola nel nome file (`\,` non gestito), barra
di progresso leggibile, e preservazione del dato di confidenza per-parola (`wordTimestamps`)
oggi scartato — campo `confidence` per-segmento sempre `None` per l'export macparakeet-cli,
mai popolato dalla migrazione MacWhisper→macparakeet-cli del Task 19.

**Task 36**: 5 bug puntuali in `rt/pipeline/configure.py` trovati nello stesso giro di test:
campo selezione modello pre-riempito col primo risultato del fetch invece di partire vuoto;
nessun avviso "chiave già presente" nel percorso a chiave singola (presente solo per
round-robin); il placeholder `RT_TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token` di
`.env.example` (copiato verbatim in `.env` al bootstrap) viene trattato come token reale già
configurato; fetch della lista modelli con errore generico non diagnosticabile (verificare in
particolare se l'endpoint OpenAI-compatibile di Google supporta `/models`); nessuna pulizia di
virgolette sul path `lessons_root` incollato (riusa `clean_input_path` già esistente in
`setup.py`, non duplicare la logica).

**Task 37**: inserimento chiavi API round-robin in batch (separate da virgola) invece di un
prompt per chiave (13 prompt separati per 13 chiavi, riprodotto empiricamente).

**Task 38**: redesign della schermata di assegnazione modello-per-fase come blocchi/card
navigabili liberamente avanti/indietro (stile "science-review", riusando il pattern già
esistente in `issue_review.py::run_interactive_review` — `rich.Live` + `read_single_key` con
supporto nativo LEFT/RIGHT/back già in `rt/core/keyboard.py`), con intestazione di stato per
fase e schermata finale "Conferma"/"Modifica" (oggi il wizard scrive su disco e stampa un
riepilogo statico non modificabile subito dopo l'ultima domanda). Sposta anche la sezione
"Pricing Custom" da intestazione a riquadro a semplice domanda inline (oggi appare fuori
sequenza logica, essendo invocata dentro la sezione "1." nonostante il numero "4.").

**Task 39**: la discovery live Telegram, se fallisce, entra SEMPRE ed incondizionatamente
nell'inserimento manuale via link, senza poter ritentare la discovery né annullare — va
sostituito con un menu di scelta. Rimuove anche un ID di canale reale usato come esempio nei
prompt (sostituito con un ID fittizio). Aggiunge `rt config --topics` per gestire (listare,
rinominare, rimuovere, modificare) i topic già configurati senza rifare l'intera sezione
Telegram, sullo stesso pattern di `--models`/`--telegram` già esistenti.

**Nota per Antigravity**: i Task 36, 37 e 38 toccano tutti `rt/pipeline/configure.py`.
Eseguili in quest'ordine (36 → 37 → 38) per isolare i commit per causa e ridurre conflitti di
merge, come indicato nell'intestazione di ciascun file.

## Aggiornamento — Task 35-39 completati, verificati manualmente in chat (non fidarsi del
walkthrough testuale di Antigravity)

Task 35-39 risultano committati (`5fbfe79`...`1d9ee3b`) e la suite passa (643/643, verificato
rieseguendo `pytest` direttamente, non fidandosi del resoconto). Verifica puntuale del codice
reale (non del solo testo del walkthrough, che di nuovo conteneva percorsi di file inventati,
es. `.agents/tasks/...` — quella cartella non esiste): Task 35, 36, 37, 39 corretti e verificati
a livello di codice. **Task 38 è incompleto rispetto alla spec**: doveva riusare la UI a card
`rich.Live`/`read_single_key` già esistente in `issue_review.py` (stile "science-review", frecce
LEFT/RIGHT dirette), ma è stato implementato invece con un menu `questionary.select` con voci
testuali "⬅️ Fase precedente"/"➡️ Fase successiva" — funzionalmente nella direzione giusta
(navigazione libera, scrittura differita a conferma, modifica post-conferma) ma non la UI a
blocchi letteralmente richiesta. **Task 43** (vedi sotto) corregge questo con una specifica UX
più precisa fornita dall'utente.

## Aggiornamento — Task 40-42: rimozione review_asr, rename review_science→review, nuovo
meccanismo di rilevamento ASR statistico + LLM opzionale

Decisione dell'utente dopo mesi di uso reale: `review_asr` (correzione termini tecnici via LLM,
confidence gating GREEN/YELLOW/RED) non è mai usato nella pratica — il rewrite gestisce già da
solo il ~95% dei casi — e va **rimosso interamente**, non solo disattivato. Contestualmente,
`review_science`/`rt review-science` viene **rinominato internamente e non solo nel comando** in
`review`/`rt review` (modulo, funzione, chiave di fase idempotenza, file YAML di job) — nessun
vincolo di retrocompatibilità: siamo in fase di test, non esistono lezioni reali da proteggere.

**Task 40** (prerequisito di 41 e 42): rimozione completa di `review_asr` (modulo, CLI, job
YAML, prompt LLM, soglie config, wiring in `rt run`, integrazione review interattiva/Telegram,
docs) + rename completo `review_science`→`review` in ogni namespace (job routing, fase di
idempotenza, modulo/funzione, comando CLI, docs) — **eccetto** i nomi delle classi Pydantic
`ScienceIssue`/`ScienceType`/`ScienceSeverity`, che restano invariati (fuori scope, nessun
beneficio a fronte di un refactor enorme).

**Task 41**: nuovo meccanismo di rilevamento ASR **puramente statistico e deterministico**
(zero LLM, gratis), integrato DENTRO `review` (non una fase separata) e mostrato nella STESSA UI
a card delle issue scientifiche. Per ogni segmento calcola il percentile-10 delle confidenze
parola (NON la media già esistente in `Segment.confidence` dal Task 35 — quella resta per il suo
scopo attuale), poi flagga i segmenti significativamente degradati rispetto alla distribuzione
di QUELLA lezione (mediana + MAD scalato, soglia relativa) più una soglia assoluta di sicurezza
per lezioni con audio uniformemente scadente. Genera issue `ScienceType.ERR_ASR_ST` (una per
unità, non per segmento), con solo due azioni utente possibili — Accetta / Modifica, niente
"Applica correzione" perché non c'è un candidato proposto da un LLM. **Include un fix di un bug
reale trovato leggendo `ledger.py::apply_decisions_to_draft`**: la sostituzione testuale cerca
`iss.claim` come sottostringa letterale nel draft, ma per queste issue `claim` è la trascrizione
RAW (quasi certamente non presente verbatim nel testo riscritto) — senza il fix, una correzione
scritta dall'utente verrebbe silenziosamente scartata e mai applicata al documento finale.

**Task 42**: flag opzionale `rt review --asr-llm` che sostituisce, SOLO per le unità con
candidati statistici, la generazione diretta di `ERR_ASR_ST` con un arricchimento del prompt
della normale chiamata LLM di critica scientifica per quell'unità (nessuna chiamata di rete
aggiuntiva, solo più contesto nel prompt per le unità coinvolte) — l'LLM giudica se il testo
rielaborato è fedele o fabbricato rispetto al segmento raw a rischio, generando `ERR_ASR_LLM`
solo se conferma il sospetto (altrimenti il candidato è scartato senza generare nulla): meno
falsi positivi, costo leggermente più alto solo per le unità toccate.

## Ordine di esecuzione (aggiornato)

1. **Task 40** (prerequisito di 41, 42 e 43).
2. **Task 41** (dipende da 40).
3. **Task 42** (dipende da 41).
4. **Task 43** (dipende solo da 40, non da 41/42 — file diverso, `configure.py` non
   `review.py`/`models.py`; corregge il Task 38 con una UI a card letterale, sostituendo il
   meccanismo `questionary.select` con `rich.Live`+`read_single_key`).

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
