# Piano 1 · Esporta tutto e Importa: portare la collezione su un altro PC

Agente: **Codex** (da confermare all'avvio della b2). Richiesta di Attilio (21/10/2026): esportare
tutto (lezioni, calendario, studio, archivio, impostazioni) per riprendere da un altro PC o salvare
lo stato dell'intera collezione. Decisione di Attilio: **le chiavi API non escono mai dal PC**; sul
PC nuovo si reinseriscono in Impostazioni.

## Cosa c'è già (non rifarlo)

- `rt/services/backup_service.py`: `create_backup` (DB con lezioni, calendario, studio, preferenze;
  media incrementali in `media-store/`; archivio delle fonti; `config/`; `.env`; stato del bot) e
  `export_backup(snapshot, zip)` che crea uno zip autosufficiente (`ZIP_STORED`, zip64, `.part` +
  `os.replace`). `restore_backup(source)` accetta anche lo zip.
- `rt/window.py`: menu "Backup…" → `_stream_backup` (sottoprocesso `bin/rt backup`, eventi JSON con
  avanzamento verso `window.__rtBackup`), `Api.salva_copia_backup` con la finestra di salvataggio.
- `frontend/src/components/shell/BackupDialog.tsx`: popup con avanzamento e riepilogo.
- Il ripristino oggi è **solo da terminale** (`rt restore`), con i servizi fermi.

## Cosa manca e cosa fare

### 1. "Esporta tutto…"

- Voce nel menu dell'app, sotto "Backup…". Un solo flusso: finestra di salvataggio (nome proposto
  `RT-<data>.zip`) → `create_backup` nella cartella dei backup come oggi → `export_backup` nel file
  scelto, **senza segreti** (punto 3). Avanzamento e riepilogo nel `BackupDialog` esistente (nuovo
  `tipo: "esporta"`), con "Mostra nel Finder/Esplora" alla fine.
- Lezioni ancora "cartella" (`_folder_lessons`, storage != `db`): oggi il backup le salta e avvisa.
  Prima dell'export, se ce ne sono, conferma "N lezioni sono ancora in una cartella: le sposto nel
  database e continuo?" e usa `rt/storage/migrate.py` `migrate_lesson` (verifica per hash, la cartella
  originale va nella cartella di backup, mai cancellata). Se l'utente annulla, l'export non parte.

### 2. "Importa…"

- Voce nel menu dell'app. Finestra di apertura (filtro `.zip`) → controllo rapido dello zip senza
  estrarlo (c'è un `rt-backup-*/manifest.json`, formato non più recente di `FORMAT`, versione di RT
  da cui viene) → conferma: "Importare la collezione del <data>? Quella attuale viene messa da parte."
- Il ripristino ha bisogno dei servizi fermi. Il flusso nella finestra:
  1. ferma API e worker dell'app (`desktop.stop_background` o equivalente per Mac/Windows);
  2. lancia `bin/rt restore <zip> --yes --json` come sottoprocesso con eventi di avanzamento nello
     stesso formato del backup (aggiungi `--yes` e `--json` a `cmd_restore`);
  3. a fine ripristino riavvia RT (stesso meccanismo di "Esci da RT" + riapertura dell'app; se
     riaprire da sé non è affidabile su una piattaforma, avviso "Riapri RT" e uscita).
  Il popup di avanzamento è il `BackupDialog` (`tipo: "importa"`); siccome il server si ferma, gli
  eventi devono arrivare alla pagina anche senza API (già oggi passano da `evaluate_js`).
- I dati sostituiti restano in `<dati>/backups/prima-del-ripristino-<data>` come oggi; il riepilogo
  lo dice.

### 3. Segreti: mai nell'export, mai sovrascritti dall'import

- `export_backup` riceve `segreti=False` (predefinito per "Esporta tutto"): nello zip non vanno
  `config/secrets.enc` né le righe di `env` che contengono segreti (nomi che finiscono in `_KEY`,
  `_TOKEN`, `_SECRET`, `_PASSWORD`, più `RT_MASTER_KEY`). Il manifest dello zip segna
  `"segreti": false`.
- `restore_backup` con un backup `"segreti": false`: **non** sposta né sostituisce `secrets.enc`
  attuale e mantiene le righe segrete dell'`.env` attuale, unendo il resto.
- Dopo l'import, se manca la chiave del provider in uso, RT mostra l'avviso che già compare quando la
  chiave non è configurata (controlla `desktop.ensure_secrets` / la pagina Impostazioni), senza testi
  nuovi.
- Il backup normale (menu "Backup…", `rt backup`) resta com'è, con i segreti cifrati.

### 4. Percorsi del vecchio PC

La configurazione viene da un altro PC, magari da Mac a Windows. Dopo il ripristino, ogni percorso
della configurazione che non esiste su questo PC (`lessons_root`, `telegram.state_dir`, cartelle dei
backup, ecc.) torna al valore predefinito; il riepilogo elenca quelli cambiati in una riga.
`database_url` SQLite punta sempre al DB della cartella dati di questo PC.

### 5. Altro

- `rt export <file.zip>` e `rt import <file.zip>` da terminale, sottili sopra le stesse funzioni.
- Nessuna voce nuova nella SPA: tutto dal menu dell'app (nel browser l'export si fa con
  `rt export`).

## Test

- `tests/test_backup.py`:
  - export senza segreti: nello zip niente `secrets.enc`, nessuna riga segreta in `env`, manifest
    `segreti: false`; tutto il resto presente (DB, media, archivio, config);
  - import di quello zip su una cartella dati con segreti propri: `secrets.enc` e righe segrete
    dell'`.env` restano quelli del PC, il DB è quello importato, media e archivio presenti;
  - percorsi inesistenti della config tornano al predefinito;
  - lezioni cartella: con conferma vengono migrate e finiscono nello zip; senza conferma niente zip;
  - zip non valido o di formato più nuovo: errore chiaro, nulla modificato.
- `tests/test_desktop_window.py`: le due voci di menu; l'import ferma i servizi prima del restore e
  riavvia dopo (con mock).
- vitest `BackupDialog`: tipi `esporta` e `importa` mostrano avanzamento e riepilogo.
- CI Windows (`app.yml`, `tests.yml`): l'import su Windows deve chiudere il DB prima di spostarlo
  (`reset_database_cache`, già fatto in `restore_backup`).
