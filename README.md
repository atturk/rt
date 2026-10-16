# RT — Academic Lecture Transcription & Reconstruction Engine

Sistema ibrido industriale per la trascrizione e rielaborazione accademica delle lezioni universitarie.

Combina **codice deterministico** (parsing ASR, normalizzazione temporale in secondi, segmenti strutturati, validazione, decision ledger e assemblaggio Markdown) con **job cognitivi LLM specializzati** (Outline gerarchico vincolato a segmenti, Rielaborazione a finestre con memoria di contesto e provenance, ASR Review con Confidence Gating e Science Critic indipendente — un **LLM-based scientific plausibility critic**: analizza la plausibilità concettuale del testo tramite un modello linguistico, non un sistema di verifica bibliografica/RAG contro fonti esterne).

---

## ⚡ Caratteristiche Principali

- **Arricchimento delle lezioni**: immagini sulle macro unità con Decision API, idee grafiche sotto le subunità, visualizzazioni interattive e infografiche generate su richiesta. [Configurazione e utilizzo](docs/ENRICHMENT.md).
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

#### App per Mac e Windows (consigliata)

Dalla [pagina delle release](https://github.com/atturk/rt/releases/latest) scarica:

- **Mac (Apple Silicon)**: `RT-<versione>-macos-arm64.dmg`, aprilo e trascina RT in Applicazioni.
- **Windows (64 bit)**: `RT-<versione>-windows-x64-setup.exe` e installalo (non servono permessi
  di amministratore).

Dentro c'è tutto (Python, dipendenze, web app, ffmpeg): un doppio clic su RT prepara la cartella
dati `~/.rt` e apre la web app nel browser, sulla configurazione guidata. Sul Mac RT resta acceso in
background; su Windows resta acceso finché è aperta la sua finestra. Gli aggiornamenti stabili si
installano da Impostazioni › Info › Aggiornamenti; le beta si scaricano a mano dalle release.

L'app non è firmata: al primo avvio il Mac la blocca (Impostazioni di Sistema › Privacy e sicurezza
› Apri comunque) e Windows mostra SmartScreen (Ulteriori informazioni › Esegui comunque). Il
motore di trascrizione locale su Windows è Parakeet ONNX, che scarica il modello alla prima
trascrizione (circa 700 MB); sul Mac resta consigliato macparakeet.

#### Installazione in un comando (macOS, da terminale)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/atturk/rt/main/bootstrap.sh)"
```

Il comando scarica l'ultima release in `./rt` e fa tutto il resto: prerequisiti (Homebrew,
Python 3.11+, `ffmpeg`, `macparakeet-cli` se lo vuoi), ambiente Python, web app già compilata,
cartella dati `~/.rt` (configurazione, segreti cifrati, database, audio e immagini), servizi in
background per API e worker, e alla fine apre il browser sulla **configurazione
guidata** (provider e chiavi, modelli, notifiche Telegram facoltative). Non ci sono altri
passaggi. Rilanciarlo ripara un'installazione rotta senza toccare i dati.

Dopo l'installazione:

```bash
rt web          # apre la web app (i servizi sono già attivi)
rt web --verbose # apre la web e segue i log dei servizi già attivi; Ctrl+C interrompe la lettura
rt logs --follow # segue i log di API, worker e bot; rt logs bot --lines 100 per un servizio

