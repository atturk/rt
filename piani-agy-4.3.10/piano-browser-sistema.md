# Piano agy: PDF e catture con il browser di sistema (4.3.10b6)

Branch: `agy/4.3.10-browser-sistema` (da `claude/rt-4.3.10-beta`). Solo codice e test automatici: niente prove
manuali né Playwright (le verifiche sul Pro le fa Claude). I test non devono mai toccare il vero `~/.rt` né
Application Support: usare sempre `RT_DATA_DIR` temporanea.

Richiesta di Attilio (28/11): il Chromium Playwright pesa troppo (808 MB sul Pro). RT deve usare il browser già
installato (Edge su Windows c'è sempre; Chrome o Edge su Mac se presenti). Il componente «Browser per PDF e catture»
resta in Impostazioni › Componenti:
- browser di sistema trovato → la riga dice che è stato rilevato (con il nome) e che scaricare il componente non è
  necessario; il pulsante «Scarica» resta, e **se il componente è scaricato RT usa quello** (ha la precedenza);
- nessun browser trovato → il componente è necessario: si scarica la versione minima (chrome-headless-shell,
  ~106 MB da scaricare, ~216 MB su disco), con lo stesso avviso del motore di trascrizione (pallino sull'ingranaggio,
  sulla voce della sezione e **anche sulla riga del componente**). Il pallino sulla riga va aggiunto anche al
  componente di trascrizione, che oggi non lo ha.

File principali: `rt/llm/enrichment_media.py`, `rt/core/components.py`, `rt/desktop.py`,
`rt/api/routers/lessons.py` (`_render_pdf`), schema API dei componenti (Pydantic `ComponentStatus` + tipi generati
del frontend), `frontend/src/components/settings/components.tsx`, `useComponentNotice.ts`, `UpdateNoticeDot.tsx`,
`frontend/src/routes/settings.tsx`, `frontend/src/components/Layout.tsx`, test relativi.

## 1. Rilevamento del browser di sistema (`rt/llm/enrichment_media.py`)

Nuova funzione `detect_system_browser() -> Optional[SystemBrowser]` (dataclass con `name` da mostrare, `channel`
Playwright oppure `executable_path`). Solo controlli sul disco, niente avvio (è chiamata a ogni GET dei componenti):
- **Windows**: Edge (`channel="msedge"`), poi Chrome (`channel="chrome"`). Percorsi da controllare:
  `%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe`, `%ProgramFiles%\Microsoft\Edge\Application\msedge.exe`,
  `%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe`; Chrome: `%ProgramFiles%`, `%ProgramFiles(x86)%`,
  `%LOCALAPPDATA%` + `\Google\Chrome\Application\chrome.exe`.
- **Mac**: `Google Chrome.app`, poi `Microsoft Edge.app` (in `/Applications` e `~/Applications`) con
  `channel="chrome"` / `"msedge"`; poi `Chromium.app` con `executable_path` (come oggi `_MAC_BROWSERS`).
- **Linux/Docker**: come oggi (`shutil.which("chromium")`, `"google-chrome"`), con `executable_path`.

Nomi mostrati: «Microsoft Edge», «Google Chrome», «Chromium».

## 2. Ordine di avvio (`launch_capture_browser`)

1. `RT_ENRICHMENT_CHROMIUM` (override, come oggi).
2. **Componente scaricato** (headless shell della revisione di Playwright installata): `p.chromium.launch(headless=True)`
   con `PLAYWRIGHT_BROWSERS_PATH` = `browsers_dir()`.
3. **Browser di sistema** da `detect_system_browser()`: `p.chromium.launch(headless=True, channel=...)` oppure
   `executable_path=...`. Il profilo è temporaneo (Playwright), il profilo dell'utente non si tocca.
4. Niente → `BrowserMissingError`.

Se un candidato è presente ma non parte, si registra il motivo (`logging.warning("PDF/catture: <nome> non si avvia: …")`)
e si prova il successivo; se nessuno parte e almeno uno esisteva, si solleva un errore con il motivo dell'ultimo e il
suggerimento «Scarica il browser minimo da Impostazioni › Lavorazione delle lezioni › Componenti».
Togliere la vecchia logica che prova `p.chromium.launch` senza `executable_path` per primo anche quando il componente
non c'è. Registrare nel log quale browser è stato usato (`PDF: uso Microsoft Edge (sistema)` / `uso browser scaricato`).
`find_capture_browser_executable` e `_find_headless_shell_executable` vanno semplificati di conseguenza
(cercare chi li usa con grep).

## 3. Componente (`rt/core/components.py`)

- `browser_ready()`: pronto solo se c'è l'eseguibile della headless shell (`chromium_headless_shell-*`); le cartelle
  `chromium-*` (Chromium completo delle versioni precedenti) non contano più.
- **Pulizia una tantum**: all'avvio (in `rt/desktop.py`, al posto di `ensure_capture_browser`, in un thread o
  subprocess che non blocca l'avvio) cancellare da `browsers_dir()` le cartelle `chromium-*` (completo, vecchio) e le
  `chromium_headless_shell-*` di revisioni diverse da quella attuale di Playwright, se nessun download è attivo.
  Log in `browser-install.log` con i MB liberati.
- **Niente download automatico all'avvio** (`ensure_capture_browser` non scarica più). Il download parte:
  - dal pulsante «Scarica» in Componenti;
  - come ripiego, quando si chiede un PDF o una cattura e non c'è **nessun** browser (né componente né sistema):
    si avvia il download (`start_download(BROWSER_ID)`, stesso meccanismo dei componenti, se non è già attivo) e
    l'errore 409 `pdf_browser_missing` dice: «Per il PDF serve un browser: sto scaricando il browser minimo (circa
    110 MB). Vedi l'avanzamento in Impostazioni › Lavorazione delle lezioni › Componenti, poi riprova.».
    Se il download è in pausa o in errore il messaggio lo dice invece di «si sta scaricando».
    Per le catture delle visualizzazioni (worker, `snapshot`) stesso ripiego; l'errore resta quello attuale del job.
