# Task 75 — Player audio "companion" (mpv) per la review scientifica, al posto del play in-terminale

Indipendente dagli altri task attivi, ma va implementato DOPO il Task 74 (che ridisegna la card e
libera/riassegna le lettere): questo task riusa lo schema di tasti definito lì (in particolare `P`
per il player) e presuppone che `_build_science_panel`/`IssueReviewApp` siano già nello stato
finale di quel task. Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente,
senza produrre un piano preliminare.

## Contesto

Oggi, in `issue_review.py`, il tasto `P` riproduce un ritaglio audio di ±5s attorno al claim
DIRETTAMENTE nel terminale (subprocess audio in background, nessuna interfaccia), e `O` riavvia
quel ritaglio da capo. L'utente vuole sostituire interamente questo meccanismo con un player
esterno con interfaccia grafica ("companion"), che:

- Riproduce l'INTERA unità didattica soggetta alla correzione (non solo ±5s attorno al claim),
  per poter cercare liberamente il punto esatto in cui viene fatto il claim nell'audio originale.
- Si apre AFFIANCO al terminale (non sopra), con il focus che passa automaticamente al player.
- Permette di navigare nella registrazione con le frecce (seek) e cambiare velocità di
  riproduzione con scorciatoie da tastiera — **`mpv` supporta già entrambe le cose nativamente**
  (frecce sinistra/destra = seek ±5s, `[`/`]` = velocità ±10%, `{`/`}` = dimezza/raddoppia
  velocità, Backspace = reset velocità — verificato via ricerca, vedi `mpv --input-test`/
  `mpv.io/manual` per la lista completa), quindi RT non deve reimplementare seek/velocità: si
  limita a lanciare `mpv` con le opzioni giuste.

## Comportamento richiesto (deciso con l'utente)

1. **Apertura**: premendo `P` quando il player NON è aperto, lancia `mpv` con l'intero clip audio
   dell'unità corrente (vedi sotto per il ritaglio/caching), posizionato AFFIANCO al terminale.
2. **Posizionamento finestra**: rileva la posizione/dimensione REALE della finestra Terminal.app
   attiva (AppleScript, es. `tell application "Terminal" to get bounds of front window`) e posiziona
   `mpv` (flag `--geometry`) immediatamente alla sua destra. Se la rilevazione fallisce per
   qualunque motivo: usa come fallback l'ULTIMA posizione in cui l'utente ha chiuso il player in
   una sessione precedente (persisti questa posizione, es. in `~/.rt/mpv_last_position.json` o
   analogo — leggi il punto "Persistenza posizione" sotto per come ottenerla), non una posizione
   fissa arbitraria.
