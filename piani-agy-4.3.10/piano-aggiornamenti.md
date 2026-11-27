# Piano agy: aggiornamenti dentro «Info e aggiornamenti» (4.3.10b2)

Branch: `agy/4.3.10-aggiornamenti` (da `claude/rt-4.3.10-beta`). Solo codice e test automatici: niente prove manuali.
Richiesta di Attilio (27/11): via i popup di download e «Installa e riavvia»; tutto avviene in
Impostazioni › Info e aggiornamenti, con avvisi solo come pallino sull'ingranaggio e sulla voce della sezione.

File: `frontend/src/components/settings/update.tsx`, `useAppUpdate.ts`, `UpdatePopup.tsx` (da togliere),
`frontend/src/components/Layout.tsx` (rail + barra telefono), `frontend/src/routes/settings.tsx` (voce di menu),
`frontend/src/routes/index.tsx` (route `app/aggiornamento`), `rt/window.py` (`apri_aggiornamento`, voce di menu),
`rt/core/app_update.py`, `rt/api/routers/system.py` (o dove sta `/system/update`), test relativi.

## 1. Niente popup

- Togliere `useUpdatePopup()` dal Layout e il componente `UpdatePopup` con la route `app/aggiornamento`.
- `DesktopApi.apri_aggiornamento` e la voce di menu dell'app «Controlla aggiornamenti…» non aprono più una finestra:
  portano la finestra principale su `/impostazioni/info-aggiornamenti#aggiornamenti` (stesso meccanismo degli
  altri link interni; `window.load_url` o evaluate_js con navigate).
- Tenere il metodo `apri_aggiornamento` (compatibilità) ma con il nuovo comportamento.

## 2. Pallino di avviso (solo dentro l'app, nessuna notifica di sistema)

- Nuovo hook `useUpdateNotice()` (in `useAppUpdate.ts`): legge `GET /system/update` (stessa query, polling 3 s solo
  nelle fasi busy, altrimenti nessun polling oltre al refetch esistente) e calcola `notice: 'available' | 'ready' | 'error' | null`:
  - `available`: c'è una versione nuova e l'utente non l'ha ancora vista;
  - `ready`: il download è finito (fase `ready` / `data.ready`) e non è ancora stato visto;
  - `error`: il download è fallito (fase `error`) e non è ancora stato visto.
- «Visto» = preferenza server `update.seen` (usePreference, vale su tutti i dispositivi) con valore
  `"<versione>:<stato>"`; si scrive quando l'utente apre la sezione Info e aggiornamenti mentre c'è quell'avviso.
- Pallino (stesso stile del badge dei Job, colore primario, `aria-label="Aggiornamento disponibile"` / «Aggiornamento
  pronto» / «Aggiornamento non riuscito») su: icona Impostazioni nella rail e nella barra del telefono; voce
  «Info e aggiornamenti» nel menu delle Impostazioni.

## 3. Download nella sezione

- «Scarica (197,5 MB)» avvia il download; al posto del testo «Scarico… (x%)» una barra `<progress>` determinata
  (valore = percentuale, `max-w-sm`, colore primario) con sotto, piccolo e in `text-meta text-muted-foreground`:
  «Download avviato: puoi continuare a usare RT. Quando finisce, o se qualcosa va storto, lo vedi qui e sull'icona
  delle Impostazioni.» Accanto alla percentuale i MB scaricati su totali.
- Il download continua lato server anche uscendo dalla pagina (già così: thread in `start_download`).
- Fine download: fase `ready` → pallino (`ready`). Errore → pallino (`error`) e nella sezione l'errore come oggi.
- **Download riprendibile**: oggi un'interruzione cancella il `.part` e «riparte da capo». Tenere il `.part`, al
  nuovo «Scarica» ripartire con header `Range: bytes=<size>-` (se il server risponde 206 si continua, se 200 si
  riparte da zero), con SHA256 calcolato rileggendo il `.part` esistente prima di continuare. Il `.part` si
  scarta se la versione cambia. Messaggio di errore: «… Riprova: il download riprende da dove si era fermato.»
  Riusare se possibile l'helper di download riprendibile già scritto per Parakeet ONNX (`rt/core/onnx_stt.py`).

## 4. «Installa e riavvia» senza barra vuota e senza attesa a finestra aperta

Oggi (`start_install` → `install` → `install_macos`) con la finestra aperta RT fa: backup pre-aggiornamento,
rilettura SHA256 del .dmg, `hdiutil attach`, `ditto` di RT.app (centinaia di MB), poi uno script chiude la finestra,
scambia le app e riapre. Quindi l'utente vede una barra che non si riempie mai per decine di secondi.

Misura sul Pro (4.3.9.1, 26/11): clic 10:05:39 → montaggio 10:05:42 → copia finita 10:05:48 → solo alle 10:05:59
la finestra si chiude. Gli 11 s dopo la copia sono `xattr -dr com.apple.quarantine` ricorsivo su tutta RT.app:
usare `ditto --noqtn` (non copia la quarantena) e togliere il passaggio `xattr -dr`.

Nuovo comportamento (macOS):
1. In-app restano solo i passi veloci: controllo SHA256 contro ready.json e backup pre-aggiornamento (già piccolo).
2. Poi RT lancia subito un helper staccato (lo script sh di oggi esteso: `hdiutil attach` → `ditto --noqtn` in
   `RT.app.update` → `hdiutil detach` → scambio → `open RT.app --args --after-update`),
   con log in `updates/install.log` come oggi, e **chiude subito la finestra** (stessa via di `window.pid`).
3. Mentre l'helper lavora scrive `updates/installing.json` con il suo PID; se l'utente riapre RT in quel momento,
   `rt/desktop.py` vede il PID vivo e mostra l'avviso nativo «RT si sta aggiornando: si riapre da solo tra poco.»
   e esce (non avvia una seconda finestra con l'app vecchia). Se il PID non è vivo il file si ignora e si cancella.
4. Se l'helper fallisce (mount/copia), riapre la RT vecchia con `--update-failed` e l'errore finisce in
   `updates/last_error.txt`; al riavvio la sezione lo mostra come fase `error` (pallino `error`).
5. Nella sezione, al clic: niente barra; solo il testo «Riavvio in corso…» (role=status) e il pulsante disabilitato.
6. Windows: invariato (l'installer silenzioso chiude già l'app), ma anche lì niente barra: solo «Riavvio in corso…».

## Test

- vitest: sezione con download in corso (barra con valore e testo), ready/error con pallino, «visto» che spegne il
  pallino, nessuna `<progress>` indeterminata durante l'installazione, nessuna chiamata a `apri_aggiornamento` dal Layout.
- pytest: download ripreso con 206 (SHA corretto sull'intero file), 200 che riparte da zero, `.part` scartato al
  cambio versione; `install_macos` non chiama più `hdiutil`/`ditto` in-process ma passa i percorsi allo script;
  `installing.json` con PID vivo/morto in `desktop.py`; script sh che contiene attach/ditto/detach/swap/open
  (controllo testuale, niente esecuzione).
- Aggiornare `docs/openapi.json` e `schema.d.ts` se cambia l'API.
