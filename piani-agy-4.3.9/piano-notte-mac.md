# Piano notte 1 — Mac/Windows: icona nei dialoghi, chiusura con la X, permessi, job paralleli

Branch: `agy/4.3.9-notte-mac` (parte da claude/rt-4.3.9-beta + fix openFiles già fatto da Claude).
Solo codice e test unitari. Niente verifiche nell'app (le fa Claude). Commit piccoli, push sullo stesso branch.

## 1. Icona RT nei dialoghi di servizio (oggi compare la cartella blu)
I dialoghi sono NSAlert di pywebview (`create_confirmation_dialog`, es. "RT smetterà di lavorare in
background. Uscire?") e alert `osascript` (`rt/desktop.py` `_alert`, `_permission_alert`, eventuali altri:
`grep -rn "display alert\|display dialog" rt`). Il processo è python3, quindi l'icona di default è generica.
- In `rt/window.py`, su darwin e PRIMA di `webview.start`: carica `Contents/Resources/rt.icns` (via
  `bundle.app_path()`; se manca, `packaging/icons/rt.icns` dalla radice del progetto) e chiama
  `NSApplication.sharedApplication().setApplicationIconImage_(img)` subito (non solo su `shown`).
- Avvolgi `webview.platforms.cocoa.BrowserView.display_confirmation_dialog` e `display_input_dialog`
  (metodi statici) con una versione che fa `alert.setIcon_(img)`: il modo più semplice è
  ricopiare le ~10 righe del metodo originale di pywebview 6.2.1 aggiungendo `setIcon_`; protetto da try,
  se fallisce resta l'originale. Commento con il motivo.
- osascript: sostituisci `display alert` con `display dialog ... with icon (POSIX file "<percorso rt.icns>")`
  e `buttons`/`default button` equivalenti; se l'icona non esiste usa `with icon caution`. Mantieni i
  risultati (`button returned:`) letti dal codice chiamante.
- Test: helper puro che costruisce lo script osascript (con e senza icona); test del wrapper con oggetti finti.

## 2. Chiusura con la X: impostazione
Oggi su Mac la X chiude solo la finestra: i LaunchAgent api e worker restano attivi (e ripartono al login).
Su Windows resta il processo nascosto `desktop --serve`. Questo resta il default.
- Config: in `UiConfig` (`rt/core/config.py`) `close_action: Literal["background", "quit"] = "background"`.
  Esponilo nelle preferenze come gli altri (`rt/services/settings_service.py`, chiave `chiusura_x`:
  `"background"`/`"esci"`), schema API e tipi frontend rigenerati come fa il progetto.
