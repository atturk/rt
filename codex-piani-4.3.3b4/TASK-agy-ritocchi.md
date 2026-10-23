# Task agy · ritocchi RT 4.3.3b4

Ultimi ritocchi della 4.3.3b4. Crea il ramo **`agy/4.3.3b4-ritocchi`** da
`origin/claude/rt-4.3.3b4-extra`:

```
git fetch origin claude/rt-4.3.3b4-extra claude/project-thread-h86yf9
git checkout -b agy/4.3.3b4-ritocchi origin/claude/rt-4.3.3b4-extra
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b4/piano-ritocchi-b4-agy.md
```

A fine lavoro apri **una sola PR** verso `claude/rt-4.3.3-beta`.

Esegui i punti del piano nell'ordine: 4 (hook dei gruppi espandibili) prima, perché 2 e 3 lo usano;
poi 1, 2, 3, 5. Non aggiungere al ramo le cartelle `codex-piani-*`.

## Regole

- Un commit per punto, con messaggio `b4 ritocchi <punto>: <titolo breve>`.
- Dopo ogni punto esegui i controlli dei file toccati. Non andare avanti con un controllo rosso.
- Prima della PR esegui i controlli completi:
  - `pytest -q`;
  - `cd frontend && npm run typecheck && npm run lint && npm test`;
  - `npm run build`, poi gli e2e dei file che hai toccato o aggiunto con `npx playwright test <file>`,
    sempre anche `lessons-view.spec.ts`, `study.spec.ts` e `calendar.spec.ts`.
- Se cambi l'API, rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
- Se cambi un comportamento coperto da un e2e esistente, aggiorna quel test.
- Non toccare `CalendarPopups.tsx`, `studyProgress.ts`, `VERSION` né `CHANGELOG.md`.
- Interfaccia minimale: pulsanti a icona con tooltip, nessun testo o legenda nuovi.
- Sui punti ambigui scegli la soluzione più semplice coerente con il piano e annotala nella PR.
- Non saltare né disattivare test.

## La PR

Titolo: `4.3.3b4 · agy: ritocchi a Lezioni, Studio e gruppi espandibili`.

Nella descrizione metti ogni punto, fatto o non fatto, le scelte sui punti ambigui e le righe per il
changelog.
