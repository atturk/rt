# Task Codex · RT 4.3.3b4

Ultima beta della 4.3.3. Lavori sul ramo **`codex/4.3.3b4`**, già creato da
`origin/claude/rt-4.3.3-beta`. A fine lavoro apri **una sola PR** verso `claude/rt-4.3.3-beta`.

## I piani, nell'ordine

```
git fetch origin claude/project-thread-h86yf9
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b4/piano-job-in-parallelo-codex.md
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b4/piano-esercizi-traccia-codex.md
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b4/piano-immagini-editor-codex.md
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b4/piano-lettura-media-zen-codex.md
```

1. **Job in parallelo**: tutti i punti, nell'ordine. 0 il worker del Mac ignora il valore,
   1 fisso a 8, 2 trascrizione locale una alla volta, 3 menu senza selettore, 4 documentazione,
   5 test. Usa questa versione del piano, non quella in `codex-piani-job-paralleli/`.
2. **Esercizi**: la traccia dà i dati, non il metodo.
3. **Immagini nell'editor**: 1.1 tremolio, 1.2 graffetta vuota, 1.3 immagine doppia, 1.4 clic,
   doppio clic e trascinamento, 1.5 animazione nel pannello.
4. **Lettura**: 2.1 graffetta e timecode sotto il titolo con il tasto M, 2.2 da zen alla lettura
   veloce.

Non aggiungere al ramo le cartelle `codex-piani-*`.

## Regole

- Un commit per punto, con messaggio `b4 <piano>.<punto>: <titolo breve>`, per esempio
  `b4 immagini 1.3: niente immagine doppia sotto la graffetta`. Per il piano dei job il prefisso è
  `job paralleli:`, come nel suo piano.
- Dopo ogni punto esegui i controlli dei file toccati. Non andare avanti con un controllo rosso.
- Prima della PR esegui i controlli completi:
  - `pytest -q`;
  - `cd frontend && npm run typecheck && npm run lint && npm test`;
  - gli e2e dei file che hai toccato o aggiunto: `npm run build`, poi `npx playwright test <file>`.
    Gli e2e girano in serie sullo stesso server: se cambi le sezioni delle impostazioni, esegui anche
    `settings.spec.ts` e `telegram.spec.ts`.
- Se cambi l'API, rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
- Se cambi un comportamento coperto da un e2e esistente, aggiorna quel test.
- La freccia destra della lettura veloce salta di frase in frase, non di parola in parola.
- Interfaccia minimale: pulsanti a icona con tooltip, nessun testo o legenda nuovi.
- Non cambiare `VERSION` né `CHANGELOG.md`.
- Sui punti ambigui scegli la soluzione più semplice coerente con il piano e annotala nella PR.
- Non saltare né disattivare test.

## La PR

Titolo: `4.3.3b4 · Codex: 8 job in parallelo, esercizi, immagini nell'editor, lettura`.

Nella descrizione metti:
- ogni punto, fatto o non fatto;
- le cause confermate o smentite (1.1, 1.2, 1.3);
- le scelte fatte sui punti ambigui;
- le righe per il changelog.
