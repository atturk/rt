# Piano di implementazione: backup con avanzamento e «Salva una copia» (per Codex)

Repository: `github.com/atturk/rt`. Base: il ramo beta `claude/rt-4.3.1-beta` (RT 4.3.1b1).
Destinazione: la beta 4.3.1b2. Il piano è autosufficiente.

## Richiesta di Attilio (18/10/2026)

Un backup è più sicuro se ne esistono più copie in posti diversi. Il backup continua a salvarsi
nella cartella di RT come oggi, ma poi l'utente deve poter salvarne una copia altrove:

1. Durante il backup si vede l'avanzamento, con un popup e una barra.
2. A backup finito compare il riepilogo di oggi, con due pulsanti: **Chiudi** e **Salva una
   copia…**.
3. **Salva una copia…** apre la normale finestra di salvataggio del sistema (Mac o Windows) e
   salva lì una copia del backup.

## Regole di lavoro

- Branch `feature/backup-copia` da `claude/rt-4.3.1-beta`, con una PR verso quel ramo. Non unirla:
  la rivede Claude e poi decide Attilio.
- Non cambiare `VERSION` e non toccare `CHANGELOG.md`: le righe di changelog vanno nella
  descrizione della PR.
- Testi, commenti e docstring in italiano, nello stile del codice esistente (frasi brevi, niente
  gergo).
- Attilio non ha un PC Windows: Windows si verifica solo in CI (`.github/workflows/app.yml`,
  `tests.yml`). Valgono le insidie già note del repo:
  - testo scritto con `newline="\n"`;
  - `os.replace` con tentativi ripetuti;
  - niente lock dentro cartelle che si spostano;
  - nel runner `bash` è uno stub WSL.
- Prima del push devono passare `pytest tests/test_backup.py tests/test_desktop_window.py` e
  `cd frontend && npm run lint && npm run typecheck && npx vitest run`.

## Come è fatto oggi (file da leggere)

| File | Cosa contiene |
|---|---|
| `rt/window.py` | Finestra pywebview 6.2.1. `_menu` contiene `MenuAction("Backup…", lambda: _maintenance(window, "backup"))`. `_maintenance` lancia `bin/rt backup` come sottoprocesso (`_command`, `subprocess.run` con `capture_output`), aspetta la fine, cerca la riga `✅ Backup completo: <percorso>`, mostra tutto l'output con `alert()` (`_notice`) e apre la cartella dei backup. `webview.create_window(...)` oggi non passa `js_api`. |
| `rt/cli_system.py` | `cmd_backup`: chiama `backup_service.create_backup(args.dest, allow_missing=...)` e stampa `✅ Backup completo: …` e gli avvisi. |
| `rt/services/backup_service.py` | `create_backup(dest, say, allow_missing)` in tre fasi: database (`sqlite_copy` o `pg_dump`), media incrementali per hash, configurazione. `say` riceve le righe del riepilogo. **I media non stanno dentro la cartella `rt-backup-<data>`**: vanno in `<dest>/media-store/<sha[:2]>/<sha>` e sono condivisi tra i backup. `restore_backup` / `resolve_snapshot` accettano una cartella `rt-backup-*` oppure la cartella dei backup, e cercano `media-store/` accanto alla cartella dello snapshot. `master_key_warning()` dà l'avviso della chiave master. |
| `tests/test_backup.py`, `tests/test_desktop_window.py` | Test esistenti da estendere. |
| `frontend/src/components/shell/` | Il guscio della SPA, dove montare un componente globale. |
| `frontend/src/components/ui/modal.tsx`, `dialog.tsx` | Le finestre modali da riusare per lo stile. |

## Decisione chiave: la copia è un unico file .zip autosufficiente

Copiare solo la cartella `rt-backup-<data>` **non basta**, perché i media stanno in
`media-store/`, fuori da quella cartella, e senza di loro il ripristino si rifiuta («Backup
incompleto»). La finestra di salvataggio, inoltre, sceglie un file e non una cartella.

Per questo «Salva una copia…» produce un unico file `rt-backup-<data>.zip` che contiene:

```
rt-backup-<data>/            ← la cartella dello snapshot così com'è (manifest, rt.db, config, env, …)
media-store/<aa>/<sha>       ← solo i media elencati nel manifest di quello snapshot
```

- Usa `zipfile.ZIP_STORED`, senza compressione: l'audio è già compresso e così è più veloce.
  Abilita `allowZip64`, perché i backup con molto audio superano i 4 GB.
