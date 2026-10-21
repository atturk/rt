# Task Codex · RT 4.3.2b3

Lavori sul ramo **`codex/4.3.2b3`**: crealo da `origin/claude/rt-4.3.2b3` se non esiste. A fine lavoro
apri una PR verso **`claude/rt-4.3.2b3`**. agy lavora in parallelo su `agy/4.3.2b3` con altri piani:
non toccare i file che servono solo ai suoi piani (elenco in fondo).

## Dove sono i piani

```
git fetch origin claude/project-thread-nzna7c
git show origin/claude/project-thread-nzna7c:codex-piani-4.3.2b3/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.2b3/` al tuo ramo.

## Piano da implementare

1. `piano-verifiche-unita-sparite-codex.md` (piano 1).

## Regole

- Commit con messaggio `4.3.2b3: <titolo breve del piano>`.
- Controlli prima di aprire la PR, tutti verdi:
  - `pytest -q`;
  - `cd frontend && npm run typecheck && npm run lint && npm test`.
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
- Interfaccia minimale: testo solo dove il piano lo chiede.
- Non cambiare `VERSION` né `CHANGELOG.md`.
- Punti ambigui: la soluzione più semplice coerente con il piano, annotata nella PR.
- Niente test saltati o disattivati.

## La PR

Titolo `4.3.2b3 · Codex: issue delle unità sparite`. Nella descrizione: fatto o non fatto, scelte sui
punti ambigui, righe per il changelog.

## File dell'altro agente (non toccarli)

`frontend/src/lib/lessonsPage.ts`, `frontend/src/lib/lessonView.ts`,
`frontend/src/components/lessons/LessonsView.tsx`, `frontend/src/routes/lessons.tsx`,
`frontend/src/lib/jobs.ts`, `frontend/src/components/lesson/JobsPanel.tsx`,
`rt/api/routers/images.py`, `rt/api/routers/lessons.py` (export), `rt/storage/export.py`,
`rt/llm/enrichment_media.py`, `rt/services/lesson_service.py`.
