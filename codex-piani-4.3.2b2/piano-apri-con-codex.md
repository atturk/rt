# Piano 3 · Aprire file con RT: icona nel Dock, "Apri con", doppio clic

## Cosa deve succedere

Nell'app (Mac e Windows), un audio, un PDF o un altro file che RT accetta può arrivare a RT:

- trascinandolo sull'icona di RT nel Dock (Mac);
- con "Apri con › RT" dal Finder o da Esplora file;
- trascinandolo sull'icona di RT nel Finder o sul collegamento sul desktop (Windows).

L'effetto è lo stesso del trascinamento sulla finestra: si apre Nuova lezione con quei file già
scelti (`openNewLesson({ initialFiles })` in `frontend/src/components/Layout.tsx`, chiamato oggi da
`GlobalFileDrop`).

- Se RT è chiuso, si apre e poi mostra il dialogo.
- Se è aperto, la finestra viene davanti con il dialogo.

RT **non** diventa l'app predefinita per nessun tipo di file: compare solo in "Apri con".

Estensioni: le stesse di `ACCEPTED_EXTENSIONS` in
`frontend/src/components/shell/globalFileDropUtils.ts`.

## Come passano i file

La pagina non può leggere un percorso locale, e il bridge di pywebview non va bene per file da
centinaia di MB. Il passaggio quindi avviene così:

1. Il processo della finestra riceve i percorsi (Apple Event o argomenti). Per ciascuno scrive
   `~/.rt/run/opened/<token>.json` con `{"path", "name", "size", "created"}`. Il token è
   `secrets.token_urlsafe(24)`, il file ha permessi `0600`.
2. Avvisa la pagina con `window.evaluate_js("window.rtOpenedFiles && window.rtOpenedFiles(<json>)")`,
   passando `[{token, name, size}]`.
3. La pagina scarica ogni file da un nuovo endpoint
   `GET /api/v1/system/opened-files/{token}`, ne fa un `File` (`new File([blob], name)`) e chiama
   `openNewLesson({ initialFiles })`.
4. L'endpoint, nel processo API, serve il file solo se:
   - il token esiste in `run/opened/`;
   - è più giovane di 10 minuti;
   - il percorso è un file regolare con estensione accettata.
   Dopo averlo servito cancella il `.json`. Usa `FileResponse` e l'autenticazione normale (`Actor`).
   Token sconosciuto o scaduto → 404.

Così un token vale una volta sola, e solo per un file che il sistema ha consegnato alla finestra.

## Pagina

- In `Layout.tsx`, un `useEffect` attivo solo con `isAppWindow()` registra
  `window.rtOpenedFiles = (items) => ...` e lo toglie allo smontaggio.
- Mentre scarica i file, mostra l'avanzamento con il componente dei caricamenti già esistente, se
  si adatta; altrimenti niente.
- Errori (token scaduto, file sparito): un `Alert` con il messaggio dell'API.
- All'avvio la pagina chiama `window.pywebview.api.file_in_attesa()`, che restituisce i token
  arrivati prima che la pagina fosse pronta. Serve per il caso "RT era chiuso".

## Mac

- `scripts/build_app.py`, `Info.plist`: aggiungi `CFBundleDocumentTypes` con
  `LSHandlerRank: "Alternate"` e `CFBundleTypeRole: "Viewer"`, e `LSItemContentTypes`:
  - `public.audio`;
  - `com.adobe.pdf`;
  - `public.image`;
  - `public.plain-text`;
  - `org.openxmlformats.wordprocessingml.document`;
  - `org.openxmlformats.presentationml.presentation`;
  - `public.zip-archive`.
- `rt/window.py`: con `objc.classAddMethods` (come fa `install_macos` in
  `rt/window_permissions.py`, **senza** sostituire classi di pywebview) aggiungi al delegato
  dell'app di pywebview (`webview.platforms.cocoa.BrowserView.AppDelegate`) il metodo
  `application:openFiles:` (firma `v@:@@`). Riceve un `NSArray` di percorsi: scrive i token e
  avvisa la pagina come sopra, poi chiama `app.replyToOpenOrPrint_(0)`.
- Va installato **prima** di `webview.start`, come il microfono.
- Il lanciatore è uno script che fa `exec` di python, e l'app Cocoa nasce solo dopo la preparazione
  dei servizi. L'Apple Event di apertura che arriva all'avvio potrebbe perdersi. Verifica con il
  test di fumo (sotto). Se si perde, aggiungi in `rt/desktop.py` la lettura di
  `NSAppleEventManager.sharedAppleEventManager().currentAppleEvent()` all'avvio della finestra, e se
  serve chiedi a Claude: non inventare altri meccanismi.

## Windows

- `packaging/windows/rt.iss`:
  - per ciascuna estensione di `ACCEPTED_EXTENSIONS`, una chiave in
    `HKCU\Software\Classes\.<ext>\OpenWithProgids` con valore `RT.File`;
  - una classe `HKCU\Software\Classes\RT.File` con `shell\open\command` =
    `"{app}\python\pythonw.exe" {#RtCmd} desktop --open "%1"`;
  - tutte con `Flags: uninsdeletevalue` / `uninsdeletekey`, solo utente corrente (l'installer è
    senza admin).
- `rt/desktop.py`: nuovo argomento `--open PATH` (ripetibile, `nargs="*"`). Con `--open`:
  - se la finestra è già aperta (`_activate_existing()` in `rt/window.py`), scrive i token in
    `run/opened/` ed esce;
  - altrimenti apre la finestra come sempre e tiene i token in attesa per `file_in_attesa()`.
- La finestra già aperta scopre i token nuovi con un thread che guarda `run/opened/` ogni secondo
  (solo file creati dopo l'avvio della finestra e non ancora annunciati), e li annuncia alla pagina
  con `evaluate_js`. Lo stesso controllo vale sul Mac, così le due strade arrivano allo stesso punto.
- Trascinare sul collegamento del desktop passa i file come argomenti: aggiungi `--open` anche ai
  collegamenti `[Icons]` (`Parameters: "{#RtCmd} desktop --open"`). Se Windows non accoda i
  percorsi agli argomenti di un collegamento con parametri, lascia stare: bastano "Apri con" e il
  doppio clic.

## Pulizia

- All'avvio della finestra, cancella i `.json` in `run/opened/` più vecchi di 10 minuti.

## Test

- `tests/test_opened_files.py`:
  - l'endpoint serve il file con token valido una volta sola (la seconda è 404);
  - 404 con token scaduto, con un percorso che non è un file, con un'estensione non accettata;
  - il token è nel nome del file ma non serve da percorso (`../` nel token → 404).
- `tests/test_desktop_window.py`:
  - `--open` con finestra già aperta scrive i token ed esce senza aprire una seconda finestra;
  - il metodo `application:openFiles:` (oggetto finto) scrive i token e chiama `evaluate_js`.
- Vitest: `window.rtOpenedFiles` scarica i file (fetch finto) e apre Nuova lezione con i `File`
  giusti.
- `.github/workflows/app.yml`, job Mac, dopo il test di fumo esistente: `open -a` sull'app
  installata con un `.txt` di prova; poi controlla in `desktop.log` la riga che dice che è arrivato
  un file. Se l'Apple Event all'avvio si perde, il test lo mostra.

Prova a mano (Attilio): trascina un audio sull'icona nel Dock con RT aperto e con RT chiuso.

## Changelog

- Puoi aprire audio e PDF con RT dal Finder ("Apri con") o trascinandoli sull'icona nel Dock: si
  apre Nuova lezione con quei file.
