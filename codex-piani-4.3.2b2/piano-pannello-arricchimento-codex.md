# Piano 10 · Pannello Arricchimento: Archivio, Da descrivere, nuova barra della selezione

Giro 2. Dipende dai piani 6, 7 e 9 (già uniti). Wireframe: tavola "Pannello Arricchimento con
Archivio" del canvas https://claude.ai/artifact/P1KzSVbQfXixTkEJ1kPBjf.

## Com'è oggi

- `EnrichmentPanel.tsx` ha la sezione "Media della lezione" (scheda di upload, ricerca sul web,
  ritaglio dentro il pannello con `MediaCropView`, galleria `MediaGallery`, barra
  `MediaSelectionBar`) e la sezione "Idee per la lezione".
- `MediaSelectionBar.tsx` è una barra scura (`bg-foreground`) con: N selezionate, Seleziona tutte,
  Inserisci al cursore, Colloca in automatico, Togli dal testo, Annulla. Ad Attilio non piace: non si
  allinea con il resto dell'app.
- Non si può descrivere a mano un'immagine né eliminarla dalla lezione. Il ritaglio sta nel pannello
  (pulsante Scissors sulla miniatura).

## Cosa deve succedere

1. **Pulsante Archivio in cima al pannello**, prima di "Media della lezione". Stesso stile dei
   pulsanti Classificatore e Verifiche in Dettagli (`DetailsPanel.tsx:445-484`):
   - `Button variant="outline"` a tutta larghezza, icona Archive, "Archivio" e sotto, in grigio,
     "124 file · 2 PDF da continuare" (`GET /archive/summary?materia=<materia della lezione>`; senza
     da continuare solo "124 file");
   - porta a `/archivio?da=<lessonId>`.
   È l'unica eccezione al "niente testo": va bene così.
2. **Filtri dei media:** due pulsanti a icona accanto al titolo della sezione, Tutti (LayoutGrid) e
   Da descrivere (con il numero, icona con il puntino). Le immagini senza descrizione vision hanno un
   puntino arancione nell'angolo della miniatura.
   - Backend: `LessonImage.descritta: bool` in `GET /lessons/{id}/images`. È falso per le voci senza
     `summary_keywords`, `ocr_text` e `visual_elements` (le immagini dell'editor `editor:` e le
     pagine salvate con `pages_only`).
3. **Nuova barra della selezione:** `MediaSelectionBar` usa `components/ui/selection-bar.tsx` del
   piano 7 (barra bianca con bordo, conteggio grigio "3 scelti", pulsanti a icona 32 px
   trasparenti). Pulsanti, in ordine:
   - **Descrivi** (ScanEye): attivo se tra le scelte c'è almeno un'immagine non descritta; descrive
     solo quelle. Endpoint nuovo `POST /lessons/{id}/media/describe {names}`, job che usa
     `describe_new_images` e la descrizione dell'archivio se c'è (piano 6). Descrivere non sposta
     niente.
   - **Posiziona** (WandSparkles): il "Colloca in automatico" di oggi.
   - **Inserisci al cursore** (ArrowDownToLine): come oggi, disattivato con "Clicca nel testo dove vuoi
     le pagine".
   - **Ritaglia** (Crop): solo con una immagine. Porta a
     `/archivio?da=<id>&file=<sha>&pagina=<n>&ritaglia=1`, cioè la voce dell'archivio dell'immagine
     (per le pagine dei materiali il file e la pagina; per le immagini singole il loro sha e pagina 1).
   - **Togli dal testo** (ImageMinus, immagine col meno): come oggi, attivo se qualcuna è nel testo.
   - **Elimina dalla lezione** (Trash2, rosso, conferma breve "Eliminare dalla lezione?"): toglie le
     immagini dal testo e dai media della lezione (voce di `descriptions.json`, placement, file in
     `assets/images` se nessun'altra voce lo usa). Restano nell'archivio. Endpoint nuovo
     `POST /lessons/{id}/media/delete {names, lease_token}`; con l'editor aperto toglie anche dal
     testo con `rt-editor-remove-images`.
   - Niente "Seleziona tutte" e "Annulla" come pulsanti: restano Cmd/Ctrl+A ed Esc.
4. **Ritaglio fuori dal pannello:** togli la vista di ritaglio da `EnrichmentPanel` e il pulsante
   Scissors sulle miniature di `MediaGallery`. `MediaCropView` resta, lo usa la pagina Archivio.
5. Le operazioni sul file (ignora pagine, ritaglia, elimina per sempre) stanno solo nell'Archivio;
   nel pannello restano quelle sulla lezione. Descrivi sta in tutti e due.

## Test

- Pytest:
  - `descritta` vero e falso;
  - `media/describe` descrive solo le non descritte e usa la descrizione dell'archivio senza
    chiamare la vision;
  - `media/delete` toglie voce, placement e testo, lascia il file se un'altra voce lo usa, e lascia
    l'archivio intatto.
- Vitest:
  - pulsante Archivio con i conteggi e il link con `da`;
  - filtro Da descrivere con il numero;
  - puntino sulle non descritte;
  - barra: Descrivi disattivato se tutte descritte, Ritaglia solo con una e link giusto, Elimina con
    conferma;
  - niente più pulsante Scissors sulle miniature.

## Changelog

- Pannello Arricchimento: pulsante Archivio in cima, filtro "Da descrivere", e una barra della
  selezione nuova con Descrivi, Posiziona, Inserisci, Ritaglia, Togli dal testo ed Elimina dalla
  lezione.