- `_component_meta(BROWSER_ID)`: nuovi campi (aggiungerli allo schema `ComponentStatus` con default `None`/`False`,
  così gli altri componenti non cambiano, e rigenerare i tipi del frontend con lo script già usato nel repo):
  - `system_browser: Optional[str]` = nome del browser rilevato;
  - `in_use: Optional[str]` = cosa userebbe RT adesso: `"component"`, `"system"` o `None`.
  - `required = (system_browser is None)`;
  - `detail`: «Chrome Headless Shell (versione minima)»;
  - `description`:
    - componente pronto → «RT usa il browser scaricato per esportare in PDF e per le visualizzazioni»;
    - non scaricato, browser rilevato → «Rilevato <nome>: RT usa quello, scaricare questo componente non è necessario.
      Se lo scarichi, RT usa questo»;
    - non scaricato, niente browser → «Serve per esportare in PDF e per le visualizzazioni: scaricalo».
- `BROWSER_APPROX_BYTES` resta ~110 MB (download); lo spazio su disco mostrato a componente pronto è quello reale.
- `delete_component(BROWSER_ID)`: invariato (cancella le cartelle `chromium*`); dopo, se c'è un browser di sistema,
  la riga torna a «Rilevato …».

## 4. Interfaccia (Impostazioni › Lavorazione delle lezioni › Componenti)

- Badge della riga browser: `ready` → «Pronto» (come oggi); non scaricato con browser di sistema → badge neutro
  «Non necessario» con il pulsante «Scarica» ancora presente; non scaricato senza browser → come oggi «Da scaricare».
- Testo sotto la riga: la `description` del backend (punto 3).
- **Pallino sulla riga** del componente quando è necessario e non è né pronto né in download: vale per il browser
  e per il componente di trascrizione (macparakeet o ONNX, quello `required`). Stesso stile di `ComponentNoticeDot`,
  accanto al nome, `data-testid="component-row-dot-<id>"`.
- `computeMissingTranscriptionComponent` → `computeMissingComponents(items)` che restituisce **tutti** i componenti
  `required && available` non pronti e non in download (trascrizione e browser). `ComponentNoticeDot` (ingranaggio
  nella rail e barra del telefono, voce «Lavorazione delle lezioni») si accende se la lista non è vuota;
  `aria-label`: «<nome> da scaricare» se è uno solo, «Componenti da scaricare» se sono più.
- Aggiornare i test vitest esistenti (`components.test.tsx`, test del notice) e aggiungerne per: browser rilevato
  (niente pallino, badge «Non necessario», Scarica presente), nessun browser (pallino su riga, voce e ingranaggio),
  due componenti mancanti (etichetta al plurale).

## 5. Test Python

- `detect_system_browser` con percorsi finti (monkeypatch di `os.path.isfile`/`sys.platform`/variabili d'ambiente):
  Windows Edge prima di Chrome; Mac Chrome prima di Edge prima di Chromium; niente → `None`.
- `launch_capture_browser` con un `p` finto: componente pronto → usato per primo anche se c'è Edge; componente assente
  → canale di sistema; candidato che non parte → si passa al successivo; nessuno → `BrowserMissingError`.
- `browser_ready` ignora `chromium-*` e riconosce `chromium_headless_shell-*` con l'eseguibile.
- Pulizia: cancella `chromium-*` e le revisioni vecchie della shell, lascia quella attuale, non fa niente con un
  download attivo.
- `_component_meta(BROWSER_ID)`: `required`, `system_browser`, `in_use`, testi nei tre casi.
- 409 del PDF senza nessun browser: avvia il download una sola volta e restituisce il nuovo messaggio.

## 6. Fuori da questo piano

- Nessun motore WebKit/WKWebView, nessuna WeasyPrint.
- Wizard iniziale: invariato.
- CHANGELOG/VERSION: li aggiorna Claude al rilascio.

Commit sul branch `agy/4.3.10-browser-sistema` e push. Niente merge nel ramo beta.
