# Self-hosting di RT

RT gira sul tuo Mac: nessun servizio esterno oltre ai provider LLM che scegli. Questa pagina
spiega dove stanno i dati, come girano i servizi in background, come fare backup e ripristino,
come aggiornare e disinstallare, e come usare Docker quando serve.

## Installazione

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/atturk/rt/main/bootstrap.sh)"
```

Il comando scarica l'ultima release in `./rt` ed esegue `install.sh`, che:

1. installa i prerequisiti con Homebrew (Python 3.11+, `ffmpeg`, `macparakeet-cli` e il modello
   Parakeet se li vuoi, `micro` e `mpv` per la CLI);
2. crea l'ambiente Python `.venv` e installa le dipendenze;
3. installa la web app già compilata della release (niente Node sul tuo Mac);
4. crea la cartella dati (vedi sotto), oppure ci sposta i dati di un'installazione 3.x;
5. crea l'archivio cifrato dei segreti (chiave master nel portachiavi di macOS);
6. crea o migra il database; se trova lezioni nel vecchio formato a cartelle le converte nel
   database e in `media/` dopo un backup (lo stesso di `rt db migrate-storage`);
7. installa i servizi in background (API e web app, worker, bot Telegram);
8. esegue `rt doctor` e apre il browser sulla configurazione guidata.

È idempotente: rilanciarlo (da dove c'è già `./rt`) riporta il codice alla release, reinstalla
dipendenze, web app e servizi, e lascia intatti dati, configurazione e lezioni.

Variabili utili (tutte facoltative):

| Variabile | Effetto |
|---|---|
| `RT_NONINTERACTIVE=1` | nessuna domanda, niente browser alla fine (script, CI) |
| `RT_INSTALL_PARAKEET=0` / `1` | salta o installa `macparakeet-cli` senza chiedere |
| `RT_INSTALL_EXTRAS=0` | salta `micro` e `mpv` |
| `RT_NO_SERVICES=1` | niente servizi in background: si usa `rt web` a mano |
| `RT_DATA_DIR=<cartella>` | cartella dati diversa da `~/.rt` |
| `RT_SPA_TARBALL=<file>` | web app da un pacchetto locale invece che dalla release |

## La cartella dati

Tutto ciò che è tuo sta in un posto solo, `~/.rt` (o `RT_DATA_DIR`):

```text
~/.rt/
  rt-data.json      segna la cartella come attiva
  config/           general.yaml, file dei job, secrets.enc (chiavi API e token, cifrati)
  .env              variabili non segrete (RT_TELEGRAM_CHAT_ID)
  rt.db             database: lezioni, testi, decisioni, costi, job
  media/            audio e immagini originali delle lezioni
  .rt_telegram/     stato del bot
  logs/             log dei servizi (api.log, worker.log, bot.log)
  backups/          backup di default e copie di sicurezza delle migrazioni
```

La cartella del codice (`./rt`) contiene solo il programma: si può cancellare e reinstallare
senza perdere nulla. `rt data` mostra i percorsi in uso.

**Dalla 3.x.** Con la 3.x configurazione e `.env` stavano nella cartella del codice e il
database in `<cartella lezioni>/.rt`. `rt -u` (o il comando di installazione) li sposta:
configurazione, `.env` e stato del bot vengono copiati nella cartella dati e gli originali
rinominati (`config.migrato-<data>`), niente viene cancellato. Se il database e `media/` esistono
già in `<cartella lezioni>/.rt`, restano lì (magari su un disco esterno): quella diventa la
cartella dati e `~/.rt/rt-data.json` rimanda lì. La migrazione si rifiuta se API, worker o bot
sono attivi. Si può anche lanciare a mano: `rt data migrate --dry-run`, poi `rt data migrate`.

## Servizi in background (launchd)

Su macOS RT gira come tre LaunchAgent, che partono al login e ripartono se cadono:

| Servizio | Comando | Cosa fa |
|---|---|---|
| `api` | `rt api --service` | API e web app su `http://127.0.0.1:8765` (solo questo Mac) |
| `worker` | `rt worker` | esegue i job: pipeline, trascrizioni, recall, immagini |
| `bot` | `rt telegram-daemon --service` | bot Telegram; se non è configurato esce subito e resta fermo |

```bash
rt service status            # stato dei servizi e della web app
rt service install [nomi]    # scrive ~/Library/LaunchAgents/com.atturk.rt.<nome>.plist e avvia
rt service stop [nomi]       # ferma (ripartono al prossimo login o con start)
rt service start [nomi]
rt service restart [nomi]
rt service uninstall [nomi]
```

Con i servizi attivi `rt web` apre solo il browser con un link di accesso monouso. Il bot si
avvia e si ferma anche da Impostazioni > Telegram: con il servizio installato lo fa launchd.
Il token dell'API non finisce nei log: si entra con `rt web`, oppure `rt api --reset-token`
ne genera uno nuovo e lo mostra (poi `rt service restart api`).

Esempio del file generato per l'API (`rt service install api`):