3. **Persistenza posizione**: usa il socket IPC di mpv (`--input-ipc-server=<path>`, protocollo
   JSON documentato in `mpv.io/manual` sotto "JSON IPC") per interrogare periodicamente (es. ogni
   pochi secondi, mentre il player è aperto) la posizione/dimensione della finestra e salvarla nel
   file di stato sopra — così anche se l'utente chiude il player con Cmd+Q o il pulsante rosso
   (senza passare da RT), l'ultima posizione nota resta comunque aggiornata per il prossimo avvio.
   Verifica il comando IPC esatto per leggere la geometria finestra nella documentazione mpv
   (potrebbe non esistere una property diretta per la posizione assoluta su schermo — se mpv non
   espone questo dato in modo affidabile via IPC, documenta il limite trovato e usa il fallback
   più ragionevole che riesci a costruire, es. salvare almeno le dimensioni/`--geometry` richiesta
   all'avvio invece della posizione osservata).
4. **Chiusura manuale**: premendo `P` di nuovo (con focus sul terminale, player aperto) chiude il
   player (termina il processo `mpv`, es. tramite il comando IPC `quit` o terminando il
   sottoprocesso).
5. **Chiusura diretta dall'utente**: se l'utente chiude `mpv` da sé (Cmd+Q o pulsante di
   chiusura), RT deve accorgersene (poll periodico di `subprocess.Popen.poll()`, o monitor del
   socket IPC che si disconnette) e aggiornare il proprio stato interno ("player chiuso") così
   che un successivo `P` lo riapra invece di tentare di richiudere un processo già morto.
6. **Auto-chiusura su azione nel terminale**: se il player è aperto e l'utente, tornato con il
   focus sul terminale, preme `A` (accetta), `R` (rifiuta) `I` (indietro) o `S` (salta) — cioè
   un tasto che fa avanzare/cambiare la card corrente — il player va chiuso AUTOMATICAMENTE prima
   di procedere con quell'azione. Se invece preme `M` (modifica) o non fa nulla, il player resta
   aperto.
7. **Riciclo del ritaglio audio**: l'intero clip dell'unità va tagliato/cachato con lo STESSO
   meccanismo già usato da `send_unit_audio` (`rt/pipeline/recall_session.py`, righe 46+, "Il clip
   viene ritagliato una sola volta e messo in cache") — verifica se quella funzione/il suo
   meccanismo di cache è direttamente riusabile per un intervallo "intera unità" invece del range
   specifico che usa oggi per il recall, o se serve una variante. L'obiettivo è che lo stesso file
   di clip cachato venga riusato SIA dal player companion in `issue_review.py` SIA dal bottone 🔊
   di Telegram, senza rilanciare `ffmpeg` due volte per lo stesso materiale.

## Modifica

- Rimuovi la riproduzione audio in-terminale attuale in `IssueReviewApp` (subprocess diretto,
  `action_toggle_audio`/`action_restart_audio`, gestione pausa/ripresa manuale) — non serve più,
  sostituita dal player esterno.
- Rimuovi il tasto `O` (non ha più senso: riavviare da capo è un semplice seek nel player).
- Implementa il ciclo di vita del player companion come descritto sopra: lancio, posizionamento,
  rilevamento chiusura (worker/timer Textual, stesso pattern già usato altrove nel progetto per
  monitorare processi in background senza bloccare l'event loop), toggle su `P`, auto-chiusura su
  `A`/`R`/`I`/`S`.
- Verifica che `mpv` sia installato (`shutil.which("mpv")`) prima di tentare di lanciarlo: se
  manca, mostra un messaggio chiaro (es. "Installa mpv con 'brew install mpv' per usare il player
  companion") invece di fallire con un errore criptico.

## Test

- Test che verifica che il primo `P` lanci `mpv` (mocka `subprocess.Popen`) con il path del clip
  dell'unità corrente e con `--geometry` calcolato dalla posizione rilevata (o dal fallback).
- Test che verifica che un secondo `P` (player già aperto) lo chiuda (verifica la chiamata di
  terminazione/comando IPC, non un secondo lancio).
- Test che verifica che, con il player aperto, premere `A`/`R`/`I`/`S` chiuda il player PRIMA di
  eseguire l'azione corrispondente.
- Test che verifica che premere `M` con il player aperto NON lo chiuda.
- Test che verifica il rilevamento di una chiusura esterna (mocka `Popen.poll()` per restituire un
  codice di uscita) e che un `P` successivo riapra il player invece di provare a richiuderlo.
- Test che verifica il comportamento quando `mpv` non è installato (messaggio chiaro, nessun
  crash).
- Test che verifica il riuso del clip cachato (nessuna seconda chiamata a `ffmpeg`/`cut_clip` se
  il clip esiste già).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Soluzione specifica per macOS (Terminal.app + mpv via Homebrew),
coerente con lo scope attuale del progetto.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale con `mpv` installato: `rt review`, premi `P`, verifica apertura affianco al
   terminale con focus sul player, prova seek/velocità nativi di mpv, torna al terminale e prova
   sia l'auto-chiusura (premendo A/R/I/S) sia la persistenza (M non chiude), chiudi con Cmd+Q e
   verifica che RT se ne accorga, riapri con P e verifica la posizione (rilevata o di fallback).
