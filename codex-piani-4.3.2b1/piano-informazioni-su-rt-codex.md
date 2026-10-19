# Piano per Codex · 4.3.2b1 · "Informazioni su RT" con versione, build e logo

Base: `claude/rt-4.3.2-beta`. File: `rt/window.py`, `scripts/build_app.py`, `rt/core/bundle.py`, `frontend/src/components/settings/info.tsx` (e l'API che la alimenta), test.

## Richiesta (Attilio)
La finestra "Informazioni su RT" dell'app (menu RT › Informazioni su RT, sul Mac) mostra solo un'icona generica di cartella e la scritta "RT". Deve mostrare versione e build, e il logo di RT. Niente di elaborato: solo dati reali.

## Causa
Il lanciatore di `RT.app` (`LAUNCHER` in `scripts/build_app.py`) fa `exec` del Python dentro `Contents/Resources/app/python/bin/python3`. Il processo che apre la finestra è quindi quel Python, non RT.app. Il pannello standard di macOS ("Informazioni su", creato da pywebview con `orderFrontStandardAboutPanel:`) legge nome, versione e icona dal bundle principale del processo, che non è RT.app: per questo non trova `Info.plist` e mostra la cartella generica senza versione. Per lo stesso motivo il Dock potrebbe mostrare un'icona generica: da verificare.

## Cosa fare
1. **Dati di build scritti dal build** (`scripts/build_app.py`, `build_payload`): accanto a `BUNDLE` scrivere `BUILD.json` con:
   - `version` (da `read_version()`);
   - `commit` (SHA corto: `GITHUB_SHA[:7]` in CI, altrimenti `git rev-parse --short HEAD`, altrimenti assente);
   - `built_at` (data e ora UTC ISO);
   - `run` (`GITHUB_RUN_NUMBER` se c'è);
   - `target` (`macos`/`windows`).
   Solo campi veri: quello che non si conosce non si scrive. Aggiungere `rt/core/bundle.py: build_info() -> dict` che legge il file e restituisce `{}` fuori dall'app.
2. **Pannello "Informazioni su" del Mac** (`rt/window.py`): in `_macos_menu` (che già riconfigura il menu dell'app con AppKit) sostituire l'azione della voce "Informazioni su RT" con `NSApplication.sharedApplication().orderFrontStandardAboutPanelWithOptions_({...})`:
   - `ApplicationName`: "RT";
   - `ApplicationVersion`: la versione completa (es. `4.3.2b1`);
   - `Version`: la build, es. `build 812 · a1b2c3d`, oppure solo il commit se manca il numero; se non c'è niente, chiave omessa;
   - `ApplicationIcon`: `NSImage.alloc().initWithContentsOfFile_(<RT.app>/Contents/Resources/rt.icns)`, con il percorso da `bundle.app_path()`;
   - `Credits`: `NSAttributedString` con poche righe vere, una per riga:
     - "Canale aggiornamenti: stabile" (o "beta", dal file `update-channel` / la funzione già usata dalla pagina Info);
     - "Compilata il 19/10/2026" (da `built_at`);
     - "Python 3.x.y · pywebview 6.2.1" (da `platform.python_version()` e `webview.__version__`);
     - "macOS 15.1 · arm64" (da `platform.mac_ver()` e `platform.machine()`).
     Testo a 11 pt, colore di sistema secondario.
   Per collegare l'azione: trovare la voce con `keyEquivalent`/titolo che inizia con "Informazioni su" e impostare target e selettore su un piccolo oggetto `NSObject` Python che chiama la funzione sopra (tenerlo vivo in una variabile di modulo).
3. **Icona nel Dock:** se in prova il Dock mostra l'icona di Python o una generica, all'avvio della finestra chiamare `NSApplication.sharedApplication().setApplicationIconImage_(<stessa NSImage>)`. Se il Dock è già giusto, non toccarlo.
4. **Windows:** pywebview non ha un pannello "Informazioni". Nel menu "RT" di `_menu`, solo su Windows, aggiungere "Informazioni su RT" che apre la pagina Impostazioni › Info (`INFO_PATH`), dove compaiono gli stessi dati (punto 5).
5. **Impostazioni › Info** (`info.tsx`): sotto "Versione" aggiungere la riga "Build" con `build 812 · a1b2c3d · 19/10/2026`. È mostrata solo nell'app (quando `build_info()` non è vuoto). I dati arrivano dall'API che già fornisce la versione alla pagina Info: aggiungere il campo `build` alla risposta e rigenerare `schema.d.ts`. Fuori dall'app (git, install.sh) la riga non compare.
6. Il logo è quello già usato per l'app (`packaging/icons/rt.icns`, `rt.png`): nessun logo nuovo.

## Test
- pytest:
  - `build_info()` legge `BUILD.json` e restituisce `{}` senza file o con un file rotto;
  - `build_payload` (con build finto o una funzione estratta `write_build_info(payload, env)`) scrive solo i campi disponibili;
  - la funzione che compone le opzioni del pannello (estrarla pura: `about_options(info, versions) -> dict`) produce `Version` "build 812 · a1b2c3d" e omette i campi mancanti;
  - su Windows il menu ha la voce "Informazioni su RT".
- vitest: Info mostra la riga Build quando l'API la fornisce e non la mostra quando manca.
- CI app (`app.yml`): il controllo di avvio del Mac (`_smoke`/`macos_menu`) verifica che la voce "Informazioni su RT" esista ancora.

Comandi: `python -m pytest tests/test_window*.py tests/test_bundle*.py tests/test_build_app*.py -q`, `cd frontend && npx vitest run src/components/settings/info.test.tsx`.

Verifica a mano (Attilio, sul Mac): menu RT › Informazioni su RT mostra il logo, `4.3.2b1`, la build e le righe con canale, data, Python e macOS.

## Changelog
Sezione 4.3.2b1, Correzioni: "Informazioni su RT mostra il logo, la versione e la build; la build compare anche in Impostazioni › Info."
