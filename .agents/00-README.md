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

Task 63, 55-59, 61-62 e 64 (pilota Textual) implementati da Antigravity, verificati riga per
riga (non solo dal resoconto): 697/697 test. Due bug reali trovati in revisione e corretti a
parte (`1fea616`, non da Antigravity): il Task 55 aveva cancellato per errore la voce di pricing
statico `gemini-2.5-pro`; il Task 64 scartava il valore di ritorno di `OutlineReviewApp.run()`,
per cui uscire con Ctrl+Q (binding di default di Textual) faceva stampare "Outline approvata" e
proseguire a REWRITE come se il primario avesse premuto A — corretto (ora solleva
`KeyboardInterrupt`, gestito dal blocco già esistente in `cli.py::main()`). **Pilota Textual
confermato con test manuale reale** (`rt run ... --mock`, più cicli M→feedback→outline
rigenerata): nessuna duplicazione visiva, Ctrl+Q interrompe correttamente senza approvare —
l'ipotesi centrale della migrazione (causa del bug di duplicazione = accoppiata rich.Live+parsing
ANSI manuale) è confermata.

Task 65-68 implementati da Antigravity, verificati riga per riga: 692/692 test (calo di 5 dal
totale precedente, corretto — sono gli unici test dedicati a `read_single_key`/`raw_mode` rimossi
col Task 68, nessun'altra copertura persa). Qualità alta: sia `issue_review.py` (Task 65) sia il
carosello di `configure.py` (Task 66) gestiscono correttamente l'uscita senza approvazione
(`action_quit` esplicito con `exit(False)`/flag di stato dedicato, verificato anche l'esatto
binding vincente per `ctrl+c`/`ctrl+q` con un test empirico) — meglio del pilota originale del
Task 64, che avevo dovuto correggere a parte. L'osservazione lasciata in sospeso sul fallimento
silenzioso di `questionary.text()` dentro `app.suspend()` è stata risolta correttamente nel
Task 66 con un thread dedicato (`_run_in_thread`, `ThreadPoolExecutor`) che evita il conflitto con
l'event loop di Textual — portato lo stesso fix anche in `outline_review.py` (Task 64) per
coerenza ed eliminare il RuntimeWarning residuo lì, non toccato da Antigravity in questo giro
(fix diretto, `<commit successivo>`). `rt/core/keyboard.py` rimosso, zero riferimenti residui
(verificato con grep indipendente). Migrazione a Textual COMPLETA su tutte e 4 le schermate.

Rilasciato tag v3.1.0 (git) per permettere l'aggiornamento via `rt -u` sulle altre installazioni.

Quarto giro di test reale (MacBook Air, indagine via SSH sui log reali). Fix diretti applicati e
pushati: voce Telegram in active recall salvata con estensione `.oga` non riconosciuta da
macparakeet-cli (serve `.ogg`, stesso contenitore); bottone 📖 dopo `/quit` ricostruiva la
tastiera includendo ⏭️ (skip) anche ad attività chiusa, ora verifica se la sessione è ancora
attiva; testo ridondante rimosso da un prompt materia Telegram; Ctrl+C durante lo streaming LLM
NON deve più attivare il fallback (era trattato come un errore qualunque, arrivava a provare
altre route invece di fermarsi subito) — rimossa anche `UserAbortedFailure`, rimasta orfana.

**Scoperta importante durante l'indagine (via log reali `llm_debug.log` sull'Air)**: il Task 63
(esaurisci il pool round-robin prima del fallback) interagisce male con `max_attempts` quando il
pool è più grande del cap configurato — es. `review.yaml` reale con 6 chiavi round-robin e
`max_attempts: 3`: un errore sistemico (503 "high demand" su Google, non isolato a una chiave)
esaurisce il cap SOLO ciclando 3 delle 6 chiavi del pool, senza mai raggiungere il
`fallback.generic` configurato — confermato riga per riga nel log reale. Deciso con l'utente: il
cap effettivo si alza automaticamente per i job round-robin, senza bisogno di toccare la config a
mano → Task 70.

Deciso anche il design di `rt cost` (nuovo comando diagnostico, "niche"): nessuna nuova
infrastruttura di logging necessaria, `_state/llm_debug.log` (già scritto in append per OGNI
chiamata LLM di OGNI fase, incluse generazione/valutazione domande di recall — verificato nel
codice) è già la fonte dati completa. `rt cost` (overview) somma tutto incluse le chiamate fallite
con costo parziale non nullo (l'utente vuole vedere anche lo spreco reale); `rt cost --split`
(debug dei costi) mostra il dettaglio massimo per fase e per unità → Task 71.

Rilasciato tag v3.1.1. Quinto giro di test reale. Indagati 4 punti senza scrivere codice
d'implementazione ancora (in attesa di conferma utente su alcuni, altri già chiariti):

- **Terminale del demone Telegram "freezato" durante generazione/eval**: causa individuata —
  `Application.builder()` in `rt/telegram/daemon.py` (riga ~1066) non imposta
  `.concurrent_updates(True)`, quindi python-telegram-bot processa UN update alla volta: mentre
  l'esecutore in background genera le domande (già correttamente su `run_in_executor`, non è un
  problema di thread bloccanti), qualunque altro comando/bottone in arrivo resta in coda finché
  l'handler corrente non termina — sembra un freeze del bot, non lo è per davvero. Trovato però un
  rischio reale se si abilita la concorrenza senza altri interventi: `rt/pipeline/recall.py::
  load_recall_bank`/`save_recall_bank` (il ban delle domande/risposte) non ha alcun locking,
  mentre `registry.py`/`session.py` ce l'hanno già — abilitare `concurrent_updates=True` da solo
  introdurrebbe un rischio di race condition (letture-modifiche-scritture concorrenti sullo stesso
  file). Proposta migliore dell'idea originale dell'utente (subprocess/altro terminale): abilitare
  la concorrenza nativa di PTB + aggiungere lo stesso locking già usato altrove attorno al
  ciclo lettura-modifica-scrittura del recall bank. Portato all'utente per conferma prima di
  taskare (vedi sotto).
