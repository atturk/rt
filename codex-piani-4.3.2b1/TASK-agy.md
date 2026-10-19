# Task agy · RT 4.3.2b1

Lavori sul ramo **`agy/4.3.2b1`** (già creato da `claude/rt-4.3.2-beta`). A fine lavoro apri una
PR verso **`claude/rt-4.3.2-beta`**. Codex lavora in parallelo su `codex/4.3.2b1` con altri piani:
non toccare i file che servono solo ai suoi piani (elenco in fondo).

## Dove sono i piani

I piani non sono nel tuo ramo. Leggili con:

```
git fetch origin claude/project-thread-nzna7c
git show origin/claude/project-thread-nzna7c:codex-piani-4.3.2b1/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.2b1/` al tuo ramo.

## Piani da implementare, in quest'ordine

1. `piano-suggerimenti-pulsanti-disattivati-codex.md`: suggerimento dei pulsanti a icona anche
   quando sono disattivati. Va per primo perché gli altri piani lo usano.
2. `piano-file-scelti-media-codex.md`: file scelti invisibili in "Aggiungi PDF o foto".
3. `piano-media-una-per-riga-codex.md`: galleria dei materiali con una pagina per riga.
4. `piano-anteprima-tenendo-premuto-codex.md`: anteprima grande tenendo premuto in vista
   miniature (dopo il 3: stesso file).
5. `piano-immagine-singola-miniatura-codex.md`: una sola immagine si mostra in miniatura.
6. `piano-ricerca-fissata-codex.md`: vista fissata nella pagina Lezioni.
7. `piano-lettura-veloce-tasti-codex.md`: L, S, Option/Alt+frecce e controlli attenuati nella
   lettura veloce.
8. `piano-zoom-codex.md`: zoom dell'interfaccia e zoom del testo nello Studio (dopo il 7: stesso
   `Study.tsx`).
9. `piano-informazioni-su-rt-codex.md`: Informazioni su RT con logo, versione e build.
10. `piano-backup-copia-codex.md`: backup con copia.

I piani 8, 9 e 10 toccano tutti `rt/window.py`: falli in ordine e rileggi il file prima di ognuno.

## Regole

- Un commit per piano, con messaggio `4.3.2b1: <titolo breve del piano>`.
- Dopo ogni piano esegui i controlli dei file toccati e non andare avanti con un controllo rosso:
  - `cd frontend && npm run typecheck && npm run lint && npx vitest run <file di test toccati>`
    (alla fine `npm test`);
  - `pytest` sui test del piano se tocchi Python (alla fine l'intera suite: `pytest -q`).
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare.
- Interfaccia **minimale**: pulsanti a icona con suggerimento, niente leggende, niente frasi
  descrittive visibili. Testo solo dove il piano lo chiede.
- Non cambiare `VERSION`, `CHANGELOG.md` né la versione nei file di build: versione e changelog li
  faccio io all'unione (il piano 9 legge versione e build, non le cambia).
- Se un punto di un piano è ambiguo, scegli la soluzione più semplice coerente con il piano e annotala
  nella PR. Non saltare piani: se uno è impossibile, spiega perché nella PR.
- Rispetta i test esistenti: niente test saltati o disattivati.

## La PR

Titolo `4.3.2b1 · agy: media, Studio, lettura veloce, zoom, Lezioni, app`. Nella descrizione: per
ogni piano una riga con fatto o non fatto, le scelte fatte sui punti ambigui, e le righe per il
changelog prese dalle "Note per il changelog" dei piani.

## File di Codex (non toccarli)

`rt/services/audio_service.py`, `frontend/src/components/lesson/AudioPlayer.tsx`, `rt/pipeline/*`,
`rt/core/materials.py`, `rt/core/update_history.py`, `rt/services/outline_service.py`,
`rt/services/pipeline_service.py`, `rt/services/api_jobs.py`, `rt/api/routers/jobs.py`,
`rt/services/subjects.py`, `rt/api/routers/subjects.py`, `rt/db/models.py`,
`rt/services/calendar_*.py`, `rt/api/routers/calendar.py`, `frontend/src/components/calendar/*`,
`frontend/src/routes/calendar.tsx`, `frontend/src/api/calendar.ts`, `frontend/src/api/subjects.ts`,
`frontend/src/components/settings/subjects.tsx`, `frontend/src/components/lesson/lessonShortcuts.ts`.
`frontend/src/routes/lessons.tsx` lo toccate entrambi: tu solo l'elenco delle lezioni (piano 6), lui
solo la parte della pagina della lezione.
