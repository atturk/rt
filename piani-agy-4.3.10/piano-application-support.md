# Piano 4.3.10b4: dati in Application Support (Mac) e %LOCALAPPDATA% (Windows)

Base: claude/rt-4.3.10-beta (2d590fb9, = b3). Indagine: https://claude.ai/artifact/TzaD34f9iE6oVNdCKnbjnE
Decisione di Attilio (2026-11-27): spostamento dati in una beta separata dopo la b3.

## Dove
- macOS: ~/Library/Application Support/RT
- Windows: %LOCALAPPDATA%\RT (non Roaming: modelli da 700 MB)
- Linux, Docker, install.sh: invariato (~/.rt o RT_DATA_DIR).
- Modelli e browser restano dentro la cartella dati (NON in Caches: macOS può svuotarla).

## 1. rt/core/paths.py
- Nuova `platform_data_dir()`. `default_data_dir()` = RT_DATA_DIR > cartella nuova se inizializzata > ~/.rt se attiva (marker) > cartella nuova per le installazioni nuove dell'app (bundle.kind() non None; da terminale resta ~/.rt).
- `active_data_dir()` continua a rispettare `"location"` del marker in ~/.rt.

## 2. Migrazione (in data_service.post_update, che già ferma i servizi; solo app Mac/Windows)
Condizioni: ~/.rt attiva, nessuna RT_DATA_DIR, cartella nuova assente, marker senza "location" esterna (le 3.x con dati su disco esterno non si toccano), nessun job in esecuzione (jobs running con lease vivo). Altrimenti si rimanda al prossimo avvio con una riga nel log.
1. Copia di sicurezza di rt.db (solo il file) in backups/prima-dello-spostamento-<data>.db.
2. `os.rename(~/.rt, nuova)`: stesso volume, atomico. Se fallisce (EXDEV, permessi, file aperti su Windows) NON si copia: si annulla e si riprova al prossimo avvio, con messaggio nel log.
3. Ricreare ~/.rt con SOLO rt-data.json = {"layout":1, "location": "<nuova>", "moved_at": ...}: le versioni vecchie (downgrade a una beta precedente) trovano i dati.
4. Riscrivere i percorsi assoluti che iniziano con il vecchio prefisso, in UNA transazione dopo il rename:
   - DB: lessons.path e tutte le colonne path / lesson_path / *_path (elencarle ispezionando i modelli SQLAlchemy, non a mano). Le lezioni a cartella in ~/.rt/lessons hanno path assoluti.
   - config/*.yaml e .env della cartella dati (lessons_root e qualunque valore col vecchio prefisso).
   - components.json: azzerare stati "downloading".
5. Servizi: launchd .plist (RT_DATA_DIR e log col percorso vecchio) riscritti con service_manager install; su Windows controllare collegamenti e avvio automatico.
6. Se un passo dopo il rename fallisce: rename all'indietro, ripristino del marker originale e del DB dalla copia, poi messaggio.

## 3. Da aggiornare
- Testi UI, guida (docs/guida/problemi.md ecc.), help CLI, OpenAPI: "~/.rt" → "la cartella dati di RT" o il percorso reale (grep "~/.rt", circa 30 punti).
- "Mostra nel Finder" di cartella dati e log; rt doctor mostra il percorso nuovo.
- bundle.apply_env (PLAYWRIGHT_BROWSERS_PATH) segue data_dir: verificare dopo la migrazione nello stesso processo.
- scripts/setup_mcp.sh e docs/MCP.md.
- desktop.log scritto prima della migrazione: dopo lo spostamento si continua nel percorso nuovo.

## 4. Test (con HOME / RT_DATA_DIR temporanee: MAI la ~/.rt vera)
- Installazione nuova dell'app → cartella nuova, nessuna ~/.rt.
- Migrazione da ~/.rt con DB, lezioni a cartella in ~/.rt/lessons, config con lessons_root, plist → tutto spostato, percorsi riscritti, marker con location, servizi ripuntati.
- Job in corso → migrazione rimandata.
- Rename che fallisce → nulla cambia.
- Errore dopo il rename → rollback completo.
- Downgrade simulato: la logica vecchia di active_data_dir trova i dati via location.
- RT_DATA_DIR esplicita → nessuna migrazione. 3.x con "location" su disco esterno → nessuna migrazione.

## Regole
- agy scrive solo codice; verifiche e Playwright le fa Claude.
- Test e script non devono mai toccare la ~/.rt vera.
- Dopo la b4 aggiornare le cartelle approvate per i log (oggi /Users/attilioturco/.rt/logs) sul Pro e sull'Air.
