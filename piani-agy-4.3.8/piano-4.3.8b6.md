# Piano 4.3.8b6

Base: `claude/rt-4.3.8` dopo la 4.3.8b5. Solo codice e test (typecheck, lint, vitest, pytest sui test toccati). Niente Playwright.

## 1. Un solo «Esporta», poi il popup sceglie Salva o Condividi
Oggi il menu Esporta della lezione ha sia le voci di download sia «Condividi PDF» / «Condividi lezione», e la selezione multipla
nella pagina Lezioni ha «Scarica Markdown» e «Scarica zip». Si unifica tutto: si esporta, e il popup in basso (`file-status`,
`frontend/src/lib/fileStatus.ts`, `frontend/src/components/ui/file-status.tsx`) chiede cosa fare del file pronto.

### 1a. Il popup
- Dopo ogni esportazione il popup resta aperto con **Salva**, **Condividi** (solo se il sistema può condividere quel tipo di file,
  `canShareFiles`) e **Annulla** (pulsante con X in alto a destra, anche Esc). Non c'è più il salvataggio automatico quando il file è
  pronto in fretta (`requiresTouch` sparisce): decide sempre l'utente.
- Anche mentre RT prepara il file («Preparo il PDF…») c'è Annulla: interrompe la richiesta (`AbortController` sul fetch; per
  l'esportazione multipla annulla il job con l'API di annullamento dei job già esistente).
- Annulla non lascia residui: libera il `File`/blob in memoria e gli object URL, cancella il file del job di esportazione multipla sul
  server (nuovo `DELETE /api/v1/lesson-exports/{job_id}`, che toglie la cartella di `job_export_path`), e nell'app le cartelle temporanee
  di condivisione (`_condividi_temp_dirs` in `rt/window.py`) si cancellano dopo la condivisione o all'annullamento, non solo all'uscita.
  Stessa pulizia dopo Salva e dopo Condividi.
- Testo: «PDF pronto: <nome>» per un file; «3 PDF pronti» / «3 lezioni pronte (.rt)» per più file, con l'elenco dei nomi a comparsa.

### 1b. Lezione singola (`frontend/src/routes/lessons.tsx`, menu Esporta)
Voci: Markdown, PDF, Lezione (.rt), Solo le fonti (zip), più la spunta «Includi lo stato di studio». Togli «Condividi PDF» e
«Condividi lezione»: ogni voce prepara il file e apre il popup di 1a. Vale per tutti i formati, Markdown e fonti compresi.

### 1c. Più lezioni (`frontend/src/components/lessons/LessonsView.tsx`, `SelectionBar`)
- Al posto di «Scarica Markdown» e «Scarica zip» due pulsanti: **Esporta PDF** (icona `FileText`) ed **Esporta lezioni (.rt)**
  (icona `Archive`, con un menu che contiene la spunta «Includi lo stato di studio» ed «Esporta lezioni (.rt)»). Markdown e fonti
  di più lezioni non servono più nella barra.
