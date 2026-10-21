# Task agy · RT 4.3.3b1

Lavori sul ramo **`agy/4.3.3b1`**: crealo da `origin/claude/rt-4.3.3-beta` se non esiste. A fine
lavoro apri una PR verso **`claude/rt-4.3.3-beta`**. Codex lavora in parallelo su `codex/4.3.3b1`:
non toccare i file del suo elenco in fondo.

## Dove sono i piani

```
git fetch origin claude/project-thread-h86yf9
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b1/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.3b1/` al tuo ramo.

## Piani da implementare, in quest'ordine

1. `piano-archivio-pagine-pdf-agy.md` (piano 4): le pagine dei PDF non diventano immagini nell'archivio.
2. `piano-archivio-veloce-agy.md` (piano 3): archivio veloce e caricamento animato.
3. `piano-pannello-arricchimento-agy.md` (piano 2): pannello allargabile e immagine scelta al centro.

## Regole

- Un commit per piano, con messaggio `4.3.3b1: <titolo breve del piano>`.
- Dopo ogni piano i controlli dei file toccati, e non andare avanti con un controllo rosso:
  - `pytest` sui test del piano (alla fine `pytest -q`);
  - `cd frontend && npm run typecheck && npm run lint && npx vitest run <file di test toccati>`
    (alla fine `npm test`).
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare.
- Interfaccia **minimale**: pulsanti a icona con suggerimento, niente leggende, niente frasi
  descrittive.
- Non cambiare `VERSION` né `CHANGELOG.md`.
- Punti ambigui: la soluzione più semplice coerente con il piano, annotata nella PR. Non saltare piani:
  se uno è impossibile, spiega perché nella PR.
- Niente test saltati o disattivati.

## La PR

Titolo `4.3.3b1 · agy: archivio e pannello Arricchimento`. Nella descrizione: per ogni piano fatto o
non fatto, scelte sui punti ambigui, righe per il changelog.

## File di Codex (non toccarli)

`frontend/src/components/lesson/lessonImages.ts`, `lessonImageStrips.ts`, `lessonUnits.ts`,
`lessonShortcuts.ts`, `LessonEditor.tsx`, `DocumentView.tsx`, `frontend/src/components/images/*`,
`frontend/src/components/study/Study.tsx`, `frontend/src/components/settings/shortcuts.tsx`,
`rt/services/document_edit_service.py`, `rt/pipeline/image_placement.py`, il modello `DocumentSection`
e le rotte del documento. In `frontend/src/index.css` tocca solo `.rt-panel-container`, la variabile
`--rt-panel-width` e le classi nuove `rt-media-flash` / `rt-shimmer`.
