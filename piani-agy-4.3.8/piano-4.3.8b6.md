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

# In coda (dalla beta 5, dopo la voce 1)
Dal thread dei metadati: `cartella` di info.yaml non aggiornata dopo la rinomina; azione «scambia date»; spiegare il 409 intermedio
quando si modificano i metadati di fila. Da dettagliare prima di darli ad agy.
