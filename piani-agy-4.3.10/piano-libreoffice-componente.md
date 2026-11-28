# Piano agy: LibreOffice come Componente per le presentazioni (4.3.10)

Branch: `agy/4.3.10-libreoffice`, da `claude/rt-4.3.10-beta` DOPO l'unione di `agy/4.3.10-browser-sistema`
(stessi file: components.py, components.tsx, useComponentNotice.ts). Solo codice e test automatici; le verifiche
vere le fa Claude. I test non toccano mai `~/.rt`, Application Support, `~/Library/Application Support/LibreOffice`
né `/Applications`: sempre `RT_DATA_DIR`, `HOME`, `USERPROFILE` finti e server di download finto.

Decisione di Attilio (28/11, 06:53): come per il browser. Se non c'è niente tra Keynote, PowerPoint e LibreOffice
→ avviso (pallino) + download automatico di LibreOffice alla prima presentazione usata in una lezione.

## 1. Ordine di conversione (`rt/core/materials.py`, `_slide_render_methods`)
Oggi: LibreOffice → PowerPoint → Keynote → Quick Look. Nuovo:
1. PowerPoint (Windows) / Keynote (Mac), se installati: resa migliore.
2. LibreOffice: quello di sistema (come oggi `_soffice()`) oppure il componente `<dati>/components/libreoffice/`.
   Se ci sono entrambi, il componente scaricato ha la precedenza (stessa regola del browser).
3. Quick Look (solo Mac, qualità ridotta) e poi il ripiego attuale (testo e immagini da python-pptx).
Il componente si avvia sempre con un profilo suo, per non toccare quello dell'utente:
`soffice -env:UserInstallation=file:///<dati>/components/libreoffice-profile --headless --norestore
--convert-to pdf --outdir <tmp> <file>` (URL con `pathlib.Path(...).as_uri()`), timeout come oggi.

## 2. Componente `libreoffice` (`rt/core/components.py`)
- Id `libreoffice`, nome «Convertitore delle presentazioni», detail «LibreOffice <versione> (MPL-2.0)».
- Sorgente: release stabile ufficiale The Document Foundation, versione fissata in costanti (URL + byte + SHA256
  per piattaforma; Claude le compila in revisione, agy mette segnaposto):
  - Mac Apple Silicon: `LibreOffice_<v>_MacOS_aarch64.dmg` (Mac Intel: `_x86-64.dmg`, se la build RT lo supporta);
  - Windows x64: `LibreOffice_<v>_Win_x86-64.msi`.
  Download con ripresa (Range), `.part`, verifica SHA256 come macparakeet.
- Installazione SENZA privilegi e senza toccare /Applications o Programmi:
  - Mac: `hdiutil attach -nobrowse -readonly -mountpoint <tmp>` → `ditto <tmp>/LibreOffice.app
    <dati>/components/libreoffice/LibreOffice.app` → `hdiutil detach`; poi controllo che
    `Contents/MacOS/soffice` esista ed esegua `--version` (timeout 60 s).
  - Windows: `msiexec /a <msi> /qn TARGETDIR=<dati>\components\libreoffice-tmp` (installazione amministrativa =
    sola estrazione, non registra nulla) → spostare la cartella con `program\soffice.exe` in
    `<dati>\components\libreoffice`; controllo `--version`.
  - Tutto in una cartella `.partial` rinominata alla fine (atomico); cancellare dmg/msi dopo il successo.
- Stati/azioni come gli altri componenti (Scarica, Pausa, Riprendi, Riprova, Elimina; Elimina toglie anche il profilo).
  Avanzamento: % del download; durante estrazione/verifica stato «downloading» con messaggio «Preparo…» al 99%.
