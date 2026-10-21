# Piano 2 · Pannello Arricchimento: più largo trascinando, immagine scelta al centro

Agente: **agy**. Due ritocchi al pannello Arricchimento.

## A. Allargare il pannello trascinando il bordo sinistro

Oggi la larghezza è fissa a `24rem` (`.rt-panel-container` in `frontend/src/index.css`) e lo stesso
valore è ripetuto in altri punti che lasciano spazio al pannello.

1. Una variabile CSS `--rt-panel-width` su `:root`, predefinita `24rem`. Sostituisci `24rem` con la
   variabile in:
   - `.rt-panel-container` (`width: min(calc(var(--rt-panel-width) - 8px), calc(100vw - 16px))`);
   - `frontend/src/routes/lessons.tsx` (padding destro del documento quando il pannello è aperto);
   - `frontend/src/components/lesson/AudioPlayer.tsx` (posizione del player);
   - `frontend/src/components/lesson/panels/ReviewPanel.tsx` (toast);
   - ogni altro `24rem` / `12rem` legato al pannello (`grep -rn "24rem\|12rem" frontend/src`).
2. In `LessonPanel.tsx`, **solo con `view === 'arricchimento'`** e solo da `md` in su: una maniglia
   sul bordo sinistro dell'`aside` (striscia invisibile di 6 px, `cursor: ew-resize`, al passaggio
   una linea di 2 px colore `--border`). Trascinando, la larghezza segue il puntatore; usa lo
   stesso schema della barra laterale dell'Archivio (`ArchivePage.tsx`, `rt.archive.detailWidth`).
   - minimo 24rem, massimo `min(60vw, 100vw - 480px)`;
   - salvata in `localStorage` (`rt.panel.enrichment.width`, letture e scritture in try/catch);
   - la variabile si imposta su `document.documentElement` mentre il pannello Arricchimento è aperto
     e torna a `24rem` alla chiusura o cambiando pannello, così il testo si sposta di conseguenza;
   - doppio clic sulla maniglia: torna a 24rem.
   - accessibilità: `role="separator"`, `aria-orientation="vertical"`, `aria-label="Larghezza del
     pannello"`, frecce sinistra/destra = ±32 px.
3. Le miniature del pannello si allargano con il pannello (griglia fluida già presente: controlla
   che le colonne della vista a griglia aumentino invece di stirarsi).

## B. Clic su un'immagine della lezione: il pannello la porta al centro

Oggi (`EnrichmentPanel.tsx`, `onMediaSelect`) l'immagine viene selezionata e portata in vista con
`block: 'nearest'`. Va cambiato così:

1. `scrollIntoView({ behavior: 'smooth', block: 'center' })`.
2. Se l'immagine è dentro un gruppo chiuso (fonte con la freccia chiusa in `MediaGallery.tsx`),
   prima apri il gruppo, poi scorri.
3. Breve animazione sulla miniatura: anello verde (`box-shadow` 0 0 0 3px con il verde degli
   elementi attivi) che pulsa due volte in ~700 ms e poi resta il normale stato "selezionato".
   Classe `rt-media-flash` aggiunta e tolta a fine animazione (`animationend`); con
   `prefers-reduced-motion` niente pulsazione, solo la selezione.
4. Funziona dai tre punti che inviano `rt-media-select`: immagine nel testo dell'editor, miniatura
   della sezione della sottounità (vedi piano 1 di Codex: il nome dell'evento resta lo stesso),
   miniatura nella lettura.

## Test

- vitest `LessonPanel`/`EnrichmentPanel`: la maniglia c'è solo con Arricchimento; trascinando cambia
  `--rt-panel-width` entro i limiti; il valore viene salvato e riletto; chiudendo torna a 24rem.
- vitest `EnrichmentPanel`/`MediaGallery`: `rt-media-select` su un'immagine in un gruppo chiuso apre
  il gruppo, chiama `scrollIntoView` con `block: 'center'` e aggiunge `rt-media-flash`.

## File

`frontend/src/components/lesson/LessonPanel.tsx`, `panels/EnrichmentPanel.tsx`,
`panels/MediaGallery.tsx`, `frontend/src/index.css` (solo il blocco `.rt-panel-container` e una
regola nuova per `rt-media-flash`), `routes/lessons.tsx`, `AudioPlayer.tsx`, `panels/ReviewPanel.tsx`
(solo la classe del toast).
