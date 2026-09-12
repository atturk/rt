# Task 29 — `install.sh`: scelta motore STT, barra di progresso reale, PATH automatico

Dipende dallo stato attuale di `install.sh` (Task 28 già completato: colori, fasi, log pulito,
parallelismo, trap su interruzione — leggi il file per intero prima di procedere, questo task
lo estende senza stravolgerne la struttura). Indipendente dagli altri task. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## Contesto

Tre richieste emerse durante test reali ripetuti su un MacBook Air, con l'installazione ormai
pienamente funzionante end-to-end (~104s osservati).

## 1. Scelta motore STT (macparakeet-cli + modello Parakeet vs altro)

**Fatto rilevante verificato sulla formula Homebrew reale**
(`moona3k/homebrew-tap/Formula/macparakeet-cli.rb`): la formula dichiara
`depends_on arch: :arm64` — su un Mac Intel `brew install moona3k/tap/macparakeet-cli`
**fallisce sempre**, non è solo "sconsigliato". Questo non è quindi solo un miglioramento di
comodità ma un vero gate di compatibilità hardware.

RT non è vincolato a `macparakeet-cli` come motore ASR: `docs/ALTERNATIVE_TRANSCRIPTION.md`
documenta già come collegare qualunque altro motore (basta produrre un JSON in uno dei formati
riconosciuti da `parse_segments_from_json`, o usare `rt setup --skip-transcribe`).

Aggiungi, come primo passo della fase `[1/5] Prerequisiti di sistema` (prima dei controlli
esistenti su ffmpeg), una rilevazione dell'architettura seguita da una scelta interattiva:

```bash
IS_APPLE_SILICON=false
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
    IS_APPLE_SILICON=true
fi
```
(usa `sysctl -n hw.optional.arm64`, non `uname -m` da solo — `uname -m` riporta `x86_64` anche
su Apple Silicon se il terminale gira sotto Rosetta, dando un falso negativo; `hw.optional.arm64`
riflette l'hardware reale indipendentemente dalla traduzione Rosetta).

- Se `IS_APPLE_SILICON=true`: chiedi interattivamente (con un default motivato, "sì" come scelta
  di default se l'utente preme solo invio) se vuole installare `macparakeet-cli` e usare Parakeet
  come motore ASR predefinito (spiega brevemente perché è consigliato: gratuito, locale, veloce
  su Apple Silicon — riprendi il tono già usato altrove nel progetto). Se sceglie di no, salta
  interamente sia l'installazione di `macparakeet-cli` sia il download del modello (fase `[2/5]`
  intera diventa un no-op con un messaggio chiaro), e nel riepilogo finale aggiungi una nota che
  rimanda a `docs/ALTERNATIVE_TRANSCRIPTION.md` per collegare un motore alternativo.
- Se `IS_APPLE_SILICON=false` (Mac Intel): **non chiedere nulla** — macparakeet-cli non è
  installabile su questa architettura, salta automaticamente la sua installazione e il download
  del modello, stampa un messaggio informativo chiaro (una riga, non allarmistico: "ℹ️
  macparakeet-cli richiede Apple Silicon (M1 o successivo), non disponibile su questo Mac.
  Configura un motore ASR alternativo, vedi docs/ALTERNATIVE_TRANSCRIPTION.md.") e prosegui.

Se lo script gira in modalità non interattiva (`[ ! -t 0 ]`, es. da CI o da un altro script),
applica lo stesso default motivato senza bloccarti in attesa di input (default "sì" su Apple
Silicon, skip automatico su Intel).

**Non toccare** la sezione STT di `rt config` (`rt/pipeline/configure.py`,
`_configure_stt_section`): quella riguarda esclusivamente il motore usato per trascrivere le
risposte vocali durante l'active recall via Telegram (`telegram.recall.stt_engine`), un ambito
diverso e più ristretto della trascrizione principale delle lezioni. Sono due scelte STT
distinte nel sistema, non vanno unificate in questo task.

## 2. Barra di progresso reale invece della riga ripetuta ogni 10s

L'attuale `⏳ ancora in corso (Ns)...` stampato su una NUOVA riga ogni 10 secondi durante
l'attesa finale del download è stato esplicitamente giudicato brutto. macparakeet-cli scrive già
nel log (`install.log`, reindirizzato lì dal Task 28) righe con percentuale reale, es.:
```
Parakeet: Downloading speech model... 48% (7/23)
```
**Preferenza esplicita dell'utente**: prova prima a tracciare il progresso reale leggendo queste
righe dal log; se non è affidabile, ripiega su un semplice spinner + cronometro — ma in
ENTRAMBI i casi il requisito non negoziabile è: **una sola riga che si aggiorna sul posto**
(carriage return, es. `printf "\r%s" "$msg"` + `\033[K` per pulire eventuali residui di una riga
precedente più lunga), mai una riga nuova stampata ripetutamente.

Approccio consigliato (adattalo pure se trovi un modo più pulito):
```bash
show_download_progress() {
    local pid="$1"
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    local start_ts=$SECONDS
    while kill -0 "$pid" 2>/dev/null; do
        local elapsed=$((SECONDS - start_ts))
        local status
        status="$(grep -oE '[0-9]+% \([0-9]+/[0-9]+\)' "$LOG_FILE" | tail -1)"
        local spin_char="${spin:i++%${#spin}:1}"
        if [ -n "$status" ]; then
            printf "\r   %s Download modello Parakeet: %s (%ss)\033[K" "$spin_char" "$status" "$elapsed"
        else
            printf "\r   %s Download modello Parakeet in corso... (%ss)\033[K" "$spin_char" "$elapsed"
        fi
        sleep 0.3
    done
    printf "\r\033[K"
}
```
(nomi/dettagli a tua discrezione, ma mantieni: aggiornamento sul posto senza nuove righe,
estrazione best-effort della percentuale reale dal log con fallback a un indicatore generico se
il pattern non viene trovato, frequenza di refresh abbastanza alta da sembrare fluido — es.
0.2-0.5s — non 10s). Se non è la stessa funzione già presente per l'heartbeat, sostituiscila
interamente invece di tenerle entrambe.

Verifica empiricamente con un download reale (cancella prima il modello con
`macparakeet-cli models delete parakeet-v3 --force`) che la riga si aggiorni visibilmente sul
posto e non scrolli mai il terminale con righe multiple ripetute.

## 3. Aggiunta automatica della riga PATH al profilo shell

Decisione precedente esplicitamente superata dall'utente in questa sessione: non chiedere più
all'utente di aggiungere a mano la riga `export PATH=".../bin:$PATH"` — fallo automaticamente,
in modo trasparente (nessun prompt di conferma necessario, coerente con la scelta già fatta per
l'installazione automatica di `micro`), ma **idempotente** (non duplicare la riga se lo script
viene rilanciato) e senza mai sovrascrivere il resto del file.

- Rileva il file di profilo giusto: usa `$SHELL` per capire la shell di login dell'utente
  (`*/zsh` → `~/.zshrc`, `*/bash` → `~/.bash_profile`, che su macOS è quello letto dalle shell di
  login in Terminal.app — non `~/.bashrc`). Se `$SHELL` non è riconosciuta o il file target non
  esiste ancora, crealo. Default a `~/.zshrc` se non riesci a determinare la shell (è il default
  di macOS da Catalina in poi).
- Prima di scrivere, controlla se una riga equivalente (stesso `REPO_DIR/bin` nel PATH) è già
  presente nel file — se sì, salta silenziosamente senza duplicare. Altrimenti appendi in fondo
  al file un blocco chiaramente commentato, es.:
  ```
  # Aggiunto da RT install.sh
  export PATH="/percorso/reale/rt/bin:$PATH"
  ```
- Aggiorna il riepilogo finale per riflettere che il passo è già stato fatto, es. sostituendo
  "2. Per usare 'rt' da qualunque cartella, aggiungi questa riga al tuo ~/.zshrc: ..." con
  qualcosa come "2. ✅ 'rt' è già disponibile da qualunque cartella (riga aggiunta a
  ~/.zshrc) — apri un nuovo terminale o esegui `source ~/.zshrc` per usarlo subito in questa
  sessione."

## Vincoli

- Mantieni intatta la struttura a fasi `[N/5]` e i colori introdotti dal Task 28 — se aggiungere
  la scelta STT cambia il numero naturale di fasi percepite, va bene rinumerarle, ma non
  eliminare il concetto.
- Lo script deve restare valido bash (`bash -n install.sh`) e conservare `set -euo pipefail`.
- Verifica il comportamento non interattivo (`[ ! -t 0 ]`, es. `install.sh < /dev/null`) per la
  nuova domanda del punto 1: non deve mai bloccarsi in attesa di input in quel caso.

## Test

Come per il Task 28, non esiste una suite automatizzata per script shell in questo progetto —
verifica manualmente in una copia temporanea del repo e riporta l'esito nel resoconto finale:
1. Su questo Mac (Apple Silicon): esegui l'installazione da zero, rispondi "sì" alla domanda
   sul motore STT, verifica che macparakeet-cli/il modello si installino come prima e che la
   barra di progresso si aggiorni sul posto (nessuna riga ripetuta).
2. Ripeti rispondendo "no" alla domanda: verifica che macparakeet-cli e il download del modello
   vengano saltati interamente, e che il riepilogo finale rimandi correttamente alla
   documentazione per motori alternativi.
3. Simula un Mac Intel (es. temporaneamente sovrascrivendo l'esito del controllo
   `sysctl -n hw.optional.arm64` nello script per il test, o se hai accesso a una macchina/VM
   Intel usala davvero) e verifica che la domanda non venga posta affatto e che lo skip sia
   automatico con il messaggio informativo corretto.
4. Verifica l'idempotenza della riga PATH: esegui l'installazione due volte di fila sulla stessa
   cartella e controlla che `~/.zshrc` (o il file di profilo pertinente) contenga la riga UNA
   sola volta, non duplicata — usa un file di profilo di test isolato (non il vero `~/.zshrc`
   dell'utente) per questa verifica, es. sovrascrivendo temporaneamente la variabile che
   determina il percorso del file target, per non toccare la shell reale della macchina di test
   durante lo sviluppo/test di questo task.
5. Esegui `python3 -m pytest tests/ -q` per assicurarti che questo task (che non tocca codice
   Python) non abbia comunque introdotto regressioni.
6. Pulisci ogni cartella/file temporaneo di test alla fine.
