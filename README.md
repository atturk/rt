# RT — Academic Lecture Transcription & Reconstruction Engine

Sistema ibrido industriale per la trascrizione e rielaborazione accademica delle lezioni universitarie.

Combina **codice deterministico** (parsing ASR, normalizzazione temporale in secondi, segmenti strutturati, validazione, decision ledger e assemblaggio Markdown) con **job cognitivi LLM specializzati** (Outline gerarchico vincolato a segmenti, Rielaborazione a finestre con memoria di contesto e provenance, ASR Review con Confidence Gating e Science Critic indipendente — un **LLM-based scientific plausibility critic**: analizza la plausibilità concettuale del testo tramite un modello linguistico, non un sistema di verifica bibliografica/RAG contro fonti esterne).

---

## ⚡ Caratteristiche Principali

- **Timestamp Deterministici e Tracciabili**: Nessun timestamp arbitrario generato dall'LLM. Tutti i timecode nel Markdown derivano rigorosamente dai segmenti audio ASR (`seg_ID → start_seconds → MM:SS`).
- **Provenienza Completa**: Ogni paragrafo rielaborato è collegato in modo bidirezionale ai segmenti sorgente (`source_segment_ids`).
- **Routing Engine Multi-Provider & Round-Robin N-way**:
  - Supporto per DeepSeek, OpenRouter, Google Gemini (con un numero arbitrario di account/chiavi, es. `google_1`...`google_9`) e Mock deterministico.
  - Round-Robin deterministico e thread-safe su un numero arbitrario di route configurate (non solo 2).
  - Error-Aware Failover mirato per classe di fallimento (`timeout`, `rate_limit`, `safety`, `auth`, `generic`).
  - Loop Protection rigida (`visited_routes`) e Hard Cap globale (`max_attempts`).
  - Output Explosion Guard (limite rigido caratteri in streaming SSE).
