# Piano agy: immagini più leggere (A), Fonti comprimibili con foto raggruppate (B), pagine non collocate fuori dal testo + foto collocate per orario (C)

Base: main (4.3.9.1). Prima di tutto: `git pull` di questo branch. Solo codice e test unitari, niente verifiche Playwright.

## A. Immagini dei materiali in WebP (punto 3)

Attilio vuole il formato più efficiente possibile, anche per le pagine dei PDF: si usa WebP, che per le slide con testo è più piccolo e più nitido del JPEG.

Oggi `rt/core/materials.py`:
- `_png_image` converte ogni foto in PNG senza perdita, a piena risoluzione: un jpg da 1 MB diventa un PNG da 4,5-8 MB;
- le pagine PDF diventano `page.get_pixmap(matrix=2).tobytes('png')`, circa 1,7 MB per una slide 1920×1080.

Lo stesso file viene poi copiato in `assets/images/<hash>.png` della lezione: la lezione di Polimeni pesa 316 MB.

Da fare:
1. Nuova funzione `_page_image(data_or_pixmap) -> (bytes, ext)`:
   - foto, immagini di docx e pptx: `exif_transpose`, RGB, lato lungo al massimo 2000 px (`Image.thumbnail`, LANCZOS), WebP qualità 80, `method=6` → `.webp`;
   - immagini con trasparenza: WebP con alfa; molto piccole (lato < 64 px): restano PNG;
   - pagine PDF: pixmap con la stessa matrix 2 → PIL → WebP qualità 80, `method=6` → `.webp`. Il lato lungo resta al massimo 2000 px.
   - Fallback: se Pillow non ha il supporto WebP (`features.check('webp')`), JPEG qualità 85 → `.jpg`.
2. Il nome del file in cache diventa `page-{n}-{i}{ext}`, in `_material_pages`. Le cache esistenti in `.png` devono continuare a funzionare: niente migrazione, si legge quello che c'è.
3. Adattare chi presuppone `.png`:
   - `rt/core/archive.py:133`: la regex accetta `png|jpg|webp`;
   - `archive.py:216`: `page_image_path(sha, 'page-1-1.png')` cerca anche `.webp`/`.jpg`;
   - `rt/services/archive_service.py:313`;
   - `rt/core/image_extract.py:114`;
   - la route `/archive/{sha}/pages/{n}.png` in `rt/api/routers/archive.py:141` serve il file che esiste, con il media type giusto;
   - `rt/api/routers/images.py`: i fallback `page-{num}-1.png` e i `media_type`.
4. `save_raw_image(..., ext)`: chi copia le pagine dei materiali nella lezione (`material_mapping.py`, `material_attachments.py`, `editor_media_service.py`, `add_images.py`) passa l'estensione del file sorgente. Aggiungere un helper `image_ext(data)` che la ricava dai magic bytes (`RIFF....WEBP` → `.webp`, `\xff\xd8` → `.jpg`, altrimenti `.png`).
5. Verso i modelli si manda sempre PNG o JPEG, perché Jev non accetta WebP. `_describe` in `materials.py` (oggi forza `image/png`) e `rt/pipeline/review.py:529` passano dall'helper `normalize_image` di `rt/llm/decision_images.py`, che riconverte già WEBP in JPEG. Verificare anche `add_images.py` `_get_image_mime_type` e l'export PDF/HTML della lezione: WebKit e WebView2 leggono WebP, ma se l'export usa un'altra libreria va controllato.
6. Test:
   - una foto 4000×3000 diventa un webp con lato 2000 e meno di 600 KB;
   - una pagina PDF diventa webp ed è almeno 3 volte più piccola del PNG di oggi;
   - `_describe` riceve un data URL JPEG o PNG, mai WebP;
   - una cache esistente con `page-1-1.png` continua a essere servita e copiata;
   - la route dell'archivio serve png, jpg e webp con il media type giusto.

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

## C. Pagine non collocate fuori dal testo, foto collocate per orario (punto 5, scelta di Attilio)

Caso reale: un PDF da 249 pagine (tutto il corso) usato per una lezione su 3 argomenti. Il classificatore ha collocato 36 pagine e scartato 27 pagine fuori tema; 149 pagine e 13 foto sono rimaste «non collocate». Dalla 4.3.9 (PR #177) `rt/pipeline/build.py:173-177` mette le non collocate in testa alla macro: 79, 28 e 50 immagini senza testo sotto «## 1.», «## 2.» e «## 3.».

1. **Le non collocate non entrano più nel documento.**
   - In `material_mapping.py`, nel ciclo finale su `classified_records`: per `page.get("unplaced")` non chiamare `append_page_placements`. La voce di `descriptions.json` resta, con `unplaced=True`, così la pagina compare nei Media e in «Materiali non collocati».
   - In `build.py`: le immagini con `unplaced` non si scrivono. Va così anche per le lezioni esistenti, al prossimo build. Togliere le righe 173-177 che le accodano.
   - **Controllare il trascinamento dal pannello** «Materiali non collocati» verso un'unità (e «Colloca» nei Media): deve togliere `unplaced` dalla voce, o comunque fare vincere la scelta dell'utente, altrimenti il punto 1 farebbe sparire anche le pagine collocate a mano. Aggiungere un test.
2. **Foto collocate per orario.** Vale per le fonti materiale che sono foto singole (`file_type == 'immagine'`), prima del classificatore.
   - Ora dello scatto: EXIF `DateTimeOriginal`, altrimenti dal nome (`photo_YYYY-MM-DD_HH-MM-SS`, `IMG_YYYYMMDD_HHMMSS`, `PXL_YYYYMMDD_HHMMSSmmm`).
   - Inizio della registrazione: dal nome dell'audio (`audio_YYYY-MM-DD_HH-MM-SS`, stessi formati), altrimenti dal tag `creation_time` del file (ffprobe, se disponibile). Con più parti audio si somma l'offset di ogni parte.
   - Offset = scatto − inizio registrazione. Se l'ora non è nota, o l'offset è fuori da [−60 s, durata + 120 s], si usa il classificatore come oggi.
   - Altrimenti la foto va nell'unità i cui segmenti contengono quell'istante: si usano `segments.json` (start/end) e `start_segment_id`/`end_segment_id` delle unità dell'outline. Se l'offset cade tra due unità, va in quella che inizia prima.
   - La decisione per orario vince sul classificatore: la slide fotografata in quel momento è quella di cui parla il prof.
   - Una riga in `api.log` per ogni foto: `foto <nome> scattata <hh:mm:ss> → offset <mm:ss> → unità <id> (per orario)`.
   - Esempio reale: audio_2026-11-26_14-27-18.ogg (64 min) e photo_2026-11-26_14-29-33.jpg → offset 2:15, nella prima unità.
3. Test:
   - le non collocate non compaiono nel markdown, ma sono in `descriptions.json` e in `material_attachments.unplaced`;
   - una non collocata trascinata in un'unità compare nel markdown dopo il build;
   - una foto con l'ora nel nome va nell'unità giusta e non chiama il classificatore;
   - una foto fuori dalla finestra, o senza ora, usa il classificatore;
   - offset con 2 parti audio.