rt service status # mostra lo stato dei servizi; rt service stop/start/restart li controlla
rt doctor       # controlla l'installazione e dice cosa sistemare
rt backup --dest /Volumes/Disco/rt-backup   # backup completo: database, media, configurazione
rt -u           # aggiorna codice, dipendenze, web app, database e servizi
rt -u --beta    # passa al canale beta: da ora 'rt -u' installa anche le versioni di prova
rt -u --stable  # torna al canale stabile
rt uninstall    # rimuove servizi e ambiente Python; dati e lezioni restano
```

La pagina Importa accetta anche uno o più ZIP completi (`scope=all`). Nella pagina della
lezione, Option (Mac) o il focus da tastiera mostra il cestino; la cancellazione richiede
il nome della lezione e la parola «confermo». Il pannello Fasi accetta istruzioni aggiuntive
per scaletta, riscrittura e revisione, e permette di revisionare una sola unità.
Impostazioni > Modelli comprende istruzioni globali, prova multimodale per il descrittore
immagini e un modello decisionale opzionale. Prima di abilitarne il gate, confronta le
false omissioni con le revisioni di un campione reale in modalità ombra.

Chi arriva dalla 3.x aggiorna con `rt -u` (se serve, due volte: la prima con il codice vecchio):
configurazione e database vengono spostati nella cartella dati, le vecchie cartelle delle
lezioni vengono convertite nel database (le originali restano nel backup della conversione) e
viene proposta la cifratura delle chiavi.

Le versioni beta (es. `4.1.0b1`) sono per chi vuole provare in anticipo le novità: `rt -u` le
ignora finché non si sceglie il canale beta con `rt -u --beta` (serve la 4.0.1 o successiva; la
scelta resta salvata nella cartella dati). `rt -v` segnala quando c'è una beta disponibile.
`rt -u --stable` torna alle versioni stabili senza tornare indietro: la beta resta installata fino
alla prossima versione stabile più recente, perché il database potrebbe essere già stato
aggiornato. Servizi, backup, Docker e percorsi sono descritti in
[Self-hosting](docs/SELF_HOSTING.md).

*(Per sviluppatori con git)*:
```bash
git clone https://github.com/atturk/rt.git && cd rt && ./install.sh
```

#### Installazione Manuale (Alternativa / Non-macOS)

Python 3.11+ con dipendenze installate:
```bash
pip install -r requirements.txt
```
Per lo sviluppo e l'esecuzione dei test:
```bash
pip install -r requirements-dev.txt
```

Configurazione, `.env`, database e media stanno nella cartella dati `~/.rt` (o `RT_DATA_DIR`),
non nella cartella del codice; `./bin/rt data` mostra i percorsi in uso. La via più semplice
è la configurazione guidata della web app (`./bin/rt web`); in alternativa:

```bash
./bin/rt data init      # crea ~/.rt con la configurazione di partenza
./bin/rt secrets init   # archivio cifrato per chiavi API e token
```

Per configurare a mano modifica `~/.rt/config/general.yaml` e i file per-job
`~/.rt/config/<job>.yaml`.
> I file YAML in `config.example/` sono volutamente senza commenti: il significato di ogni campo e le funzionalità opzionali (credenziali custom, pricing globale/per-route) sono documentati in [Guida alla Configurazione (CONFIGURATION_REFERENCE.md)](docs/CONFIGURATION_REFERENCE.md).

Su Linux (server) RT gira anche con Docker: vedi [Self-hosting](docs/SELF_HOSTING.md#docker).


#### Interfaccia web locale

```bash
rt web
```

Avvia l'API, un worker per i job e la web app, e apre il browser già autenticato su
`http://127.0.0.1:8765`. La web è l'interfaccia di RT: importi l'audio, segui la pipeline in
tempo reale, approvi la scaletta, fai la review accanto al testo con l'audio, leggi il documento
con i timecode, fai il recall anche a voce, aggiungi immagini e configuri provider, modelli e
notifiche Telegram. Al primo avvio una configurazione guidata chiede provider, modelli e
Telegram. Nel terminale restano i comandi (`rt run`, `rt review`, `rt status`...): quando serve
una decisione (scaletta, issue) indicano di prenderla nella web. `install.sh` e `rt -u` installano la web app compilata dalla
release. Dettagli in [Web app di RT](docs/WEB.md).

### 2. Esecuzione End-to-End di una Lezione

```bash
./bin/rt run "percorso/cartella_lezione"
```

Per testare offline senza consumare crediti API:
```bash
./bin/rt run "percorso/cartella_lezione" --mock --auto-accept
```

### 2-bis. Coda dei job e worker (opzionale)

Il database di RT si crea e si aggiorna da solo al primo comando, senza scandire o importare
automaticamente le vecchie cartelle delle lezioni. Per convertirle in modo esplicito, usa
`rt db migrate-storage` dopo aver verificato il backup. Per far girare le elaborazioni lunghe
in un processo separato, avvia un worker e accoda la pipeline:

```bash
./bin/rt worker                          # esegue i job in coda (Ctrl+C per fermarlo)
./bin/rt run "cartella_lezione" --queue  # accoda e segue il progresso
./bin/rt jobs                            # elenca i job; 'rt jobs cancel ID' ne annulla uno
./bin/rt jobs close ID                   # chiude un job in attesa delle issue: le valuti dopo in Revisione
```

Senza `--queue`, `rt run` lavora in processo come sempre.

### 2-ter. Dove finiscono le lezioni

Le nuove lezioni non creano più una cartella di lavoro: testi e metadati stanno nel database
di RT e audio e immagini originali nella cartella `media/` accanto a `rt.db`. Il Markdown
finale (e, se servono, tutti gli altri dati) si scarica quando serve:

```bash
./bin/rt export "[2026-09-05] BIOCHIMICA - Lipidi" -o ~/Desktop   # Markdown finale con immagini
./bin/rt export "[2026-09-05] BIOCHIMICA - Lipidi" --all --zip    # tutti i dati in uno zip
./bin/rt import "[2026-09-05] BIOCHIMICA - Lipidi.zip"            # reimporta uno zip completo come nuova lezione
./bin/rt delete "[2026-09-05] BIOCHIMICA - Lipidi"                # elimina la lezione (chiede conferma, --yes per saltarla)
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
./bin/rt validate-phase "cartella_lezione" outline  # Segna valida una fase STALE senza rieseguirla
./bin/rt relevance "cartella_lezione" --all         # Riassegna le etichette JEV a tutte le unità
./bin/rt review "cartella_lezione"            # Revisione scientifica e delle ambiguità ASR
./bin/rt review "cartella_lezione" --unit 1.2 # Rivede solo un'unità (ripetibile)
./bin/rt build "cartella_lezione"             # Genera i documenti Markdown definitivi
./bin/rt status "cartella_lezione"            # Mostra lo stato di avanzamento
```

### 4. Notifiche su Telegram (opzionale)

RT può scriverti nella chat personale di Telegram quando una lezione è pronta, quando la
scaletta o le issue aspettano una tua decisione e quando una lavorazione non riesce. Non c'è un
bot sempre acceso: RT manda solo messaggi. Si configura nella web (Impostazioni › Telegram):
crei un bot con @BotFather, incolli il token, scrivi `/start` al bot e premi «Collega la chat».

**Dalle versioni precedenti:** il bot con comandi, topic e recall in chat non c'è più.
`rt service install` (lo esegue anche l'aggiornamento) toglie il vecchio servizio `bot` e il
LaunchAgent `com.rt.telegram-daemon` della 3.x; `rt doctor` li segnala se sono ancora presenti.

---

## 📚 Documentazione Dettagliata

- [Guida alla Configurazione (CONFIGURATION_REFERENCE.md)](docs/CONFIGURATION_REFERENCE.md)
- [Architettura del Sistema (ARCHITECTURE.md)](docs/ARCHITECTURE.md)
- [Workflow e Ciclo di Vita (WORKFLOW.md)](docs/WORKFLOW.md)
- [Modelli Dati e Contratti JSON (SCHEMAS.md)](docs/SCHEMAS.md)
- [Guida allo Sviluppo e Test Suite (DEVELOPMENT.md)](https://github.com/atturk/rt/blob/main/docs/DEVELOPMENT.md)
- [Motori di Trascrizione Alternativi (ALTERNATIVE_TRANSCRIPTION.md)](docs/ALTERNATIVE_TRANSCRIPTION.md)
- [Self-hosting: servizi, backup, Docker (SELF_HOSTING.md)](docs/SELF_HOSTING.md)


---

## 🧪 Esecuzione dei Test

La suite di test comprende unit test, test di validazione timestamp, test del critic scientifico, test del decision ledger e regressione su una lezione reale di biochimica:

```bash
python3 -m pytest tests/
```

## Sviluppo e distribuzione

La radice del repository `rt/` contiene il pacchetto Python omonimo `rt/`: non sono due copie del progetto.
Configurazione personale, segreti, database e stato Telegram stanno nella cartella dati (`~/.rt`), fuori dal checkout.
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
La trascrizione ha tre motori, da scegliere in Impostazioni › Lavorazione:

- **macparakeet** (`macparakeet-cli`): consigliato sul Mac, usa il Neural Engine. Solo macOS.
- **Parakeet ONNX**: lo stesso modello Parakeet v3 eseguito sulla CPU con onnx-asr, su Windows,
  Linux e macOS (seconda scelta sul Mac). Il modello, circa 700 MB, si scarica in
  `<cartella dati>/models/` alla prima trascrizione e poi funziona senza internet.
- **Server OpenAI-compatible**: un tuo server di trascrizione
  ([ALTERNATIVE_TRANSCRIPTION.md](docs/ALTERNATIVE_TRANSCRIPTION.md)).

ffmpeg si usa quello installato, altrimenti quello incluso nel pacchetto `imageio-ffmpeg`.

Per contribuire: [sviluppo](https://github.com/atturk/rt/blob/main/docs/DEVELOPMENT.md), [gestione file e release](https://github.com/atturk/rt/blob/main/docs/MAINTENANCE.md),
[valutazione delle interfacce](https://github.com/atturk/rt/blob/main/docs/INTERFACE_DIRECTION.md) (documenti disponibili nel repository).
