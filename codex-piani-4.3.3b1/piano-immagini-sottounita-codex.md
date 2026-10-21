# Piano 1 · Immagini della sottounità: bottone con la graffetta al posto del blocco

Agente: **Codex**. Wireframe approvati da Attilio: https://claude.ai/artifact/FhSTW8rDPPtGKhhpzdNzJ3
(schermate 1-5). Il codice di riferimento è quello di `claude/rt-4.3.3-beta` (contiene la 4.3.2 con
Esporta PDF).

## Cosa cambia per l'utente

1. Il blocco espandibile con la graffetta ("1 pagina · file.pdf, p. 2" + striscia) **sparisce**.
2. Al suo posto, nella riga del timer di ogni sottounità, c'è un **bottone a sinistra del timer**:
   icona graffetta (Lucide `Paperclip`) + il numero delle immagini della sezione. Suggerimento:
   "Mostra le immagini" / "Nascondi le immagini". Se la sezione è vuota il bottone non c'è.
3. Clic sul bottone: sotto la riga del timer si apre la **sezione**, cioè le miniature in fila con
   scorrimento orizzontale e il badge "p. N" come oggi. Niente intestazione, niente nome del file,
   niente conteggio "N pagine": solo le immagini in riga. Secondo clic: si chiude. Bottone attivo =
   sfondo verde chiaro come gli altri pulsanti attivi.
4. L'impostazione **"Immagini trascinate" (Sotto il titolo / Dove le lascio) sparisce** da
   Impostazioni › Scorciatoie, insieme alla preferenza `editor.image-drop`.
5. Trascinare un'immagine (file dal Finder/Esplora, miniatura del pannello Arricchimento, miniatura
   di una sezione aperta):
   - durante il trascinamento **ogni** sottounità mostra il bottone (tratteggiato se la sezione è
     vuota, senza numero); quello sotto il puntatore si evidenzia;
   - rilascio **sul bottone** (o dentro una sezione aperta): l'immagine va nella sezione di quella
     sottounità, in coda;
   - rilascio **nel testo**: l'immagine va in quel punto, come oggi in modalità "Dove le lascio",
     con le maniglie per ridimensionarla. Indicatore di inserimento: la linea verde di oggi.
6. Una miniatura di una sezione aperta si può trascinare: nel testo (diventa immagine nel testo),
   sul bottone o nella sezione aperta di un'altra sottounità (si sposta lì), o nella stessa sezione
   per cambiarne l'ordine. Spostare = togliere dal posto di prima, mai duplicare.
7. Un'immagine nel testo trascinata sul bottone di una sottounità torna nella sezione.
8. L'**auto-assegnazione** (material_mapping, add-images, place_uploaded_images, il pulsante "Aggiungi
   alla lezione" del pannello) mette sempre le immagini nella sezione. Nessun cambio lato backend
   qui: già oggi scrivono `placement.json` → `units`, che è proprio la sezione.
9. Lettura (vista HTML, `DocumentView`) e Studio (`Study.tsx`): stesso bottone e stessa sezione che
   si apre; lì non si trascina.
10. Esporta PDF: invariato rispetto alla 4.3.2 (sezione = griglia a due colonne sotto il titolo;
    immagini nel testo dove sono, con la larghezza scelta). Verifica solo che continui a valere.

## Modello dei dati (nessun formato nuovo)

Già oggi il Markdown dell'anteprima distingue i due casi (`rt/services/document_edit_service.py`,
`_parse_structure`):

- righe immagine **subito dopo il timecode**, prima di qualsiasi testo → `unit.images` →
  `placement.json` `units[uid]`: **è la sezione**;
- righe immagine **dentro il testo** → contenuto dell'unità nella bozza: **immagini nel testo**.

Unico caso ambiguo: un'immagine nel testo messa prima del primo paragrafo verrebbe letta come
sezione. Regola nuova: **un'immagine nel testo ha sempre la larghezza `#w=<px>`**, e una riga
immagine con `#w=` non è mai della sezione.

- Frontend: ogni inserimento nel testo scrive `#w=` (larghezza iniziale: quella naturale
  dell'immagine, massimo 480 px; se non nota, 480).
- Backend: in `_parse_structure`, `if not unit.content_lines and IMAGE_LINE_RE.match(stripped)`
  diventa "e la destinazione non contiene `#w=`". Le immagini sotto il titolo di sezione `##`
  (macro) restano come sono.
- Aggiorna il docstring del modulo.
- Le immagini già nel testo senza `#w=` (lezioni vecchie) restano nel testo e si vedono intere,
  con le maniglie: nessuna migrazione.

## Frontend: file e interventi

Editor (CodeMirror, `LessonEditor.tsx`):

- `lessonImageStrips.ts`: oggi trasforma **qualsiasi** serie di righe immagine in una striscia.
  Deve farlo **solo** per le righe immagine della sezione (stessa regola del backend: dopo il
  timecode, prima del testo, senza `#w=`). Il blocco viene sostituito da un widget che è la
  sezione: vuoto (altezza 0) se chiusa, la riga di miniature se aperta. Il cursore dentro il blocco
  oggi mostra il Markdown: non serve più, il blocco è atomico (`Decoration.replace` + `atomicRanges`)
  così non si modifica a mano per errore.
- Il bottone: widget nella riga del timecode, **prima** del timecode (vedi come `lessonShortcuts.ts`
  piazza le scorciatoie dopo il timecode; qui `side: -1` all'inizio della riga del timecode, o un
  widget dedicato nello stesso StateField). Stato aperto/chiuso per unità in uno `StateField`
  (`toggleUnitImages` effect); non entra mai nel Markdown.
- `imageStripDOM.ts`: togli intestazione, freccia, graffetta e nome; resta la "rail" con frecce di
  scorrimento e miniature con badge. Il clic sulla miniatura resta com'è (pannello aperto →
  `rt-media-select`; chiuso → visore). Rimuovi `getStripClosedPreference` /
  `setStripClosedPreference` / evento `rt-strip-toggle` e la preferenza `strip_closed`.
