# Task agy · RT 4.3.3b3

Lavori sul ramo **`agy/4.3.3b3`**, già creato da `origin/claude/rt-4.3.3-beta`. A fine lavoro apri una
PR verso **`claude/rt-4.3.3-beta`**. Codex lavora in parallelo su `codex/4.3.3b3`: non toccare i file
del suo elenco in fondo.

## Dove sono i piani

```
git fetch origin claude/project-thread-h86yf9
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b3/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.3b3/` al tuo ramo.

## Piani da implementare, in quest'ordine

1. `piano-formule-domande.md` (piano 5): regola LaTeX nei prompt delle domande. C'è un'implementazione
   di riferimento sul ramo `origin/claude/formule-domande`: puoi riprenderla.
2. `piano-invio-tastiera.md` (piano 3): ⌘/Ctrl + Invio invia la risposta scritta, Invio va a capo.
3. `piano-campi-senza-bordo.md` (piano 4): niente bordo nero di focus nei campi di testo.
4. `piano-formule-lettura-veloce.md` (piano 6): formule lunghe della lettura veloce adattate alla
   loro misura reale e centrate.
5. `piano-rumore-timer-lettura.md` (piano 7): dissolvenza di 1 s sul rumore e conto alla rovescia
   (0–10 s) prima della lettura veloce.

## Regole

- Un commit per piano, con messaggio `4.3.3b3: <titolo breve del piano>`.
- Dopo ogni piano i controlli dei file toccati, e non andare avanti con un controllo rosso:
  - `pytest` sui test del piano (alla fine `pytest -q`);
  - `cd frontend && npm run typecheck && npm run lint && npx vitest run <file di test toccati>`
    (alla fine `npm test`).
- Gli e2e Playwright che i piani chiedono vanno in `frontend/e2e/`.
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare.
- Interfaccia **minimale**: pulsanti a icona con suggerimento, niente leggende, niente frasi
  descrittive.
- Non cambiare `VERSION` né `CHANGELOG.md`.
- Punti ambigui: la soluzione più semplice coerente con il piano, annotata nella PR. Non saltare piani:
  se uno è impossibile, spiega perché nella PR.
- Niente test saltati o disattivati.

## La PR

Titolo `4.3.3b3 · agy: lettura veloce, formule, invio da tastiera, campi senza bordo`. Nella
descrizione: per ogni piano fatto o non fatto, scelte sui punti ambigui, righe per il changelog.

## File di Codex (non toccarli)

`frontend/src/components/lessons/LessonsView.tsx`, `frontend/src/components/lessons/NewLessonDialog.tsx`,
`frontend/src/components/calendar/*`, `frontend/src/components/shell/BackupDialog.tsx`,
`frontend/src/components/settings/*` tranne le impostazioni della lettura veloce dentro
`SpeedReader.tsx`, `frontend/src/lib/lessonsPage.ts`, `rt/services/calendar_service.py`,
`rt/services/calendar_models.py`, `rt/api/routers/calendar.py`, `rt/api/routers/jobs.py`,
`rt/services/backup_service.py`, `rt/storage/migrate.py`, `rt/window.py`,
`rt/services/materials_lesson_service.py`, `rt/services/notes_lesson_service.py`, `rt/api/schemas.py`.
In `frontend/src/index.css` tocca solo le regole `.rt-rsvp*` e aggiungi la regola globale dei campi
di testo del piano 4 (fuori da `@layer base`).