- **Confidence Gating a 3 Livelli**:
  - **GREEN**: correzioni ovvie/fonetiche certe (auto-applicate con log).
  - **YELLOW**: ipotesi plausibili ma ambigue (coda di revisione utente).
  - **RED**: termini ad alto rischio o incerti (richiesta conferma d'ascolto).
- **Critic Scientifico Indipendente**: Distingue chiaramente tra lapsus del docente (`ERR_DOCENTE`), allucinazioni del modello (`ERR_RECONSTRUCTION`) e controlli di plausibilità (`SCIENCE_CHECK`).
- **Human Decision Ledger**: Persistenza di tutte le decisioni in `review_decisions.json`. Riproducibile e idempotente.
- **Retrocompatibilità Totale**: Supporta sia le trascrizioni storiche Markdown/MacWhisper sia gli export JSON nativi di `macparakeet-cli` (motore ASR di default).

---

## 🚀 Guida Rapida

### 1. Requisiti e Configurazione

#### Installazione Automatica (Consigliata su macOS)

Scarica ed installa l'ultima release ufficiale di RT con un solo comando:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/atturk/rt/main/bootstrap.sh)"
```

*(In alternativa, per chi preferisce vedere prima cosa scarica)*:
```bash
mkdir -p rt && curl -sL $(curl -sL https://api.github.com/repos/atturk/rt/releases/latest | grep '"tarball_url":' | cut -d '"' -f 4) | tar -xz -C rt --strip-components=1 && cd rt && ./install.sh
```

*(In alternativa per sviluppatori con git già installato)*:
```bash
git clone https://github.com/atturk/rt.git && cd rt && ./install.sh
```
Lo script `install.sh` verifica i prerequisiti di sistema (Homebrew, Python 3.11+, `ffmpeg`), crea l'ambiente virtuale `.venv`, installa le dipendenze e inizializza i file di configurazione (`config/` e `.env`).

#### Installazione Manuale (Alternativa / Non-macOS)

Python 3.11+ con dipendenze installate:
```bash
pip install -r requirements.txt
```
Per lo sviluppo e l'esecuzione dei test:
```bash
pip install -r requirements-dev.txt
```

Copia il template per le variabili d'ambiente (opzionale se si usano chiamate LLM reali):
```bash
cp .env.example .env
# Le chiavi che inserirai qui devono corrispondere ai nomi 'env_var' che dichiari
# in config/general.yaml sotto 'credentials:' (vedi docs/CONFIGURATION_REFERENCE.md)
```

Configurazione dei job e dei modelli:

Per una configurazione guidata e interattiva:
```bash
./bin/rt config
```
In alternativa, per configurare manualmente:
```bash
cp -r config.example config
# Modifica config/general.yaml e i singoli file per-job config/<job>.yaml
```
> I file YAML in `config.example/` sono volutamente senza commenti: il significato di ogni campo e le funzionalità opzionali (credenziali custom, pricing globale/per-route) sono documentati in [Guida alla Configurazione (CONFIGURATION_REFERENCE.md)](docs/CONFIGURATION_REFERENCE.md).


#### Interfaccia web locale

```bash
rt web
```

Avvia l'API, un worker per i job e la web app, e apre il browser già autenticato su
`http://127.0.0.1:8765`. Dalla web fai tutto quello che fai nel terminale: importi l'audio,
segui la pipeline in tempo reale, approvi la scaletta, fai la review accanto al testo con
l'audio, leggi il documento con i timecode, fai il recall anche a voce, aggiungi immagini e
configuri provider, modelli e Telegram. Al primo avvio una configurazione guidata chiede la
cartella delle lezioni e il resto. `install.sh` e `rt -u` installano la web app compilata dalla
release. Dettagli in [Web app di RT](docs/WEB.md).

La vecchia interfaccia Gradio resta per questa release con `rt web --legacy` (deprecata; richiede
`./.venv/bin/python -m pip install -r requirements-web.txt`).

### 2. Esecuzione End-to-End di una Lezione

```bash
./bin/rt run "percorso/cartella_lezione"
```

Per testare offline senza consumare crediti API:
```bash
./bin/rt run "percorso/cartella_lezione" --mock --auto-accept
```

### 2-bis. Coda dei job e worker (opzionale)

Il database di RT si crea e si aggiorna da solo al primo comando (e importa le lezioni già
presenti): non servono comandi di database. Per far girare le elaborazioni lunghe in un
processo separato, avvia un worker e accoda la pipeline:

```bash
./bin/rt worker                          # esegue i job in coda (Ctrl+C per fermarlo)
./bin/rt run "cartella_lezione" --queue  # accoda e segue il progresso
./bin/rt jobs                            # elenca i job; 'rt jobs cancel ID' ne annulla uno
```

Senza `--queue`, `rt run` lavora in processo come sempre. Con un worker attivo anche il daemon
Telegram gli passa la generazione delle domande di recall e la trascrizione dei vocali.

### 2-ter. Dove finiscono le lezioni

Le nuove lezioni non creano più una cartella di lavoro: testi e metadati stanno nel database
di RT e audio e immagini originali nella cartella `media/` accanto a `rt.db`. Il Markdown
finale (e, se servono, tutti gli altri dati) si scarica quando serve:

```bash
./bin/rt export "[2026-09-05] BIOCHIMICA - Lipidi" -o ~/Desktop   # Markdown finale con immagini
./bin/rt export "[2026-09-05] BIOCHIMICA - Lipidi" --all --zip    # tutti i dati in uno zip
```

Le lezioni create prima restano nelle loro cartelle e funzionano come sempre. Per portarle nel
database (una volta sola, con backup; le cartelle originali vengono spostate, non cancellate):

```bash
./bin/rt db migrate-storage --dry-run   # mostra cosa verrebbe spostato
./bin/rt db migrate-storage
```

### 3. Esecuzione Passo-Passo

```bash
./bin/rt prepare "cartella_lezione"           # Estrae segmenti e crea segments.json
./bin/rt outline "cartella_lezione"           # Genera outline strutturata con LLM
./bin/rt validate-outline "cartella_lezione"  # Valida monotonicità e copertura
./bin/rt rewrite "cartella_lezione"           # Rielabora a finestre con provenance
./bin/rt validate-draft "cartella_lezione"    # Valida il draft prodotto
./bin/rt review "cartella_lezione"            # Revisione scientifica e delle ambiguità ASR
./bin/rt build "cartella_lezione"             # Genera i documenti Markdown definitivi
./bin/rt status "cartella_lezione"            # Mostra lo stato di avanzamento
```

### 4. Notifiche e Comandi via Telegram (opzionale)

Le funzionalità Telegram (routing per topic in base alla materia, notifica di build completata,
`/list`, `/recall <query>`, active recall via bot) richiedono un **processo persistente** distinto
dalla pipeline `rt run`:

```bash
./bin/rt telegram-daemon
```

Senza questo processo in esecuzione continua, nessuna funzionalità Telegram funziona — anche se
`config/general.yaml`/`.env` sono configurati correttamente (verifica prima con `./bin/rt config`,
vedi sopra). Va lasciato attivo in un terminale/tab dedicato, con `tmux`/`screen`, oppure fatto
ripartire automaticamente ad ogni accesso con un LaunchAgent macOS
(`~/Library/LaunchAgents/com.rt.telegram-daemon.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.rt.telegram-daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/percorso/assoluto/rt/bin/rt</string>
        <string>telegram-daemon</string>
    </array>
    <key>WorkingDirectory</key><string>/percorso/assoluto/rt</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/percorso/assoluto/rt/.rt_telegram/daemon.log</string>
    <key>StandardErrorPath</key><string>/percorso/assoluto/rt/.rt_telegram/daemon.err.log</string>
</dict>
</plist>
```
poi caricalo con `launchctl load ~/Library/LaunchAgents/com.rt.telegram-daemon.plist`.

---

## 📚 Documentazione Dettagliata

- [Guida alla Configurazione (CONFIGURATION_REFERENCE.md)](docs/CONFIGURATION_REFERENCE.md)
- [Architettura del Sistema (ARCHITECTURE.md)](docs/ARCHITECTURE.md)
- [Workflow e Ciclo di Vita (WORKFLOW.md)](docs/WORKFLOW.md)
- [Modelli Dati e Contratti JSON (SCHEMAS.md)](docs/SCHEMAS.md)
- [Guida allo Sviluppo e Test Suite (DEVELOPMENT.md)](https://github.com/atturk/rt/blob/main/docs/DEVELOPMENT.md)
- [Motori di Trascrizione Alternativi (ALTERNATIVE_TRANSCRIPTION.md)](docs/ALTERNATIVE_TRANSCRIPTION.md)


---

## 🧪 Esecuzione dei Test

La suite di test comprende unit test, test di validazione timestamp, test del critic scientifico, test del decision ledger e regressione su una lezione reale di biochimica:

```bash
python3 -m pytest tests/
```

## Sviluppo e distribuzione

La radice del repository `rt/` contiene il pacchetto Python omonimo `rt/`: non sono due copie del progetto.
Configurazione personale, segreti e stato Telegram restano locali; lezioni e backup vanno fuori dal checkout.
Le installazioni da release e i cloni Git puliti sul branch `main` si aggiornano con
`rt -u`; il comando si ferma senza cambiare i file se rileva modifiche locali o un
altro branch. Chi usa una versione precedente alla 3.4.2 in un clone Git deve
eseguire una volta il comando di transizione qui sotto, perché alcune vecchie
versioni non gestiscono correttamente gli aggiornamenti nei cloni. Lo stesso
comando funziona anche sulle installazioni da archivio e verifica le dipendenze web:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/atturk/rt/main/scripts/upgrade_legacy.sh)"
```

Il comando si interrompe prima di modificare un clone Git se non è su `main` o
se contiene modifiche tracciate. Da quel momento gli aggiornamenti successivi si
fanno con `rt -u`.
La trascrizione integrata usa `macparakeet-cli` su macOS; gli altri sistemi possono elaborare trascrizioni già prodotte.

Per contribuire: [sviluppo](https://github.com/atturk/rt/blob/main/docs/DEVELOPMENT.md), [gestione file e release](https://github.com/atturk/rt/blob/main/docs/MAINTENANCE.md),
[valutazione delle interfacce](https://github.com/atturk/rt/blob/main/docs/INTERFACE_DIRECTION.md) (documenti disponibili nel repository).
