# Task Codex · RT 4.3.2b1

Lavori sul ramo **`codex/4.3.2b1`** (già creato da `claude/rt-4.3.2-beta`). A fine lavoro apri una
PR verso **`claude/rt-4.3.2-beta`**. Un altro agente lavora in parallelo su `agy/4.3.2b1` con altri
piani: non toccare i file che servono solo ai suoi piani (elenco in fondo).

## Dove sono i piani

I piani non sono nel tuo ramo. Leggili con:

```
git fetch origin claude/project-thread-nzna7c
git show origin/claude/project-thread-nzna7c:codex-piani-4.3.2b1/<nome-file>
```

Non aggiungere la cartella `codex-piani-4.3.2b1/` al tuo ramo.

## Piani da implementare, in quest'ordine

1. `piano-audio-codex.md`: audio che si blocca dopo pochi secondi.
2. `piano-ritocchi-dalla-4.3.1-codex.md`: tre ritocchi rimasti dalla 4.3.1.
3. `piano-scaletta-durante-aggiornamento-codex.md`: la card "Scaletta da approvare" non resta
   durante l'aggiornamento.
4. `piano-preparazione-veloce-codex.md`: preparazione più veloce, avanzamento chiaro e tempi
   registrati.
5. `piano-docenti-per-materia-codex.md`: docenti per materia, suggerimenti nel campo Docente, Invio
   nel popup del calendario.
6. `piano-calendario-codex.md`: vista annuale, Vai alla settimana, griglia delle settimane, copia e
   incolla dello stampo, esporta e importa l'orario.

I piani 2, 3 e 4 toccano tutti `rt/pipeline/source_update.py`: falli in ordine e rileggi il file
prima di ognuno. Il 6 dipende dal 5.

## Regole

- Un commit per piano, con messaggio `4.3.2b1: <titolo breve del piano>`. Se un piano è grande
  (il 4 e il 6) puoi usare più commit, sempre con lo stesso prefisso.
- Dopo ogni piano esegui i controlli dei file toccati e non andare avanti con un controllo rosso:
  - `pytest` sui test del piano (alla fine l'intera suite: `pytest -q`);
  - `cd frontend && npm run typecheck && npm run lint && npx vitest run <file di test toccati>`
    (alla fine `npm test`).
- Se cambi l'API rigenera lo schema: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
  `tests/test_api_auth.py::test_openapi_export_is_current` deve passare.
- Interfaccia **minimale**: pulsanti a icona con suggerimento, niente leggende, niente frasi
  descrittive visibili. Testo solo dove il piano lo chiede.
- Non cambiare `VERSION`, `CHANGELOG.md` né i file di build: versione e changelog li faccio io
  all'unione.
- Se un punto di un piano è ambiguo, scegli la soluzione più semplice coerente con il piano e annotala
  nella PR. Non saltare piani: se uno è impossibile, spiega perché nella PR.
- Rispetta i test esistenti: niente test saltati o disattivati.

## La PR

Titolo `4.3.2b1 · Codex: audio, preparazione, scaletta, docenti, calendario`. Nella descrizione: per
ogni piano una riga con fatto o non fatto, le scelte fatte sui punti ambigui, e le righe per il
changelog prese dalle "Note per il changelog" dei piani.

## File dell'altro agente (non toccarli)

`frontend/src/components/ui/icon-button.tsx`, `components/lesson/panels/MediaGallery.tsx`,
`components/lesson/panels/EnrichmentPanel.tsx`, `components/images/*`,
`components/lesson/lessonImageStrips.ts`, `components/study/*`, `components/lessons/*`,
`lib/lessonsPage.ts`, `lib/lessonFilters.ts`, `lib/zoom.ts`, `components/settings/info.tsx`,
`components/settings/preferences.tsx`, `components/shell/BackupDialog.tsx`, `rt/window.py`,
`rt/services/backup_service.py`, `rt/core/bundle.py`, `scripts/build_app.py`.
`frontend/src/routes/lessons.tsx` lo toccate entrambi: tu solo la parte della pagina della lezione
(piano 3), lui solo l'elenco delle lezioni.