- UI: Impostazioni → Generali (`frontend/src/components/settings/general.tsx`), solo nell'app desktop
  (`isAppWindow()`), gruppo "Chiudendo la finestra con la X":
  - "Continua a lavorare in background (consigliato)" — sotto, in piccolo: "RT finisce i job in corso e
    riceve le risposte dei provider IA che lavorano in modalità batch, più economica ma più lenta."
  - "Chiudi del tutto RT" — sotto: "Ogni volta che premi la X RT smette di lavorare in background, come con
    Esci da RT (⌘Q). I job in corso si fermano e riprendono alla prossima apertura."
  Passando a "Chiudi del tutto" chiedi conferma (dialogo dell'app, non alert del browser).
- Comportamento (`rt/window.py` `open_window`): dopo che `webview.start(...)` ritorna, se l'utente ha chiuso
  la finestra (non una chiusura voluta dal codice: aggiornamento, import, ripristino, `quit_rt` che già
  ferma tutto) e `close_action == "quit"`, chiama `stop_background(base_url)` (Mac e Windows). Usa un flag
  modulo `_programmatic_close` impostato prima di ogni `window.destroy()` del codice. Leggi il config fresco
  (`load_config()`) al momento della chiusura. Niente dialogo di conferma in questo caso.
- ⌘Q / "Esci da RT" restano come oggi (dialogo + stop).
- Test: con webview finto, chiusura utente + quit → stop_background chiamato; background → no;
  chiusura programmatica → no.

## 3. Permessi
- `scripts/build_app.py` `macos_info_plist`: aggiungi
  `NSAppleEventsUsageDescription`: "RT usa Keynote per convertire le presentazioni in PDF quando LibreOffice non è installato."
  `NSLocalNetworkUsageDescription`: "RT permette di aprire le lezioni dagli altri dispositivi sulla stessa rete Wi‑Fi."
  Aggiorna `tests/test_build_app.py`.
- Elementi in background (macOS 13+): se l'utente spegne RT in Impostazioni di Sistema → Generali →
  Elementi login ed estensioni, `launchctl bootstrap` fallisce o i servizi non partono e oggi RT dice solo
  "RT non risponde". In `rt/services/service_manager.py` aggiungi `background_disabled() -> bool`
  (parsing di `launchctl print-disabled gui/<uid>`: le label `com.atturk.rt.*` con `=> disabled`/`true`)
  e in `rt/desktop.py run_macos`, quando install/start/_wait_for_api falliscono e `background_disabled()`,
  mostra un dialogo (con icona RT, punto 1) che spiega: "RT ha bisogno di lavorare in background. Attivalo
  in Impostazioni di Sistema → Generali → Elementi login ed estensioni → Consenti in background." con pulsante
  "Apri Impostazioni" (`open "x-apple.systempreferences:com.apple.LoginItems-Settings.extension"`).
  Test del parsing con output finto.
- Sezione "Permessi" in Impostazioni (solo app desktop, Mac e Windows), nuovo componente
  `frontend/src/components/settings/permissions.tsx`, voce di menu Impostazioni come le altre. Elenco
  informativo, una riga per permesso: nome, a cosa serve, quando viene chiesto, pulsante "Apri impostazioni
  di sistema" (chiama una nuova funzione `apri_impostazioni_sistema(chiave)` di `DesktopApi` che apre solo
  URL da una whitelist). Righe Mac: Microfono (registrare note vocali e risposte; c'è anche "Controlla
  permessi" che già esiste: pulsante che chiama la stessa logica), File e cartelle (solo se la cartella delle
  lezioni è in Scrivania, Documenti o Download), Automazione → Keynote (solo per convertire .pptx senza
  LibreOffice), Elementi in background (lavorare con la finestra chiusa), Rete locale (solo con l'accesso
  dalla stessa rete Wi‑Fi). Windows: Microfono (ms-settings:privacy-microphone). Niente stato "concesso/negato"
  calcolato tranne il microfono se `mic_status()` è disponibile (via DesktopApi).
- Test frontend del componente (render righe, click pulsante chiama l'API desktop finta).

## 4. Job in parallelo (niente rielaborazione: quella resta così)
- `rt/pipeline/add_images.py` `describe_new_images`: oggi un'immagine alla volta. Usa un
  `ThreadPoolExecutor` con `max_workers = max(1, min(load_config().pipeline.parallel_pages, n))`; le chiamate
  LLM nei worker, mentre salvataggio di `descriptions.json`, `progress`, `failures` e la cache restano nel
  thread chiamante (consuma i risultati con `as_completed`, aggiorna e salva lì). `raise_if_cancelled` prima
  di sottomettere e mentre consumi; su `too_many()` cancella i future pendenti. Esito identico a prima
  (stesse chiavi, stessa cache per hash).
- `judge_images_by_macro`: stessa cosa per le chiamate `decision(...)` per immagine (le immagini già in
  cache non vanno nel pool); `decisions.json` scritto nel thread chiamante.
- Ricerca immagini web per unità (`add_images.py` ~riga 399, loop `for unit_id, query in queries.items()`):
  parallelizza le richieste alla ricerca con lo stesso schema se sono chiamate di rete indipendenti.
- Cerca altri loop seriali di chiamate LLM/rete indipendenti fuori da outline/rewrite (es. enrichment,
  material pages, recall_checks, study) e parallelizzali SOLO se ogni chiamata non dipende dal risultato
  della precedente; elencali nel messaggio del commit.
- Test: con client finto che registra i thread/ordine, risultati identici al seriale, cancellazione e
  `failures.too_many()` rispettati.

## Fine
`python -m pytest -q` sui test toccati + `cd frontend && npx vitest run <file toccati> && npx tsc --noEmit`.
Aggiungi una riga al CHANGELOG nella sezione della prossima beta per ogni punto.
