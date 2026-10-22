# Task Codex · Job in parallelo

Lavori sul ramo **`codex/job-paralleli`**, già creato da `origin/claude/rt-4.3.3-beta`. A fine lavoro
apri una PR verso **`claude/rt-4.3.3-beta`**.

## Il piano

```
git fetch origin claude/project-thread-krk5ox
git show origin/claude/project-thread-krk5ox:codex-piani-job-paralleli/piano-job-in-parallelo-codex.md
```

Non aggiungere la cartella `codex-piani-job-paralleli/` al tuo ramo.

Implementa tutti i punti, nell'ordine: 0 (il worker del Mac ignora l'impostazione), 1 (tetto a 16),
2 (trascrizione locale una alla volta), 3 (menu), 4 (documentazione), 5 (test).

## Regole

- Un commit per punto, messaggio `job paralleli: <titolo breve del punto>`.
- Dopo ogni punto i controlli dei file toccati, e non andare avanti con un controllo rosso; prima
  della PR quelli completi:
  - `pytest -q`;
  - `cd frontend && npm run typecheck && npm run lint && npm test`.
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare.
- Se cambi un comportamento coperto da un e2e esistente (`frontend/e2e/settings.spec.ts`), aggiornalo.
- Interfaccia minimale: nessun testo nuovo oltre a "In attesa che finisca un'altra trascrizione".
- Non cambiare `VERSION` né `CHANGELOG.md`.
- Punti ambigui: la soluzione più semplice coerente con il piano, annotata nella PR.
- Niente test saltati o disattivati.

## La PR

Titolo `Job in parallelo: impostazione applicata sul Mac, fino a 16, trascrizione locale una alla volta`.
Nella descrizione: ogni punto fatto o non fatto, scelte sui punti ambigui, righe per il changelog.
