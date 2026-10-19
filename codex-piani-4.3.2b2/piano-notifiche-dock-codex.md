# Piano 2 · Notifiche di sistema e numero sull'icona dell'app

## Cosa deve succedere

Solo nell'app (finestra pywebview), Mac e Windows:

1. Quando un job finisce (riuscito o fallito) o si ferma in attesa di una decisione, e la finestra
   RT **non** è in primo piano, compare una notifica di sistema.
   - Titolo: il nome del job (`jobTypeLabel`).
   - Testo: il titolo della lezione se c'è, più l'esito in una parola ("finito", "non riuscito",
     "serve la tua decisione").
   - Clic sulla notifica: porta davanti la finestra RT. Se è facile, apre anche la pagina del job
     (`decisionLink(job)` oppure `/job/<id>`); altrimenti basta portare davanti la finestra.
2. L'icona di RT nel Dock (Mac) mostra lo stesso numero del badge "Job" del menu (`JobsNavBadge`:
   attivi, più in attesa di decisione, più caricamenti). Il numero sparisce a zero.
3. Su Windows, al posto del numero, la finestra lampeggia nella barra delle applicazioni quando
   arriva una notifica e RT non è in primo piano.
4. Nel browser non cambia niente.

Niente impostazioni nuove: i lavori lunghi sono il motivo per cui l'utente lascia la finestra.

## Frontend

- Nuovo hook `useDesktopJobSignals()` in `frontend/src/components/jobs/JobsIndicator.tsx` (o in un
  file accanto), montato una volta nel `Layout`, attivo solo con `isAppWindow()`
  (`frontend/src/lib/zoom.ts`) e con `window.pywebview?.api`.
- Usa la stessa query di `JobsNavBadge` (`useJobs({ limit: 50 })`, `useUploads()`). Estrai il
  calcolo del conteggio in una funzione condivisa, così badge del menu e Dock non divergono.
- Conteggio: a ogni cambio chiama `window.pywebview.api.badge(count)`.
- Transizioni: tiene in un `useRef` lo stato precedente di ogni job (per id). Quando un job passa da
  attivo (`isActive`) a `succeeded`, `failed` o `waiting_for_decision`, e
  `document.visibilityState === 'hidden' || !document.hasFocus()`, chiama
  `window.pywebview.api.notifica(titolo, testo, percorso)`.
- Al primo caricamento della lista non notifica niente: servono due letture per vedere una
  transizione.
- Tipi esclusi (rumorosi e brevi): `recall_evaluate`, `recall_comment` e i job di sola lettura. Se ci
  sono altri tipi che durano pochi secondi, escludili in una costante `QUIET_JOB_TYPES` accanto a
  `JOB_TYPE_LABELS`.
- `useJobs({ limit: 50 })` oggi non ha polling: si aggiorna solo quando qualcosa invalida
  `jobKeys.all` (gli eventi di un job aperto, una mutazione). Con la finestra in secondo piano non
  succede niente, e le notifiche non arriverebbero mai. Nell'hook usa quindi una query sua, con la
  stessa chiave `jobKeys.list({ limit: 50 })`, `refetchInterval: 5000` e
  `refetchIntervalInBackground: true`, attiva solo nell'app (`enabled`). Nel browser non cambia
  niente.

## Finestra: `rt/window.py` e nuovo `rt/window_signals.py`

`DesktopApi` guadagna due metodi, che delegano a `rt/window_signals.py` (come
`rt/window_permissions.py`, così si testa senza la finestra):

### `badge(count: int)`

- Mac:
  `AppHelper.callAfter(lambda: NSApplication.sharedApplication().dockTile().setBadgeLabel_(str(count) if count else ""))`.
- Windows: niente.

### `notifica(titolo, testo, percorso=None)`

- Mac, in ordine:
  1. `NSUserNotificationCenter.defaultUserNotificationCenter()`. Il processo è il python dentro
     `RT.app/Contents/Resources/app/python/bin/python3`, lanciato con `exec` dallo script
     `Contents/MacOS/RT`, quindi `NSBundle.mainBundle()` potrebbe non avere un identificatore. Come
     già si fa per `CFBundleName` in `open_window`, imposta
     `infoDictionary()["CFBundleIdentifier"] = BUNDLE_ID` (quello di `scripts/build_app.py`) prima di
     chiedere il centro notifiche. Se il centro è `None`, passa al punto 2.
  2. Ripiego: `osascript -e 'display notification "<testo>" with title "<titolo>"'`, con le
     stringhe passate in modo sicuro (come `_applescript_string` in `rt/desktop.py`).
  - Scrivi in `desktop.log` quale strada ha funzionato la prima volta.
  - Clic: con `NSUserNotificationCenter` imposta un delegato che, su
    `userNotificationCenter:didActivateNotification:`, attiva l'app e, se c'è `percorso`, fa
    `window.load_url(base_url + percorso)`. Con `osascript` il clic non si gestisce: va bene.
- Windows: un `System.Windows.Forms.NotifyIcon` creato una volta (icona `rt.ico`, visibile solo
  mentre mostra il fumetto) con `ShowBalloonTip(5000, titolo, testo, ToolTipIcon.None)`. Clic
  (`BalloonTipClicked`): porta davanti la finestra e apre `percorso`. Poi
  `FlashWindowEx(window.native.Handle, FLASHW_TRAY | FLASHW_TIMERNOFG)` con `ctypes`. Tutto sul
  thread della UI (`window.native.Invoke`, come `install_windows` in `rt/window_permissions.py`).
- Linux, o errori: solo una riga nel registro, mai un'eccezione verso la pagina.

## Test

- Vitest per `useDesktopJobSignals`, con `window.pywebview.api` finto:
  - nessuna notifica al primo caricamento;
  - notifica su attivo → `succeeded` con la finestra non a fuoco;
  - nessuna notifica se la finestra è a fuoco o il tipo è in `QUIET_JOB_TYPES`;
  - `badge` chiamato con lo stesso conteggio di `JobsNavBadge`.
- `tests/test_window_signals.py`, con moduli finti per AppKit e Foundation:
  - `badge(0)` toglie il numero;
  - `notifica` usa `NSUserNotificationCenter` quando c'è, altrimenti `osascript` con le virgolette
    del testo protette;
  - su Linux non fa niente.
- Il test di fumo dell'app (`app.yml`) deve restare verde.

Prova a mano (Attilio): avvia una lezione, passa a un'altra app; a fine job arriva la notifica e il
Dock mostra il numero mentre il job gira. Controlla anche quale icona ha la notifica: se è quella
di Script Editor, vuol dire che si è usato il ripiego.

## Changelog

- Nell'app arriva una notifica quando un lavoro lungo finisce o aspetta una tua decisione, e
  l'icona nel Dock mostra quanti lavori sono in corso.