- **Impossibile selezionare testo nel terminale durante le schermate Textual**: NON è un bug RT,
  confermato con ricerca — Terminal.app (a differenza di iTerm2/Warp) non supporta la sequenza
  OSC 52 che Textual usa per il copia-incolla nativo, e la cattura del mouse da parte di un'app
  TUI impedisce comunque la selezione nativa del terminale. Workaround noto: tenere premuto
  **Shift** durante la selezione per bypassare la cattura mouse dell'app TUI e usare la selezione
  nativa di Terminal.app. Nessun codice da cambiare — comunicato all'utente, nessun task.
- **Editor "pico" invece di "micro" nonostante `micro` installato**: NON è un bug — `rt/core/
  editor_edit.py` legge `$EDITOR` (fallback `nano` se non impostata, mai "pico" per scelta di RT)
  e rispetta fedelmente quello che l'utente ha configurato nella propria shell. "pico" arriva
  dall'ambiente dell'utente (`$EDITOR` probabilmente impostata a `pico` in qualche dotfile legacy),
  non da RT. Comunicato: basta `export EDITOR=micro` nel proprio shell profile per usarlo ovunque,
  incluso RT — nessun task.
- **Companion audio player esterno per la review** (Allegato 1 lungo dell'utente): ricerca fatta,
  `mpv` è il candidato forte — frecce già mappate a seek, `[`/`]`/`{`/`}` già mappati a velocità
  ±10%/dimezza-raddoppia, `--geometry` per posizionare la finestra. Design rifinito con l'utente:
  posizione rilevata via AppleScript con fallback sull'ultima posizione di chiusura (richiede il
  socket IPC di mpv per persisterla, non solo `.poll()`), auto-chiusura su A/R/I/S ma non su M →
  Task 75. Contestualmente, l'utente ha chiesto di uniformare le lettere della card di review
  (A=Accetta, R=Rifiuta, M=Modifica, I=Indietro) su ENTRAMBI i rami (Science Critic e RISCHIO
  ASR) → ripiegato nel Task 74, che già toccava l'action bar per il redesign visivo.

## Task da fare, in ordine

1. **69** — In fase di build, sposta (non copia) la cartella lezione in `lessons_root` se
   configurato: oggi non esiste alcuna logica che lo fa (verificato leggendo il codice, non un
   fix precedente rotto), la cartella lezione resta sempre accanto all'audio sorgente.
2. **70** — `max_attempts` deve alzarsi automaticamente per i job round-robin (almeno dimensione
   pool + 1) così il fallback dedicato viene sempre raggiunto anche con un errore sistemico che
   colpisce l'intero pool, senza richiedere modifiche manuali alla config.
3. **71** — Nuovo comando diagnostico `rt cost <cartella> [--split]`: legge e somma
   `_state/llm_debug.log` (dato già esistente), overview vs dettaglio massimo per fase/unità.
4. **72** — Dopo il build, rileva in modo affidabile (PID file) se il demone Telegram è già
   attivo; se non lo è, chiedi conferma e avvialo in automatico in una nuova finestra Terminal.
5. **73** — Abilita `concurrent_updates(True)` nel demone Telegram (causa reale del "freeze"
   percepito durante generazione/eval) insieme al locking del recall bank, oggi assente, per
   evitare race condition una volta abilitata la concorrenza.
6. **74** — Redesign della card di review scientifica (ramo Science Critic): niente più timecode,
   claim con prefisso "- " in rosso inline nel testo dell'unità, correzione proposta con prefisso
   "+ " in verde subito sotto (stile diff), mini legenda con sole emoji sotto la critica. Mockup
   approvato dall'utente in `/Users/attilioturco/Desktop/rt_review_card_mockup.py`. Include anche
   la ridenominazione dei tasti (decisa con l'utente, si applica a ENTRAMBI i rami Science
   Critic/RISCHIO ASR): A=Accetta, R=Rifiuta, M=Modifica (era E), I=Indietro (era B), S/Q
   invariati — P/O non toccati, riservati al Task 75.
7. **75** — Player companion `mpv` per la review scientifica al posto del play in-terminale
   (tasto P): riproduce l'intera unità (non solo ±5s), si apre affianco al terminale (posizione
   rilevata via AppleScript, fallback sull'ultima posizione di chiusura persistita), seek/velocità
   nativi di mpv, auto-chiusura su A/R/I/S ma non su M, riusa il clip cachato già usato dal
   bottone 🔊 di Telegram. Va dopo il Task 74 (riusa lo schema di tasti definito lì).

## In sospeso — decisioni da prendere con l'utente prima di trasformarle in task

Nessuna al momento: tutti i punti del giro precedente sono stati decisi (vedi "Stato" sopra e i
Task 72-75).

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