- Scrivi su `<scelta>.part` e alla fine fai `os.replace`, così un file a metà non sembra un
  backup buono. Se c'è un errore, cancella il `.part`.
- **Ripristino dallo zip.** `resolve_snapshot` / `restore_backup` (e quindi `rt restore`)
  devono accettare anche un `.zip`. Si estrae in una cartella temporanea dentro
  `<dati>/backups/`, sullo stesso disco, per avere lo spazio e un `os.replace` affidabile, poi
  si procede come per una cartella e alla fine si cancella la cartella temporanea. Rifiuta i
  percorsi non sicuri dentro lo zip (assoluti o con `..`) con un `BackupError`.
- Aggiorna `help` di `rt restore` e il messaggio «Backup incompleto» per dire che vale anche lo
  zip salvato con «Salva una copia».

## Backend

1. **Avanzamento in `create_backup`.** Aggiungi un parametro opzionale `progress:
   Callable[[str, int, int], None] | None`, chiamato con `(fase, fatto, totale)`:
   - `("database", 0, 1)` all'inizio e `("database", 1, 1)` alla fine;
   - `("media", i, n)` dopo ogni file, dove `n` è il numero di media da considerare. L'hash e la
     copia sono la parte lenta, quindi la barra deve muoversi qui;
   - `("config", 1, 1)` alla fine.
   Il valore predefinito non stampa nulla, così la CLI e i test di oggi non cambiano.
2. **Nuova funzione `export_backup(snapshot, target_zip, progress=None) -> str`** in
   `backup_service.py`. Crea lo zip descritto sopra e chiama `progress("copia", byte_scritti,
   byte_totali)`. Restituisce il percorso finale. Se lo snapshot ha media assenti dal
   `media-store`, alza `BackupError` con lo stesso stile di `restore_backup`.
3. **CLI per la finestra.**
   - `rt backup --progress-json` stampa una riga JSON per ogni evento:
     `{"fase": "media", "fatto": 12, "totale": 119}`.
   - Alla fine stampa `{"fine": true, "percorso": "...", "riepilogo": ["🗄 Database salvato
     (rt.db).", ...], "avviso_chiave": "..."}`. Il riepilogo sono le righe `say` più gli avvisi
     di oggi (media mancanti, lezioni ancora in cartella).
   - In caso di errore stampa `{"errore": "..."}` ed esce con codice diverso da 0.
   - Ogni riga si scrive con `flush=True`.
   - Senza il flag l'output resta identico a oggi.
   - Nuovo comando `rt backup --export <snapshot> --to <file.zip> --progress-json`, con eventi
     `{"fase": "copia", ...}` e la riga finale `{"fine": true, "percorso": "..."}`.

## Finestra (`rt/window.py`)

1. **Sottoprocesso con lettura in tempo reale.** Per il backup sostituisci `subprocess.run` con
   `subprocess.Popen(..., stdout=PIPE, text=True, encoding="utf-8", bufsize=1)`, mantenendo
   `creationflags=0x08000000` su Windows ed `env` come in `_command`, e leggi riga per riga. La
   diagnostica (`doctor`) resta com'è.
2. **Ponte con la pagina.** Per ogni evento chiama
   `window.evaluate_js(f"window.__rtBackup && window.__rtBackup({json.dumps(evento)})")`.
   - All'inizio manda `{"inizio": true, "tipo": "backup"}`.
   - Limita la frequenza a circa 10 aggiornamenti al secondo, ma manda sempre l'ultimo.
   - Se la pagina non ha `__rtBackup`, per esempio perché non è ancora caricata, alla fine usa
     `_notice` come oggi, così il riepilogo non si perde.
   - Due backup insieme non partono: un secondo clic su «Backup…» mentre il primo è in corso
     manda solo `{"inizio": true}` per riaprire il popup.
   - Non aprire più la cartella dei backup alla fine: lo sostituisce il popup.