```xml
<plist version="1.0"><dict>
  <key>Label</key><string>com.atturk.rt.api</string>
  <key>ProgramArguments</key><array>
    <string>/Users/tu/rt/.venv/bin/python3</string><string>/Users/tu/rt/bin/rt</string>
    <string>api</string><string>--service</string><string>--port</string><string>8765</string>
  </array>
  <key>EnvironmentVariables</key><dict><key>RT_DATA_DIR</key><string>/Users/tu/.rt</string></dict>
  <key>WorkingDirectory</key><string>/Users/tu/.rt</string>
  <key>StandardOutPath</key><string>/Users/tu/.rt/logs/api.log</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
</dict></plist>
```

Porta diversa: `RT_API_PORT=8800 rt service install api`.

## Backup e ripristino

Le lezioni vivono nel database (testi e metadati) e in `media/` (audio e immagini): il backup è
l'unica copia completa, non ci sono più cartelle lezione da copiare a mano.

```bash
rt backup --dest /Volumes/Disco/rt-backup    # default: ~/.rt/backups (meglio un disco esterno)
rt backup --dest /Volumes/Disco/rt-backup --list
rt restore /Volumes/Disco/rt-backup          # il più recente, o una cartella rt-backup-<data>
```

Ogni backup contiene una copia coerente del database (API di backup di SQLite, anche con RT in
funzione; `pg_dump` per PostgreSQL), la configurazione con `secrets.enc`, `.env` e lo stato del
bot. I media stanno in `media-store/`, uno per hash: ogni backup copia solo i file nuovi. Prima
di salvare, RT verifica che ogni media citato nel database esista (`--allow-missing` per salvare
comunque il resto); `rt doctor` fa lo stesso controllo.

**La chiave master non è nel backup.** Decifra `secrets.enc` e sta nel portachiavi di macOS (o
in `RT_MASTER_KEY`). Salvala a parte, per esempio in un password manager: `rt secrets show-key`
la mostra. Senza, dopo un ripristino su un altro Mac chiavi API e token vanno reinseriti.

Il ripristino si rifiuta se i servizi sono attivi (`rt service stop`), mette da parte database,
configurazione e `.env` attuali in `~/.rt/backups/prima-del-ripristino-<data>`, copia solo i
media mancanti e applica le migrazioni del database se il backup è di una versione precedente.

Le lezioni rimaste in cartella dalla 3.x non sono nel backup: `rt backup` le segnala e
`rt db migrate-storage` le porta nel database.

## Aggiornare, diagnosticare, disinstallare

- `rt -u` ferma i servizi, aggiorna codice, dipendenze e web app, poi con il codice nuovo
  migra la cartella dati se serve, aggiorna il database (migrazioni Alembic) e riavvia i
  servizi. Dalla 3.x installa anche i servizi e propone di cifrare le chiavi rimaste in `.env`.
  Con la versione già aggiornata ripara l'installazione.
- `rt doctor` controlla Python, `ffmpeg`, trascrizione, cartella dati, configurazione, database,
  media, chiave master, web app, servizi, porta e worker, e per ogni problema dice cosa fare.
  `rt doctor --json` per gli script; esce con 1 solo se c'è un errore.
- `rt uninstall` rimuove servizi, ambiente Python e web app e toglie RT dal PATH. Dati, lezioni
  e backup restano; `--purge-data` cancella anche la cartella dati (tranne `backups/`).

## Docker

Docker serve per far girare RT su un server Linux o per provarlo isolato. Sul Mac il default
resta nativo: in un container Linux `macparakeet` non gira.

Si usa da un clone del repository (l'archivio della release non contiene i file Docker):

```bash
git clone https://github.com/atturk/rt.git && cd rt
docker compose up -d                          # API + web app e worker, dati nel volume rt-data
docker compose exec api rt web --no-browser   # stampa il link di accesso monouso
docker compose --profile telegram up -d       # anche il bot
```

- L'immagine (`Dockerfile`, multi-stage) compila la web app con Node e poi usa solo Python.
- La cartella dati è `/data` (volume `rt-data`); la porta è pubblicata solo su `127.0.0.1`
  (`RT_PORT` per cambiarla sull'host).
- Il portachiavi non c'è: per i segreti cifrati passa `RT_MASTER_KEY` (in un file `.env`
  accanto a `docker-compose.yml`, non nel repository).
- **Trascrizione.** Un worker dichiara se sa trascrivere (`rt worker --stt`, oppure
  `RT_WORKER_STT`): `auto` vuol dire `macparakeet` su macOS, `custom` se hai configurato un
  motore compatibile (vedi [motori alternativi](ALTERNATIVE_TRANSCRIPTION.md)), nessuno
  altrimenti. I job che devono trascrivere audio (`ingest_audio`, pipeline da audio, vocali
  del recall) vanno solo ai worker che sanno farlo: senza, aspettano in coda un worker sul Mac
  collegato allo stesso database. Tutto il resto (rielaborazione, review, recall, immagini,
  lezioni già trascritte) gira nel container.
- **PostgreSQL** (facoltativo): `docker compose --profile postgres up -d` con
  `RT_DATABASE_URL=postgresql+psycopg://rt:<password>@postgres/rt` e `RT_POSTGRES_PASSWORD`.
  Senza, il database è SQLite in `/data/rt.db`.
- Backup: `docker compose exec api rt backup --dest /data/backups`, poi copia il volume o
  monta una cartella dell'host su `/data/backups`.

La CI prova lo stack con `scripts/docker_smoke.py`: `docker compose up`, accesso con il link
monouso, run mock completo di una lezione via API.
