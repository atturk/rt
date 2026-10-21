# Task agy · RT 4.3.2b3

Lavori sul ramo **`agy/4.3.2b3`**: crealo da `origin/claude/rt-4.3.2b3` se non esiste. A fine lavoro
apri una PR verso **`claude/rt-4.3.2b3`**. Codex lavora in parallelo su `codex/4.3.2b3`: non toccare i
file che servono solo al suo piano (elenco in fondo).

## Dove sono i piani

```
git fetch origin claude/project-thread-nzna7c
git show origin/claude/project-thread-nzna7c:codex-piani-4.3.2b3/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.2b3/` al tuo ramo.

## Piani da implementare, in quest'ordine

1. `piano-nomi-job-agy.md` (piano 4): nomi leggibili per tutti i job.
2. `piano-lezioni-ordine-agy.md` (piano 2): nessun raggruppamento e ordine "(Ri)create di recente".
3. `piano-esporta-pdf-agy.md` (piano 3): Esporta PDF.

## Regole

- Un commit per piano, con messaggio `4.3.2b3: <titolo breve del piano>`.
- Dopo ogni piano i controlli dei file toccati, e non andare avanti con un controllo rosso:
  - `pytest` sui test del piano (alla fine `pytest -q`);
  - `cd frontend && npm run typecheck && npm run lint && npx vitest run <file di test toccati>`
    (alla fine `npm test`).
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare.
- Interfaccia **minimale**: pulsanti a icona con suggerimento, niente leggende, niente frasi
  descrittive. Testo solo dove il piano lo chiede.
- Non cambiare `VERSION` né `CHANGELOG.md`.
- Punti ambigui: la soluzione più semplice coerente con il piano, annotata nella PR. Non saltare piani:
  se uno è impossibile, spiega perché nella PR.
- Niente test saltati o disattivati (tranne il PDF vero del piano 3 quando Chromium manca, come dice
  il piano).

## La PR

Titolo `4.3.2b3 · agy: nomi dei job, ordine delle lezioni, esporta PDF`. Nella descrizione: per ogni
piano fatto o non fatto, scelte sui punti ambigui, righe per il changelog.

## File dell'altro agente (non toccarli)

`rt/pipeline/review.py`, `rt/pipeline/ledger.py`, `rt/services/review_service.py`,
`rt/pipeline/rewrite.py`, `frontend/src/components/lesson/panels/ReviewPanel.tsx`.