- `lessonImages.ts`:
  - `dropTarget(state, pos, mode)`: togli `mode`. Due bersagli: `section` (unità, posizione =
    fine delle righe della sezione) e `text` (posizione libera come oggi in `free`, ma mai dentro
    il blocco della sezione né prima del timecode: in quei casi va subito dopo la sezione).
  - Il bersaglio `section` si ottiene solo rilasciando sul bottone o sulla sezione aperta
    (`event.target.closest('[data-unit-images]')` con l'id dell'unità); tutto il resto è `text`.
  - Durante `dragover` aggiungi una classe sull'editor (`rt-dragging-images`) che fa comparire i
    bottoni delle sezioni vuote (tratteggiati); `dragleave`/`drop`/`dragend` la tolgono.
  - Incolla (`paste`) e `EDITOR_INSERT_IMAGES_EVENT` (pulsante "Inserisci al cursore" del pannello):
    vanno nel testo al cursore, con `#w=`.
  - Spostamento di una miniatura della sezione: nuovo tipo di drag (`RT_SECTION_IMAGE_DRAG_TYPE`,
    `{name, fromUnit}`); al rilascio un'unica transazione toglie la riga dalla sezione di origine e
    la inserisce nella destinazione (un solo passo di annulla).
  - Un'immagine nel testo trascinabile verso un bottone: stessa cosa, riga tolta dal testo e messa
    nella sezione senza `#w=`.
- `lessonUnits.ts`: `attachResizeHandles` sempre attivo per le immagini nel testo (niente più
  controllo di `mode`); `findInsertPosition` senza preferenza.
- `settings/shortcuts.tsx` (+ test): togli il campo "Immagini trascinate".
- `lib/preferences`: se c'è un elenco delle preferenze note, togli `editor.image-drop` e
  `strip_closed`.

Lettura e Studio:

- `DocumentView.tsx` e `Study.tsx` usano `mountDocumentImageStrips(root)`, che oggi raggruppa
  tutti i paragrafi di sole immagini. Deve raggruppare solo quelli della sezione. Per saperlo senza
  indovinare dall'HTML, il backend aggiunge a ogni `DocumentSection` il campo
  `immagini_sezione: list[str]` (nomi file in `assets/images`, in ordine), preso da
  `images_for_document(...).by_unit`. `mountDocumentImageStrips(root, sections)` toglie i
  paragrafi immagine subito dopo l'intestazione che corrispondono a quell'elenco, aggiunge il
  bottone in `.rt-unit-meta` **prima** del timecode e la sezione apribile sotto l'intestazione.
  Le altre immagini restano nel testo come immagini normali.
- Rigenera lo schema OpenAPI (`python scripts/export_openapi.py && (cd frontend && npm run gen:api)`).

Stile (in fondo a `frontend/src/index.css`, blocco nuovo `/* Immagini della sottounità */`; non
toccare `.rt-panel-container`, lo cambia agy):

- bottone: altezza 30 px come il timecode, bordo 1 px `--border`, raggio 8 px, icona 16 px, numero
  `text-meta`; attivo: sfondo e testo verdi come `IconButton active`; tratteggiato in trascinamento;
  evidenziato (anello verde) sotto il puntatore.
- sezione: miniature alte ~120 px come la striscia di oggi, gap 10 px, nessun bordo attorno al
  gruppo. Animazione di apertura breve (altezza + opacità, 160 ms), disattivata con
  `prefers-reduced-motion`.

## Test

- `tests/test_document_edit*.py`: un'immagine con `#w=` subito dopo il timecode resta nel testo e non
  entra in `units`; senza `#w=` entra in `units` come oggi.
- API documento: `immagini_sezione` presente e uguale a `placement.json` `units[uid]`.
- vitest:
  - la striscia appare solo per le righe della sezione, non per le immagini nel testo;
  - bottone con il numero giusto, assente con sezione vuota, presente (tratteggiato) durante il
    trascinamento;
  - rilascio sul bottone → riga aggiunta alla sezione dell'unità giusta;
  - rilascio nel testo → riga con `#w=` in quel punto;
  - spostamento sezione → altra sezione e sezione → testo in una sola transazione;
  - `DocumentView`: bottone prima del timecode, sezione chiusa di default, si apre al clic;
  - Impostazioni senza "Immagini trascinate".
- e2e esistenti che usano la striscia o la preferenza: aggiornali, non disattivarli.

## Fuori da questo piano

Pannello Arricchimento (larghezza, scorrimento all'immagine selezionata) e Archivio: li fa agy.
Non toccare `LessonPanel.tsx`, `EnrichmentPanel.tsx`, `MediaGallery.tsx`, `archive/*`,
`rt/services/archive_service.py`, `rt/core/archive.py`, `rt/pipeline/add_images.py`.
