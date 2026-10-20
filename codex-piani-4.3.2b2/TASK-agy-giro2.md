# Task agy · RT 4.3.2b2 · secondo giro

Lavori sul ramo **`agy/4.3.2b2-giro2`** (già creato da `claude/rt-4.3.2-beta`). A fine lavoro apri una PR
verso **`claude/rt-4.3.2-beta`**. Codex lavora in parallelo su `codex/4.3.2b2-giro2` con altri piani:
non toccare i file che servono solo ai suoi piani (elenco in fondo).

## Dove sono i piani

I piani non sono nel tuo ramo. Leggili con:

```
git fetch origin claude/project-thread-nzna7c
git show origin/claude/project-thread-nzna7c:codex-piani-4.3.2b2/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.2b2/` al tuo ramo. Il wireframe approvato
dell'archivio è https://claude.ai/artifact/P1KzSVbQfXixTkEJ1kPBjf: se non riesci ad aprirlo, i piani
bastano.

Il ramo parte da `claude/rt-4.3.2-beta` **dopo** l'unione del primo giro (archivio, Aggiungi fonte,
pagina Archivio, immagini nel testo e il resto).

## Piano da implementare

1. `piano-pannello-arricchimento-codex.md` (piano 10): pulsante Archivio in cima al pannello, filtro
   Da descrivere, nuova barra della selezione con Descrivi, Posiziona, Inserisci, Ritaglia, Togli dal
   testo, Elimina dalla lezione.

## Regole

- Un commit per piano, con messaggio `4.3.2b2: <titolo breve del piano>`. Per i piani grandi puoi
  usare più commit, sempre con lo stesso prefisso.
- Dopo ogni piano esegui i controlli dei file toccati e non andare avanti con un controllo rosso:
  - `pytest` sui test del piano (alla fine l'intera suite: `pytest -q`);
  - `cd frontend && npm run typecheck && npm run lint && npx vitest run <file di test toccati>`
    (alla fine `npm test`).
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare. Se all'unione lo schema va in
  conflitto con l'altro ramo, lo rigenero io.
- Interfaccia **minimale**: pulsanti a icona con suggerimento, niente leggende, niente frasi
  descrittive visibili. Testo solo dove il piano lo chiede.
- Non cambiare `VERSION`, `CHANGELOG.md`: versione e changelog li faccio io all'unione.
- Se un punto di un piano è ambiguo, scegli la soluzione più semplice coerente con il piano e annotala
  nella PR. Non saltare piani: se uno è impossibile, spiega perché nella PR.
- Rispetta i test esistenti: niente test saltati o disattivati.

## La PR

Titolo `4.3.2b2 · agy: pannello Arricchimento`. Nella descrizione: fatto o non fatto, scelte sui
punti ambigui, righe per il changelog.

## File dell'altro agente (non toccarli)

`rt/pipeline/source_update.py`, `rt/pipeline/outline.py`, `rt/pipeline/outline_extension.py`,
`rt/pipeline/material_mapping.py`, `rt/pipeline/rewrite.py`, `rt/llm/prompts.py`,
`rt/core/materials.py`, `rt/core/source_selection.py`.
