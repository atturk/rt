# Piano per Codex · 4.3.2b1 · Anteprima grande tenendo premuto (vista a griglia)

Base: `claude/rt-4.3.2-beta`. Dipende dal piano `piano-media-una-per-riga-codex.md` (prop `view` di `MediaGallery`, componente `MediaCell`): implementarlo dopo, sullo stesso branch.
File: `frontend/src/components/lesson/panels/MediaGallery.tsx` e `MediaGallery.test.tsx`.

## Richiesta (Attilio)
Nella vista a griglia le miniature sono piccole: per capire quali slide (o quale intervallo di slide) servono, tenendo premuto su una miniatura deve comparire un'anteprima grande della pagina.

## Comportamento
È una "sbirciata": compare finché tieni premuto e sparisce quando lasci, così si scorrono tante pagine in fretta senza aprire e chiudere il visore.

- **Mouse (Mac/Windows), solo vista `grid`:** `onPointerDown` con `pointerType === 'mouse'` e tasto sinistro, senza Maiusc né Cmd/Ctrl, avvia un timer di 350 ms. Se nel frattempo il puntatore si sposta più di 5 px, parte un `dragstart`, o arriva `pointerup`/`pointerleave`, il timer si annulla e tutto resta com'è oggi (clic = seleziona, doppio clic = visore, trascinamento nel testo).
- Allo scadere del timer compare l'anteprima. Al `pointerup` (ascoltato su `window`, perché il puntatore può essere sopra l'anteprima), su `Escape` o su `blur` della finestra l'anteprima si chiude.
- Il clic che segue il rilascio **non** deve cambiare la selezione: un ref `peekShownRef` fa ignorare quel solo `onClick` (e il doppio clic eventualmente generato).
- Mentre l'anteprima è aperta, chiamare `preventDefault` sul `dragstart` per non trascinare l'immagine per sbaglio.
- **Touch:** resta com'è (pressione lunga di 500 ms apre il visore intero). **Vista `rows`:** niente anteprima, le pagine sono già grandi.

## Aspetto
- Livello fisso sopra tutto (`fixed inset-0 z-50`), sfondo `bg-black/40` con `pointer-events-none` sul velo, `animate-in fade-in zoom-in-95 duration-100`.
- Al centro della finestra (non del pannello, che è stretto) l'immagine `img.url` con `object-contain`, `max-w-[min(90vw,1100px)] max-h-[80vh]`, `rounded-lg shadow-2xl bg-background`.
- Sotto, una riga di didascalia uguale a quella della cella: "Pag. N" e unità usate o "non usata", in `text-body text-white`.
- Renderizzare con `createPortal` su `document.body`, `role="dialog"`, `aria-label="Anteprima pagina N"`, senza spostare il focus.
- Un solo stato in `MediaGallery`: `peek: { img, captionLabel, unitText } | null`.

## Test (vitest + fireEvent con pointer events, `vi.useFakeTimers()`)
- Griglia: `pointerDown` (mouse) su una cella, avanzare 350 ms → compare il dialog "Anteprima pagina N" con l'immagine; `pointerUp` su window → sparisce; la selezione non è cambiata (`aria-pressed` invariato) dopo il click che segue.
- `pointerDown` e `pointerUp` prima di 350 ms → nessuna anteprima, il clic seleziona come oggi.
- `pointerDown` poi `pointerMove` di 10 px → nessuna anteprima.
- `Escape` chiude l'anteprima.
- Vista `rows`: tenere premuto non apre l'anteprima.
- Touch: i test esistenti della pressione lunga restano verdi.

Comandi: `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run src/components/lesson/panels`.

## Changelog
Sezione 4.3.2b1 di `CHANGELOG.md`: "Nella griglia dei media, tieni premuto su una miniatura per vederla in grande; lascia per chiuderla."