- Backend: il job `export_lessons` accetta il formato `pdf` (stesso PDF dell'export singolo, una lezione dopo l'altra con
  l'avanzamento; le lezioni senza documento finale si saltano e il popup dice quante) e, per `pdf` e `zip`, produce **file separati**
  (un .pdf o un .rt per lezione, nomi come l'export singolo, `unique()` per i doppioni) in una cartella del job. Nuovi endpoint: elenco dei
  file del job e download del singolo file; il download zip di tutta la cartella resta come oggi per «Salva» nel browser.
- Salva:
  - nell'app: scelta di una cartella (`create_file_dialog` di tipo cartella) e copia lì di tutti i file, con un nuovo metodo
    `salva_esportazione(job_id)` della `DesktopApi` che legge la cartella del job lato server, senza passare i file dalla webview;
  - nel browser: un solo zip con dentro i file separati (i browser bloccano o chiedono conferma per più download di fila).
- Condividi:
  - app su Mac: `NSSharingServicePicker` accetta più elementi; estendi `condividi` (o nuovo `condividi_esportazione(job_id)`) per
    passare tutti i file della cartella del job;
  - browser (iPhone, Safari, Chrome): `navigator.share({ files: [...] })` con tutti i file se `navigator.canShare` li accetta, altrimenti
    il pulsante Condividi non c'è;
  - app su Windows: niente condivisione (come oggi), solo Salva.
- Test: vitest del popup (Salva, Condividi, Annulla, file multipli, nessun salvataggio automatico), della barra di selezione (due
  pulsanti nuovi); pytest del job `pdf`/`zip` a file separati, dei nuovi endpoint e della cancellazione; test di `rt/window.py` per
  condivisione multipla e pulizia delle cartelle temporanee con oggetti finti, come i test esistenti.

## 2. Studio: Cmd+A seleziona e copia solo l'unità
Oggi Cmd+A (Ctrl+A su Windows) in Studio seleziona tutta la pagina, barra e intestazione comprese. Nella fase di lettura
(`frontend/src/components/study/Study.tsx`, stesso `onKeyDown` delle altre scorciatoie, stessa guardia per campi di testo, menu e
dialoghi; non nella lettura veloce) Cmd/Ctrl+A seleziona solo l'unità aperta: il titolo `h2#study-unit-title` e il testo
`[data-testid=study-text]` (`selection.setBaseAndExtent` dal titolo alla fine del testo).
- Fuori dalla selezione e dalla copia: il chip del timestamp, i pulsanti e le strisce delle immagini, i marcatori delle note
  (`user-select: none` dove non c'è già, oppure esclusi nella copia).
- Copia ben formattata: `handleCopy` di `UnitText` oggi taglia la selezione al solo testo (`clipToRoot`) e lascia il titolo fuori.
  Con la selezione dell'unità intera la copia mette in `text/html` il titolo come `<h2>` seguito dall'HTML del testo passato da
  `selectionHtml` di `frontend/src/lib/copyFormat.ts` (rispetta il formato scelto in Impostazioni → Copia, formule comprese), e in
  `text/plain` «1.2 Titolo», una riga vuota e il testo sorgente (`sourceOffsets`, come oggi). Evidenziazioni e colori seguono le spunte di Impostazioni → Aspetto e lettura → Copia, come la copia di oggi.
- Se l'utente seleziona a mano solo una parte, la copia resta quella di oggi.
- **Copia in Markdown grezzo**: nuova scorciatoia «Copia l'unità in Markdown» (gruppo Studio di Impostazioni → Editor e scorciatoie,
  predefinita `Mod-Alt-c`, cioè Cmd+Option+C / Ctrl+Alt+C, personalizzabile come le voci 7 della b5). Copia negli appunti, come
  `text/plain`, il titolo come intestazione Markdown (`## 4.2 Titolo`, stesso livello del documento) e il Markdown dell'unità così
  com'è nel documento: grassetto `**…**`, corsivo `*…*`, elenchi, formule `$…$`. Togli le righe delle immagini e degli allegati e i
  commenti interni di RT. Serve un campo nuovo `markdown` in `StudyUnit` (backend dello Studio, stesso testo da cui nasce `html`).
  Funziona anche senza selezione e conferma con un avviso breve («Unità copiata in Markdown»). Nel browser Cmd+Option+C può essere
  già usato dagli strumenti per sviluppatori: va bene, la scorciatoia si può cambiare.
- Test anche per la copia in Markdown: contenuto esatto (titolo `##`, grassetto, formule, niente immagini) e scorciatoia personalizzata.
- Test vitest: Cmd+A seleziona titolo e testo e non la barra; la copia contiene titolo e testo in HTML e testo semplice, senza il timestamp;
  Cmd+A dentro un campo di testo resta quello del campo.

## 3. Trascinamento delle immagini nelle zone dove non si può rilasciare
L'anteprima personalizzata (`frontend/src/components/lesson/dragPreview.ts`, in basso a destra del cursore: già sistemata da Claude,
non cambiare la posizione) sparisce quando il puntatore passa su intestazione, barra laterale o altre zone dove non si può rilasciare,
e ricompare solo tornando sul testo. Va sistemato così:
- L'anteprima segue sempre il puntatore, su tutta la finestra. Trova perché si perde: per esempio `drag`/`dragover` con coordinate 0,0
  in WebKit fuori dalle zone di rilascio, o elementi che fermano la propagazione. Se serve, aggiorna la posizione da `dragover` a livello
  di `document` in cattura e tieni l'ultima posizione valida.
- Nelle zone dove non si può rilasciare: `dataTransfer.dropEffect = 'none'` (niente «+» sul cursore; il cursore di divieto se il sistema
  lo mostra) e, sull'anteprima, un piccolo segno di divieto (icona `Ban` di lucide in un cerchio rosso nell'angolo) finché resta lì.
  Tornando su una zona valida il segno sparisce.
- Rilasciare in una zona non valida non fa nulla: nessuna modifica al documento, nessun annulla da registrare, anteprima tolta.
- Valgono le stesse regole per il trascinamento dal pannello Media (anche multiplo) e per le miniature delle unità.
- Test vitest: posizione aggiornata anche con `dragover` su un elemento non di rilascio; segno di divieto presente e poi tolto;
  `drop` fuori zona senza effetti.

# In coda (dalla beta 5, dopo le voci sopra)
Dal thread dei metadati: `cartella` di info.yaml non aggiornata dopo la rinomina; azione «scambia date»; spiegare il 409 intermedio
quando si modificano i metadati di fila. Da dettagliare prima di darli ad agy.
