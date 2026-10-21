# Piano 3 · Esporta PDF

Approvato da Attilio sull'anteprima `/mnt/project-files/studio/4.3.2b3/anteprima-esporta-pdf.pdf`
(se non la vedi, valgono le misure qui sotto).

## Com'è oggi

- Il menu Esporta della lezione (`frontend/src/routes/lessons.tsx:413-419`) ha Markdown, Tutti i dati
  (zip), Solo le fonti (zip), Includi lo stato di studio.
- `GET /lessons/{id}/export` (`rt/api/routers/lessons.py:211`) fa `markdown` o `zip`. Il Markdown viene
  da `final_markdown(lesson_dir)` (`rt/storage/export.py`): documento finale o anteprima.
- RT scarica già un Chromium di Playwright per le catture delle visualizzazioni
  (`ensure_capture_browser`, `rt/desktop.py:106`) e lo avvia in `snapshot`
  (`rt/llm/enrichment_media.py:88-100`, con il ripiego su Chrome installato sul Mac).

## Cosa deve succedere

Voce **PDF** nel menu Esporta, dopo Markdown, con la stessa disponibilità e lo stesso suggerimento
d'anteprima di Markdown. Scarica `<stesso nome del Markdown>.pdf`.

### Come si fa il PDF

1. **Pagina di stampa nel frontend**: rotta nuova `/lezioni/:id/stampa` (`handle: bare`, nessuna
   barra) che mostra il documento finale (stesso testo di `?format=markdown`, esposto con un endpoint
   o un campo esistente) con lo stesso rendering di Markdown, formule (temml) e immagini di
   `DocumentView`, ma con l'impaginazione qui sotto. Quando testo, formule e tutte le immagini sono
   caricati imposta `document.body.dataset.ready = '1'`.
2. **Backend**: `format=pdf` in `export_lesson`. Avvia il browser delle catture (estrai da `snapshot`
   una funzione comune `launch_capture_browser(p)` e usala in tutti e due i posti), crea una sessione
   (`create_session()` in `rt/api/auth.py`) e la mette come cookie nel contesto, apre
   `http://127.0.0.1:<porta del server>/lezioni/<id>/stampa`, aspetta `body[data-ready="1"]`
   (al massimo 60 s), poi `page.pdf(format='A4', prefer_css_page_size=True, print_background=True)`
   con il numero di pagina in fondo al centro (`footer_template`, 8 px grigio). Chiude la sessione.
3. Se il browser non c'è ancora (download in corso o fallito): 409 `pdf_browser_missing` con
   "Il browser per il PDF si sta ancora scaricando. Riprova tra poco." e il frontend mostra il
   messaggio. Il PDF si fa in un thread, senza bloccare il server.

### Impaginazione (CSS di stampa, solo nella pagina di stampa)

- A4, margini 20 mm sopra, 18 mm ai lati e sotto.
- In cima: riga piccola grigia "Materia · data", poi il titolo (19 pt).
- Testo 10,5 pt, interlinea 1,5, giustificato con sillabazione. Titoli `##` 14 pt e `###` 11,5 pt,
  sans-serif, mai in fondo alla pagina da soli (`break-after: avoid`).
- Timecode: in grigio 8,5 pt accanto al titolo della sottounità, non su una riga sua.
- **Immagini**: le immagini consecutive (una per paragrafo, anche separate solo da righe vuote) formano
  una griglia a 2 colonne, spazio 4 mm in verticale e 5 mm in orizzontale. Ogni immagine è larga
  mezza colonna di testo (circa 85 mm).
  - Numero dispari: l'ultima va da sola al centro, sempre larga mezza colonna.
  - Un'immagine sola: mezza colonna, al centro (mai a tutta larghezza).
  - Altezza massima 95 mm (`object-fit: contain`): le verticali non riempiono la pagina.
  - Bordo sottile grigio chiaro, angoli 1,2 mm. Mai spezzata fra due pagine (`break-inside: avoid`).
  - Sotto ogni immagine, centrato in grigio 8 pt: "pag. N" se l'alt finisce con "pagina N",
    altrimenti niente.
- Niente pulsanti, niente evidenziazioni di studio, niente link al lettore audio.

### Peso delle immagini (zoom senza file pesante)

- Le immagini entrano nel PDF ridotte a **1600 px sul lato lungo** (circa 480 dpi a 85 mm: si legge
  bene anche ingrandendo 3 volte). Le più piccole restano come sono.
- Formato: JPEG qualità 82, tranne le immagini con trasparenza o quelle che in PNG pesano meno (slide
  con pochi colori): restano PNG.
- La pagina di stampa le chiede con un parametro nuovo dell'endpoint delle immagini,
  `GET /lessons/{id}/assets/images/{name}?max=1600` (Pillow, risultato in cache in
  `<data>/cache/pdf-images/<sha>-1600.<ext>`). Senza `max` l'endpoint non cambia.
- Obiettivo: una lezione come quella dell'anteprima (25 slide, 17 pagine) sotto i 6 MB.

## Test

- Pytest:
  - `?max=1600` riduce un PNG 3000×1700 a 1600 px di lato lungo, sceglie JPEG per una foto e PNG per
    un'immagine con trasparenza, usa la cache la seconda volta;
  - `format=pdf` con `page.pdf` simulato: apre la rotta di stampa con il cookie di sessione e restituisce
    `application/pdf` con il nome giusto; senza browser risponde 409 `pdf_browser_missing`;
  - (se Chromium è disponibile, altrimenti salta solo questo) un PDF vero di una lezione finta con
    tre immagini: tre immagini nel PDF, nessuna più larga di 1600 px.
- Vitest:
  - griglia: 2 immagini → una riga; 3 → due righe con l'ultima al centro; 1 → al centro a mezza
    larghezza; testo fra due immagini → due griglie separate;
  - didascalia "pag. 34" dall'alt, nessuna didascalia senza "pagina N";
  - `data-ready` solo dopo il caricamento delle immagini;
  - voce PDF nel menu con lo stesso stato di Markdown.

## Changelog

- Esporta PDF: la lezione in A4, con le immagini due per riga a mezza pagina, leggibili anche
  ingrandendo.