- `system_app`: nome rilevato tra «Keynote», «Microsoft PowerPoint», «LibreOffice» (installato dall'utente).
  `required = system_app is None`. Descrizioni:
  - componente pronto → «RT usa questo convertitore per le slide delle presentazioni»;
  - non scaricato, app rilevata → «Rilevato <nome>: RT usa quello, scaricare questo componente non è necessario»;
  - non scaricato, niente → «Serve per trasformare le presentazioni (.pptx) in slide: scaricalo».
- Pallino: `useComponentNotice` considera anche questo componente quando `required` e non pronto/non in download
  (stesso pallino su ingranaggio, voce Lavorazione e riga del componente, come da piano browser).
- `available_slide_methods()` e `window_permissions.py` (`automazione_keynote`) devono contare anche il componente.

## 3. Download automatico alla prima presentazione
In `materials.py`, quando una lezione contiene una .pptx e nessun metodo dei punti 1-2 è disponibile:
avviare `start_download("libreoffice")` (se non attivo) e procedere SUBITO con il ripiego attuale (Quick Look /
python-pptx): la lezione non aspetta. Messaggio nel job: «Slide importate senza resa grafica: sto scaricando il
convertitore delle presentazioni (circa 300 MB). Le prossime presentazioni avranno le slide complete.»
Niente download all'avvio dell'app.

## 4. Testi
- Pannello Componenti: dimensione mostrata dal valore reale della costante (~300 MB da scaricare).
- Guida (docs/guida): dove si parla di LibreOffice/Keynote/PowerPoint, spiegare il nuovo ordine e il componente.

## Test (agy)
- Ordine dei metodi: Keynote/PowerPoint prima di LibreOffice; componente prima del LibreOffice di sistema.
- Download finto: SHA256 sbagliato → errore; ok → estrazione simulata (hdiutil/msiexec sostituiti da funzioni
  finte), cartella finale con soffice, `.partial` rimossa; Elimina.
- `required`/descrizioni con e senza app rilevate; pallino nel frontend.
- Prima .pptx senza convertitori → download avviato una sola volta, lezione completata col ripiego.

## 5. Aggiunte dopo le prove sul Pro (28/11 08:00)
- Costanti (LibreOffice 26.8.3): piani-agy-4.3.10/libreoffice-costanti.md. dmg aarch64 300 MB,
  msi x86-64 376 MB; app estratta ~808 MB su disco (mostrare questo valore come spazio occupato).
- Keynote via osascript va in timeout a 120 s se manca il permesso Automazione (dialogo che nessuno vede):
  - timeout di Keynote ridotto a 45 s;
  - se Keynote fallisce per timeout o per errore -1743 (permesso negato), ricordarlo in components.json
    (`keynote_blocked_until` = ora + 7 giorni) e saltarlo nelle conversioni successive, passando a LibreOffice;
    in quel caso Keynote NON conta come «app rilevata» per `required` (così parte il pallino/download);
  - nel pannello, sotto la riga, testo «Keynote non risponde: consenti a RT di controllarlo in Impostazioni di
    Sistema › Privacy e sicurezza › Automazione, oppure scarica il convertitore».
- Quick Look non produce PDF né PNG per slide (solo Preview.html): resta solo come ultimo ripiego, non conta come
  convertitore.

## 6. Font (dalle prove sul Pro 28/11 08:10)
LibreOffice --headless su macOS usa il backend senza schermo (svp) con fontconfig, che vede solo i font inclusi
nell'app: Helvetica, Georgia, Arial Black, Avenir, Cambria Math… diventano Linux Libertine (serif).
Correzione VERIFICATA sul Pro (08:19): con FONTCONFIG_FILE tutti i font veri e anche le emoji a colori; 6,8 s a
freddo, poi cache. NON usare SAL_USE_VCLPLUGIN=osx (pedici sovrapposti).
- RT scrive `<dati>/components/libreoffice-fonts.conf` con le cartelle dei font di sistema e lo passa con la
  variabile `FONTCONFIG_FILE` (solo all'ambiente del processo soffice):
  macOS: `/System/Library/Fonts`, `/System/Library/Fonts/Supplemental`, `/Library/Fonts`, `~/Library/Fonts`
  (+ `<include ignore_missing="yes">` del fonts.conf incluso nell'app, se esiste; cachedir in
  `<dati>/components/libreoffice-fontcache`).
  Windows: non serve (headless usa i font di Windows); verificarlo comunque nella prova su Windows.
- Tabella di sostituzione nel profilo RT (registrymodifications.xcu, VCL.xcu FontSubstitutions) solo per i font
  Microsoft che mancano sul Mac: Calibri→Carlito, Cambria→Caladea, Cambria Math→STIX Two Math (di sistema su
  macOS; senza, fontconfig sceglie HiraMaruPro).
- Emoji: con FONTCONFIG_FILE escono a colori (Apple Color Emoji).
- La cachedir fissa in `<dati>/components/libreoffice-fontcache` evita i 6,8 s a ogni conversione; Elimina la toglie.
