# Piano 9 · Immagini nel testo: sotto il titolo, dove le lascio, clic e cancellazione

Giro 1. Wireframe: tavole "Trascinare un'immagine con il pannello aperto" e "Impostazioni" del
canvas https://claude.ai/artifact/P1KzSVbQfXixTkEJ1kPBjf, più le note sotto il pannello.

## Com'è oggi

- Trascinare o incollare un'immagine nell'editor la carica (`uploadEditorImage`, PNG/JPEG/GIF) e la
  mette al punto del rilascio, spostata dopo un titolo se ci cade sopra (`findInsertPosition`,
  `frontend/src/components/lesson/lessonImages.ts:38`; gestori drop/dragover `:267-302`).
- Con il pannello Arricchimento aperto, `GlobalFileDrop` lascia il rilascio all'editor
  (`.cm-editor`) o alla scheda del pannello (`[data-file-drop-target]`), ma a vista le due zone non
  si distinguono.
- Un clic su un'immagine singola nel testo non fa niente (`LessonImageWidget`, `lessonUnits.ts:118`;
  le immagini disegnate da atomic-editor sono `<img>` dentro `.cm-content`). Il clic sulle strisce
  apre il visualizzatore (`imageStripDOM.ts:98`).
- "Usata nel testo" si ricava sempre dal testo (`find_units_for_image`,
  `rt/api/routers/images.py:98`).

## Cosa deve succedere

1. **Rilascio nel testo, impostazione "Sotto il titolo"** (predefinita):
   - mentre trascini sopra l'editor, la sottounità (`###`, oppure la macro `##` se non ci sono
     sottounità) sotto il puntatore si colora di sfondo azzurro chiaro;
   - una linea blu sotto il suo titolo mostra dove andrà l'immagine, con un'etichetta
     "Sotto «2.2 Metaboliti…»";
   - al rilascio l'immagine va lì: dopo la riga del titolo, il suo timecode e le immagini già sotto il
     titolo, così l'ordine segue i rilasci.
2. **Impostazione "Dove le lascio":** la linea segue il puntatore fra i paragrafi (inizio del blocco
   sotto il puntatore, mai dentro un titolo) e l'immagine va lì.
3. In tutti e due i casi l'immagine entra nei media della lezione **senza descrizione** (come oggi) e
   nell'archivio (lo fa il backend del piano 6, non serve altro qui).
4. **Rilascio sul pannello:** la scheda di upload del pannello (`data-file-drop-target`) mostra mentre
   trascini una zona tratteggiata blu "Analizza e aggiungi" (icona ScanEye) e fa quello che fa oggi
   (vision e posizionamento automatico). Fuori da editor e pannello, con il pannello aperto, il
   rilascio non fa niente.
5. **Ridimensionare** (solo con "Dove le lascio"): un'immagine singola nel testo, al passaggio del
   mouse, mostra due maniglie negli angoli in basso. Trascinandole cambia la larghezza, che si salva
   nel Markdown come frammento dell'URL: `![alt](assets/images/x.png#w=320)`. Minimo 120 px, massimo
   la larghezza del testo. Chi legge il Markdown senza RT vede comunque l'immagine.
   - L'editor e la lettura (`DocumentView` / `withImageUrls`) applicano `#w=` come `width` e lo
     tolgono dall'URL prima di caricarla.
   - `removeImagesFromDocument`, `replaceImageInDocument`, il conteggio "usata" del backend e
     `findUnitForImage` devono riconoscere l'immagine anche con `#w=…`.
6. **Clic su un'immagine nel testo** (singola o in una striscia):
   - con il pannello Arricchimento aperto la seleziona nei media della lezione: evento
     `rt-media-select {name}`. `EnrichmentPanel` lo ascolta, imposta la selezione su quella sola
     immagine e scrolla la galleria fino a lei. Niente visualizzatore;
   - con il pannello chiuso apre il visualizzatore (`rt-image-viewer-open`) con le immagini della
     lezione, partendo da quella.
   Per riconoscere il pannello aperto usa `isEnrichmentPanelOpen` (`globalFileDropUtils.ts:43`).
7. **Cancellare un'immagine nel testo** (Backspace, taglia, selezione cancellata) è un comportamento
   previsto ed equivale a Togli dal testo: l'immagine resta nei media della lezione come non usata e
   nell'archivio. Cmd+Z la rimette. Qui serve solo che la galleria si aggiorni dopo il salvataggio del
   testo (invalidare `['images', id]` quando il documento salvato cambia l'insieme delle immagini) e i
   test qui sotto.

## Impostazione

- In `components/settings/shortcuts.tsx` (Editor e scorciatoie), una riga "Immagini trascinate" con
  `SlideToggle` a due scelte: "Sotto il titolo" (predefinito) / "Dove le lascio".
- `usePreference('editor.image-drop', 'heading')`, valori `heading` | `free`. Vale per immagini
  trascinate e incollate. Incollare con "Sotto il titolo" usa la sottounità del cursore.
- Le maniglie di ridimensionamento compaiono solo con `free`.

## File

- `frontend/src/components/lesson/lessonImages.ts`:
  - posizione di inserimento per le due modalità (funzione pura `dropTarget(state, pos, mode)` →
    `{insertAt, headingLine, label}`);
  - decorazioni durante `dragover` (sfondo della sottounità, widget linea + etichetta), tolte su
    `dragleave` e `drop`.
- `frontend/src/components/lesson/lessonUnits.ts` e `components/images/imageStripDOM.ts`: clic e
  maniglie.
- `frontend/src/components/lesson/panels/EnrichmentPanel.tsx`: solo l'ascolto di `rt-media-select`,
  la zona "Analizza e aggiungi" durante il trascinamento e lo scroll alla miniatura (con
  `MediaGallery.tsx` se serve un `scrollToName`). Nient'altro: il resto del pannello cambia nel
  piano 10 (giro 2).
- `GlobalFileDrop.tsx` / `globalFileDropUtils.ts`: con il pannello aperto, rilascio ignorato fuori
  dalle due zone.
- `components/settings/shortcuts.tsx`.
- Backend: `find_units_for_image` e `in_document` riconoscono `#w=` (`rt/api/routers/images.py`).

## Test

- Vitest:
  - `dropTarget` con "Sotto il titolo": puntatore a metà paragrafo di 2.2 → dopo titolo e timecode di
    2.2 e dopo le immagini già lì; puntatore su una macro senza sottounità → sotto la macro;
  - `dropTarget` con "Dove le lascio": inizio del blocco, mai dentro un titolo;
  - `#w=320` letto e scritto, riconosciuto da remove e replace;
  - clic su un'immagine con il pannello aperto emette `rt-media-select` e non apre il visualizzatore;
    con il pannello chiuso apre il visualizzatore;
  - la galleria seleziona e scrolla all'evento;
  - la preferenza cambia la modalità.
- Pytest: un'immagine tolta dal Markdown resta in `GET /lessons/{id}/images` con
  `in_document: false`; con `#w=320` nel Markdown risulta usata.

## Changelog

- Un'immagine trascinata nel testo va sotto il titolo della sottounità su cui la lasci, evidenziata
  mentre trascini. In Impostazioni › Editor si può scegliere "Dove le lascio", e allora le immagini si
  ridimensionano dagli angoli.
- Con il pannello Arricchimento aperto, un clic su un'immagine del testo la seleziona fra i media.