3. **`js_api`.** Passa a `create_window` un oggetto `js_api` con un solo metodo pubblico,
   `salva_copia_backup(self, percorso_snapshot)`, che fa questo:
   - controlla che `percorso_snapshot` sia una cartella `rt-backup-*` dentro
     `backup_service.default_dest()` (dopo `realpath`) e non un percorso qualsiasi;
   - apre `window.create_file_dialog(webview.SAVE_DIALOG, save_filename=
     "rt-backup-<data>.zip", file_types=("Archivio zip (*.zip)",))` sul thread giusto, come
     richiede pywebview;
   - se l'utente annulla restituisce `{"annullato": true}`;
   - altrimenti lancia in un thread `rt backup --export … --to … --progress-json` con lo
     stesso ponte, con `"tipo": "copia"`, e restituisce subito `{"avviato": true}`;
   - aggiunge `.zip` al nome se manca.
   Tutti gli altri metodi dell'oggetto devono essere privati (con `_`), perché pywebview espone
   alla pagina solo i metodi pubblici.
4. Test in `tests/test_desktop_window.py`, con il sottoprocesso e `window` finti:
   - gli eventi arrivano alla pagina nell'ordine giusto;
   - in caso di errore arriva `{"errore": …}`;
   - senza `__rtBackup` si usa il ripiego `_notice`;
   - `salva_copia_backup` rifiuta un percorso fuori da `default_dest()`;
   - l'annullamento della finestra di salvataggio non avvia nulla.

## Pagina (frontend)

1. Nuovo componente `BackupDialog` (per esempio `frontend/src/components/shell/BackupDialog.tsx`),
   montato una volta nel guscio dell'app. Registra `window.__rtBackup = (evento) => …` al mount
   e lo toglie all'unmount, con il tipo dichiarato in un `.d.ts`.
2. Stati del popup, nello stile delle modali esistenti:
   - **In corso:**
     - titolo «Backup in corso…» oppure «Salvo una copia…»;
     - una riga con la fase: «Database», «Media 12 di 119» o «Configurazione», oppure
       «Copia 1,2 GB di 3,4 GB»;
     - una barra di avanzamento con percentuale. Database e configurazione valgono poco, i media
       quasi tutto: per esempio 5% database, 90% media e 5% configurazione;
     - nessun pulsante di chiusura mentre lavora. Esc non chiude.
   - **Finito (backup):**
     - il riepilogo di oggi, cioè le righe di `riepilogo` così come arrivano, con il percorso in
       `font-mono` che va a capo;
     - l'avviso sulla chiave master in un riquadro `Alert` separato, non mescolato alle righe;
     - una riga breve: «Per sicurezza tieni anche una copia su un altro disco o nel cloud»;
     - pulsanti **Chiudi** e **Salva una copia…** (primario).
   - **Salva una copia…** chiama `window.pywebview.api.salva_copia_backup(percorso)`. Se torna
     `annullato`, il popup resta sul riepilogo. Se torna `avviato`, il popup passa a «Salvo una
     copia…» con la sua barra.
   - **Finito (copia):** «Copia salvata in `<percorso>`» con il pulsante **Chiudi**. Lo zip vale
     anche da solo per il ripristino: «Si ripristina con rt restore `<file.zip>`», in piccolo.
   - **Errore:** il messaggio in un `Alert` con tono `danger` e il pulsante **Chiudi**.
3. Fuori dall'app, cioè nel browser, `window.pywebview` non esiste e il popup non compare mai,
   perché solo il menu dell'app lancia il backup. Non serve altro.
4. Test vitest per `BackupDialog`:
   - gli eventi simulati su `window.__rtBackup` muovono la barra;
   - la fine mostra il riepilogo e i due pulsanti;
   - «Salva una copia…» chiama l'API finta;
   - l'annullamento lascia il riepilogo;
   - un errore mostra l'avviso.

## Test del backend

In `tests/test_backup.py`:

- `progress` riceve le fasi in ordine, con l'ultimo `media` uguale a `n/n`;
- `export_backup` crea uno zip con lo snapshot e solo i media del suo manifest;
- `rt restore` su quello zip, in un'altra cartella dati, ripristina database e media;
- uno zip con `../` viene rifiutato;
- un errore a metà non lascia né `.zip` né `.part`;
- `--progress-json` stampa righe JSON valide e chiude con `fine`.

## Cosa controllerà la revisione

- Lo zip si ripristina davvero da solo, senza la cartella dei backup accanto.
- `js_api` espone un solo metodo e accetta solo snapshot dentro la cartella dei backup di RT.
- La CLI senza flag e `rt restore` su una cartella funzionano come prima.
- Windows: niente console che compare (`creationflags`), percorsi con spazi e accenti,
  `os.replace` affidabile, e CI `app.yml` verde.
