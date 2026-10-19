# Piano 5 · DMG: firma ad-hoc e istruzioni per "Apri comunque" nello sfondo

## Perché

L'app non è firmata con un Developer ID (costa 99 € l'anno), e Attilio ha deciso di non comprarlo.
Oggi `scripts/build_app.py` non firma RT.app in nessun modo. Un'app senza firma, scaricata dal
browser, su Apple Silicon spesso viene data per "danneggiata", senza via d'uscita. Con una firma
ad-hoc (gratuita, `codesign -s -`) macOS dice invece che non può verificare lo sviluppatore. Dopo il
primo tentativo di apertura, Impostazioni di Sistema › Privacy e sicurezza mostra **Apri comunque**.

La finestra del DMG deve guidare l'utente come fanno i DMG delle app per Mac: le istruzioni stanno
nello **sfondo**, senza file di istruzioni nel DMG e senza app esterne (Sentinel scartato il
2026-10-19).

Gli aggiornamenti fatti dall'app copiano RT.app senza quarantena (`copy_app_from_dmg` in
`rt/core/app_update.py`), quindi "Apri comunque" serve solo alla prima installazione.

## 1. Firma ad-hoc (`scripts/build_app.py`, `build_macos`)

- Dopo aver scritto `Info.plist` e prima di creare il DMG, firma l'app dall'interno verso
  l'esterno:
  1. tutti i `.so`, i `.dylib` e gli eseguibili Mach-O dentro `Contents/Resources/app` (trovali
     con `file` o con la firma magica Mach-O, non solo per estensione):
     `codesign --force --sign - --timestamp=none <file>`;
  2. poi il bundle: `codesign --force --sign - --timestamp=none <RT.app>`.
- Niente `--deep` (Apple lo sconsiglia) e niente entitlements.
- Il lanciatore `Contents/MacOS/RT` è uno script: codesign lo firma con il bundle e mette la firma
  negli attributi estesi. Per questo il DMG va creato da una cartella su APFS/HFS+ (il runner lo
  è), e `ditto` li conserva.
- Subito dopo: `codesign --verify --strict --verbose=2 <RT.app>`. Se fallisce, la build fallisce.
- Nel `LAUNCHER` aggiungi `export PYTHONDONTWRITEBYTECODE=1` prima di `exec`. Così python non
  scrive `__pycache__` dentro il bundle firmato (il bytecode è già precompilato, vedi `_trim`), e
  la firma resta valida. Controlla che nessun'altra parte di RT scriva dentro `RT.app` durante l'uso.
  I dati stanno in `~/.rt`, ma se trovi altri scritti, elencali nella PR.

## 2. Sfondo e disposizione

- Nuovo `packaging/dmg/background.png` (660×400) e `packaging/dmg/background@2x.png` (1320×800),
  generati da un nuovo script `scripts/make_dmg_background.py` con Pillow. I PNG vanno nel
  repository. Lo script resta per rigenerarli e non gira durante la build.
- Contenuto dello sfondo, minimale (principio UI di RT: poco testo, niente frasi di spiegazione):
  - a sinistra il posto per l'icona di RT, a destra quello per Applicazioni, con una freccia
    sottile fra le due;
  - sotto, tre righe brevi e numerate:
    1. `Trascina RT in Applicazioni`
    2. `Apri RT da Applicazioni`
    3. `Impostazioni › Privacy e sicurezza › Apri comunque`
  - colori neutri, leggibili sia con il Finder chiaro sia con quello scuro (lo sfondo del DMG non
    cambia col tema: usa un fondo chiaro fisso). Font di sistema, se Pillow lo trova sul runner,
    altrimenti un font libero messo in `packaging/dmg/`.
- Disposizione con **dmgbuild** (pacchetto pip, solo macOS): crea il `.DS_Store` con sfondo,
  dimensione della finestra, posizione delle icone, vista a icone e niente barre.
  - Nuovo `packaging/dmg/settings.py` per dmgbuild:
    - `files = [<RT.app>]`, `symlinks = {"Applications": "/Applications"}`;
    - `background = "packaging/dmg/background.png"` (dmgbuild usa da solo `@2x` se esiste);
    - `window_rect = ((200, 120), (660, 400))`, `icon_size = 128`;
    - `icon_locations` allineate ai due posti disegnati nello sfondo;
    - `format = "UDZO"`, `volume_name = "RT"`, `show_status_bar = False`,
      `show_toolbar = False`, `show_sidebar = False`.
  - In `build_macos`, al posto di `hdiutil create`: `python -m dmgbuild -s packaging/dmg/settings.py
    -D app=<percorso di RT.app> RT <dmg>`. Togli il symlink fatto a mano: ci pensa dmgbuild.
  - dmgbuild è uno strumento di build, non una dipendenza dell'app: non va in
    `packaging/requirements-app.txt`. Installalo nel passo "Build dmg" di
    `.github/workflows/app.yml` (e in quello di release, se costruisce a parte), con versione fissa
    (l'ultima disponibile quando implementi), prima di `python scripts/build_app.py`.
- Icona del volume: `icon = "packaging/icons/rt.icns"` in `settings.py`.

## 3. CI

- Passo "Install from the dmg" di `app.yml`: dopo il `ditto`, aggiungi
  `codesign --verify --strict "$RUNNER_TEMP/Applications/RT.app"`. Controlla anche che nel volume
  montato ci siano solo `RT.app` e `Applications` (più i file nascosti di dmgbuild:
  `.background`, `.DS_Store`): niente file di istruzioni.
- `scripts/installer_size.py`: lo sfondo aggiunge pochi KB; se il controllo della dimensione ha una
  soglia stretta, aggiornala e dillo nella PR.
- Dopo i passi di fumo (che eseguono python dall'app), un secondo `codesign --verify --strict` mostra
  se l'uso ha rotto la firma. Se la rompe, trova chi scrive nel bundle e correggilo: non togliere il
  controllo.

## Note da riportare nella PR

- Con una firma ad-hoc, l'identità del codice cambia a ogni versione. macOS potrebbe richiedere il
  permesso del microfono dopo un aggiornamento. Non serve fare niente, ma va scritto, così Attilio
  sa cosa aspettarsi.
- Windows non cambia: SmartScreen ha già "Ulteriori informazioni › Esegui comunque".

## Test

- `tests/test_build_app.py` (o il file che testa già `build_app.py`):
  - con `subprocess.run` finto, `build_macos` firma prima i Mach-O interni, poi il bundle, poi
    verifica, poi chiama dmgbuild con `settings.py`;
  - il `LAUNCHER` contiene `PYTHONDONTWRITEBYTECODE=1`.
- `scripts/make_dmg_background.py` va eseguito una volta: i PNG nel repository devono avere le
  dimensioni giuste (test che apre i PNG con Pillow, se Pillow è fra le dipendenze di test;
  altrimenti legge l'intestazione PNG).

Prova a mano (Attilio): scarica il DMG dal browser, aprilo e controlla la finestra. Trascina RT,
aprilo: deve comparire l'avviso con "Fine", e poi "Apri comunque" in Privacy e sicurezza.

## Changelog

- Il DMG spiega nello sfondo come installare RT e come aprirlo la prima volta con "Apri comunque".
- RT.app ora ha una firma ad-hoc: macOS non la dà più per danneggiata.
