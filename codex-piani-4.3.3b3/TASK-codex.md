# Task Codex · RT 4.3.3b3

Lavori sul ramo **`codex/4.3.3b3`**, già creato da `origin/claude/rt-4.3.3-beta`. A fine lavoro apri
una PR verso **`claude/rt-4.3.3-beta`**. agy lavora in parallelo su `agy/4.3.3b3`: non toccare i file
del suo elenco in fondo.

## Dove sono i piani

```
git fetch origin claude/project-thread-h86yf9
git show origin/claude/project-thread-h86yf9:codex-piani-4.3.3b3/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.3b3/` al tuo ramo.

## Piani da implementare, in quest'ordine

1. `piano-anello-scudo-lezioni.md` (piano 8): spunta nell'anello dello studio, scudo solo sulle
   lezioni verificate.
2. `piano-metadati-doppi-codex.md` (piano 2): lezione con metadati già usati, dire quali e permettere
   di cambiarli prima di accodare.
3. `piano-lezioni-mancanti.md` (piano 9): inizio del periodo accademico e avviso delle lezioni
   mancanti per materia (include la pulizia di `focus:ring` in `CalendarPopups.tsx`).
4. `piano-esporta-importa-codex.md` (piano 1): Esporta tutto e Importa nel menu dell'app, **senza
   chiavi API** (decisione di Attilio: le chiavi non lasciano mai il PC).

## Regole

- Un commit per piano, messaggio `4.3.3b3: <titolo breve del piano>`. Se il piano è grande puoi fare
  più commit, tutti con lo stesso prefisso.
- Dopo ogni piano i controlli dei file toccati, e non andare avanti con un controllo rosso; prima
  della PR quelli completi:
  - `pytest -q`;
  - `cd frontend && npm run typecheck && npm run lint && npm test`.
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare.
- Gli e2e Playwright che i piani chiedono vanno in `frontend/e2e/`; se cambi un comportamento coperto
  da un e2e esistente (es. `lesson-review-shield` sulle lezioni non verificate), aggiorna quell'e2e.
- Interfaccia **minimale**: pulsanti a icona con suggerimento, niente leggende, niente frasi
  descrittive.
- Non cambiare `VERSION` né `CHANGELOG.md`.
- Punti ambigui: la soluzione più semplice coerente con il piano, annotata nella PR. Non saltare
  piani: se uno è impossibile, spiega perché nella PR.
- Niente test saltati o disattivati.

## La PR

Titolo `4.3.3b3 · Codex: lezioni mancanti, metadati doppi, esporta/importa, anello e scudo`. Nella
descrizione: per ogni piano fatto o non fatto, scelte sui punti ambigui, righe per il changelog.

## File di agy (non toccarli)

`frontend/src/components/recall/LightweightSession.tsx`, `frontend/src/components/study/SpeedReader.tsx`,
`frontend/src/components/study/rsvpSound.ts`, `frontend/src/lib/studyPrefs.ts`, `rt/llm/prompts.py`,
`rt/pipeline/recall_special.py`, `tests/test_latex_prompts.py`. In `frontend/src/index.css` non
toccare le regole `.rt-rsvp*` e non aggiungere regole di focus: se ti serve CSS, solo un blocco nuovo
in fondo al file.
