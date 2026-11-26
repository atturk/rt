# Piano agy: immagini più leggere (punto 3) e Fonti comprimibili con foto raggruppate (punto 4)

Base: main (4.3.9.1). Prima di tutto: `git pull` di questo branch. Solo codice e test unitari, niente verifiche Playwright.

## A. Immagini dei materiali in JPEG (punto 3)

Oggi `rt/core/materials.py`:
- `_png_image` converte ogni foto in PNG senza perdita, a piena risoluzione: un jpg da 1 MB diventa un PNG da 4,5-8 MB;
- le pagine PDF diventano `page.get_pixmap(matrix=2).tobytes('png')`, circa 1,7 MB per una slide 1920×1080.

Lo stesso file viene poi copiato in `assets/images/<hash>.png` della lezione: la lezione di Polimeni pesa 316 MB.

Da fare:
1. Nuova funzione `_page_image(data_or_pixmap) -> (bytes, ext)`:
   - foto, immagini di docx e pptx: `exif_transpose`, RGB, lato lungo al massimo 2000 px (`Image.thumbnail`, LANCZOS), JPEG qualità 85, `optimize=True` → `.jpg`;
   - immagini con trasparenza o molto piccole (lato < 64 px): restano PNG;
   - pagine PDF: `pix.tobytes('jpg', jpg_quality=85)` con la stessa matrix 2 → `.jpg`.
2. Il nome del file in cache diventa `page-{n}-{i}{ext}`, in `_material_pages`. Le cache esistenti in `.png` devono continuare a funzionare: niente migrazione, si legge quello che c'è.
3. Adattare chi presuppone `.png`:
   - `rt/core/archive.py:133`: la regex accetta `png|jpg`;
   - `archive.py:216`: `page_image_path(sha, 'page-1-1.png')` cerca anche `.jpg`;
   - `rt/services/archive_service.py:313`;
   - `rt/core/image_extract.py:114`;
   - la route `/archive/{sha}/pages/{n}.png` in `rt/api/routers/archive.py:141` serve il file che esiste, con il media type giusto;
   - `rt/api/routers/images.py`: i fallback `page-{num}-1.png` e i `media_type`.
4. `save_raw_image(..., ext)`: chi copia le pagine dei materiali nella lezione (`material_mapping.py`, `material_attachments.py`, `editor_media_service.py`, `add_images.py`) passa l'estensione del file sorgente. Aggiungere un helper `image_ext(data)` che la ricava dai magic bytes (`\xff\xd8` → `.jpg`).
5. Data URL verso i modelli: `_describe` in `materials.py` (oggi forza `image/png`) e `rt/pipeline/review.py:529` usano il mime reale. `decision_images.py` lo fa già.
6. Test:
   - una foto 4000×3000 diventa un jpg con lato 2000 e meno di 1,5 MB;
   - una pagina PDF diventa jpg;
   - una cache esistente con `page-1-1.png` continua a essere servita e copiata;
   - la route dell'archivio serve sia png sia jpg.

## B. Fonti nei Dettagli (punto 4)

File: `frontend/src/components/lesson/panels/SourcesSection.tsx` (+ test).

Attenzione: il branch `claude/project-thread-fkzrud` modifica lo stesso file («riga Documenti spiegata»). Se è già in main, parti da lì; altrimenti tieni le modifiche piccole e separate, per facilitare il merge.

1. L'intestazione «Fonti» diventa un bottone comprimibile:
   - chevron e numero di fonti («Fonti · 19»);
   - stato ricordato per lezione in localStorage, con try/catch;
   - aperta di default; chiusa di default se le fonti sono più di 8.
   - Il «+» resta sempre visibile.
2. Foto raggruppate: le fonti `tipo === 'materiale'` che sono immagini singole (estensione jpg, jpeg, png o heic) si raccolgono in un'unica riga «Foto · 17», con icona Image e chevron. Aperta, la riga mostra una griglia di miniature (3 per riga nel pannello, 4 su schermi larghi):
   - miniatura dalla route dell'archivio `/api/v1/archive/{impronta}/pages/1.png`, con `loading="lazy"` e bordo arrotondato;
   - sotto ogni miniatura l'ora dello scatto, ricavata dal nome `photo_YYYY-MM-DD_HH-MM-SS` → «14:29»; se il nome non la contiene, il nome accorciato. Il nome completo va nel title;
   - puntino «Non ancora usata» e stellina principale come nelle righe attuali;
   - al passaggio del mouse, o con il focus, un menu ⋯ su ogni miniatura: Modifica, Usa come principale, Togli. Riusa le stesse azioni e le stesse conferme delle righe attuali;
   - clic sulla miniatura: apre l'anteprima della pagina, come fa oggi Info nei Media (se esiste un componente riusabile), altrimenti apre il menu.
3. Il raggruppamento scatta solo con almeno 3 foto; con meno restano righe normali.
4. Test (vitest):
   - 17 fonti foto → una riga «Foto · 17» e 17 miniature dopo l'apertura;
   - l'ora è ricavata dal nome;
   - con 2 foto non c'è raggruppamento;
   - comprimi/espandi Fonti;
   - il menu ⋯ chiama Togli con la conferma.
