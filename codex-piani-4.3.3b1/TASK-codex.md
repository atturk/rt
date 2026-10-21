# Task Codex · RT 4.3.3b1

Lavori sul ramo **`codex/4.3.3b1`**: crealo da `origin/claude/rt-4.3.3-beta` se non esiste. A fine
lavoro apri una PR verso **`claude/rt-4.3.3-beta`**. agy lavora in parallelo su `agy/4.3.3b1`: non
toccare i file del suo elenco in fondo.

## Dove sono i piani

```
git fetch origin claude/project-thread-h86yf9
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b1/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.3b1/` al tuo ramo.

## Piano da implementare

1. `piano-immagini-sottounita-codex.md` (piano 1): bottone con la graffetta e sezione delle immagini
   della sottounità al posto del blocco espandibile; via l'impostazione "Immagini trascinate".

## Regole

- Un commit per piano, messaggio `4.3.3b1: <titolo breve del piano>`. Se il piano è grande puoi fare
  più commit, tutti con lo stesso prefisso.
- Controlli prima della PR, e non andare avanti con un controllo rosso:
  - `pytest -q`;
  - `cd frontend && npm run typecheck && npm run lint && npm test`.
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare.
- Interfaccia **minimale**: pulsanti a icona con suggerimento, niente leggende, niente frasi
  descrittive.
- Non cambiare `VERSION` né `CHANGELOG.md`.
- Punti ambigui: la soluzione più semplice coerente con il piano e con i wireframe, annotata nella PR.
- Niente test saltati o disattivati.

## La PR

Titolo `4.3.3b1 · Codex: immagini della sottounità`. Nella descrizione: cosa è fatto, scelte sui
punti ambigui, righe per il changelog.

## File di agy (non toccarli)

`frontend/src/components/lesson/LessonPanel.tsx`, `panels/EnrichmentPanel.tsx`,
`panels/MediaGallery.tsx`, `frontend/src/components/archive/*`, `frontend/src/components/lesson/AudioPlayer.tsx`,
`rt/services/archive_service.py`, `rt/services/archive_backfill.py`, `rt/api/routers/archive.py`,
`rt/core/archive.py`, `rt/pipeline/add_images.py`. In `frontend/src/index.css` aggiungi solo un blocco
nuovo in fondo; non toccare `.rt-panel-container`.
