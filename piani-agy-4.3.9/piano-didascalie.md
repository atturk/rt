# Piano: didascalie delle immagini (titolo della slide + riferimento discreto)

Decisione di Attilio (2026-11-16): la didascalia è il **titolo della slide**; numero di pagina e nome del
documento compaiono solo quando servono, piccoli e in grigio. Nessuna chiamata LLM in più.

## Il problema oggi
- L'alt Markdown delle pagine dei materiali è `"<nome file>, pagina N"`. Il PDF di stampa mostra solo `pag. N`
  (`frontend/src/lib/printDocument.ts`, `extractPageCaption`). Una foto è un documento di una pagina: ogni foto
  diventa "pag. 1". Due PDF nella stessa sezione danno due "pag. N" diverse. I nomi dei file sono brutti
  (`PHOTO-2026-11-16-19-24-48 5.jpg`, `Lez2parte1-segnale e informazione.pdf`).
- Il modello visivo restituisce già `slide_title` e `alt_text` (`ImageDescription`), ma `_describe` in
  `rt/core/materials.py` li unisce nel testo e li perde.

## Formato dell'alt (unico punto di verità)
`"<titolo> — <nome file>, pagina N"`; senza titolo resta `"<nome file>, pagina N"` (lezioni vecchie compatibili).
Per i file immagine (una sola pagina, `file_type(...) == 'immagine'`) si omette `, pagina 1`:
`"<titolo> — <nome file>"`. Separatore: ` — ` (spazio, trattino lungo, spazio); il parser divide sull'ULTIMO.
Il titolo si pulisce: niente `[ ] \ `, a capo e ` — `; spazi compattati; `N/A`/vuoto = nessun titolo;
massimo 90 caratteri con `…`.

## Backend
1. **Titolo della pagina** (campo `titolo` in `page-N.json` / `pages.json`):
   - Pagine descritte dal modello visivo: `_describe` restituisce anche `slide_title` e `alt_text`;
     `titolo = slide_title` se valido, altrimenti la frase `alt_text` accorciata. Salvare anche
     `slide_title`/`alt_text` in `descrizione.json` dei file immagine (oggi solo `ocr_text`) e riusarli.
   - PDF con testo: in `_extract`/`_extract_text`/`_extract_images`, `page.get_text("dict")`: la riga col
     carattere più grande nel 40% alto della pagina, 3-120 caratteri, non solo numeri.
   - PPTX: `slide.shapes.title.text` se c'è. DOCX/TXT/MD: il titolo (Heading) che apre il blocco, se c'è.
   - Cache vecchie senza `titolo`: per i file immagine usare la prima riga di `testo` (era `slide_title`)
     se non è `N/A`; per gli altri nessun titolo (niente ri-estrazione automatica).
2. **Helper unico** in `rt/core/materials.py` (o nuovo `rt/core/captions.py`):
   `page_alt(source_file, page_number, titolo=None, single_page=False) -> str` col formato sopra, e
   `clean_caption(text) -> str|None`. Sostituire TUTTE le f-string `", pagina {n}"` degli alt:
   `rt/pipeline/material_mapping.py` (4 punti), `rt/pipeline/material_attachments.py`,
   `rt/pipeline/add_images.py` (3 punti), `rt/services/archive_service.py:401`,
   `rt/services/editor_media_service.py:125`. Dove la pagina è a portata, passare `page.get('titolo')`.
3. **Lezioni già fatte**: in `rt/pipeline/build.py`, prima di scrivere `![alt](...)`, se l'alt non contiene
   ` — ` e la description ha `source` `material:<id>:<n>`, ricostruire l'alt con l'helper usando il `titolo`
   della pagina in cache (se c'è). Così la prossima ricostruzione sistema le lezioni vecchie senza costi.
4. `rt/services/editor_media_service.py:320` (etichetta `Pag. N`): continua a funzionare; se c'è il titolo
   usare quello come label.

## Frontend
1. `parseImageAlt` (`components/images/imageUtils.ts`): restituisce anche `caption?: string` (parte prima
   dell'ultimo ` — `); `docName`/`pageNumber` come oggi sul resto. `ImageItem` prende `caption`.
2. **PDF di stampa** (`printDocument.ts`): la `figcaption` ha due righe:
   - riga 1 (testo normale): `caption`; se manca, `Figura N` (contatore progressivo nel documento, solo per
     le immagini senza titolo);
   - riga 2 (piccola, grigia, classe `pdf-image-ref`): `p. N` solo se c'è `pageNumber`; preceduta dal
     **nome breve del documento** solo se nella stessa griglia ci sono immagini di documenti diversi.
     Nome breve: senza estensione, `_` e `-` → spazio, spazi compattati, max 40 caratteri con `…`.
   - Le foto singole: solo il titolo, nessun numero.
   Sostituire `extractPageCaption` (aggiornare `printDocument.test.ts`) e aggiungere lo stile in
   coda al CSS di stampa (stesso file dove sta `.pdf-image-caption`).
3. **App**: `ImageViewer.tsx` (riga ~78): didascalia = `caption` in evidenza + sotto `docName, pagina N` in
   grigio; `imageStripDOM.ts`: attributo `title` della miniatura = `caption`; il badge `p. N` resta.
4. Test: aggiornare/aggiungere casi in `imageUtils.test.ts`, `printDocument.test.ts`, `ImageViewer.test.tsx`
   (titolo con virgole, nome file con ` — `, foto senza pagina, due documenti nella stessa griglia).
   Backend: test per `page_alt`/`clean_caption` e per il titolo PDF (pymupdf su un PDF generato nel test).

## Fuori da questo lavoro
- Didascalia modificabile nell'editor e nome breve della fonte modificabile (campo su `Source`): dopo.
- Nessuna verifica Playwright: la fa Claude.
