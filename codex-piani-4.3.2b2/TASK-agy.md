# Task agy · RT 4.3.2b2

Lavori sul ramo **`agy/4.3.2b2`** (già creato da `claude/rt-4.3.2-beta`). A fine lavoro apri una PR
verso **`claude/rt-4.3.2-beta`**. Codex lavora in parallelo su `codex/4.3.2b2` con altri piani:
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

## Piani da implementare, in quest'ordine

1. `piano-aggiornamenti-app-codex.md` (piano 1): aggiornamenti in un popup dell'app, download
   conservato, Installa e riavvia, canale beta dall'app.
2. `piano-notifiche-dock-codex.md` (piano 2): notifiche di sistema e numero dei job sull'icona.
3. `piano-apri-con-codex.md` (piano 3): file aperti con RT che aprono Nuova lezione.
4. `piano-dmg-apri-comunque-codex.md` (piano 5): firma ad-hoc e sfondo del DMG con le istruzioni.
5. `piano-risposte-codex.md` (piano 4): storico delle risposte, domande riposte senza la vecchia
   risposta, pagina Risposte.
6. `piano-immagini-nel-testo-codex.md` (piano 9): immagini trascinate sotto il titolo o dove le
   lasci, ridimensionamento, clic che seleziona nei media, cancellazione nel testo.

I piani 1, 2, 3 e 5 toccano tutti `rt/window.py`, `scripts/build_app.py` e
`.github/workflows/app.yml`: falli in ordine e rileggi i file prima di ognuno.

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

Titolo `4.3.2b2 · agy: aggiornamenti nell'app, notifiche, Apri con, DMG, risposte, immagini nel
testo`. Nella descrizione: per ogni piano una riga con fatto o non fatto, le scelte fatte sui punti
ambigui, e le righe per il changelog prese dalla sezione "Changelog" dei piani.

## File dell'altro agente (non toccarli)

`rt/core/archive.py`, `rt/core/materials.py`, `rt/core/sources.py`, `rt/core/source_selection.py`,
`rt/pipeline/source_update.py`, `rt/pipeline/material_mapping.py`, `rt/pipeline/add_images.py`,
`rt/pipeline/setup.py`, `rt/services/editor_media_service.py`, `rt/services/archive_service.py`,
`rt/services/materials_lesson_service.py`, `rt/services/backup_service.py`,
`rt/services/data_service.py`, `rt/api/routers/archive.py`, `rt/api/routers/lesson_sources.py`,
`rt/api/routers/jobs.py`, `requirements.txt`, `frontend/src/components/archive/*`,
`frontend/src/components/sources/*`, `frontend/src/components/ui/selection-bar.tsx`,
`frontend/src/components/lessons/NewLessonDialog.tsx`,
`frontend/src/components/lesson/panels/SourcesSection.tsx`, `frontend/src/api/sources.ts`.

File condivisi:
- `frontend/src/routes/index.tsx`: tu aggiungi solo `app/aggiornamento` e la pagina Risposte; Codex
  aggiunge la rotta `archivio`.
- `rt/api/routers/images.py`: tu tocchi solo `find_units_for_image` e `in_document` (piano 9); Codex
  cambia i percorsi delle immagini dei materiali.
- `rt/core/models.py`: tu aggiungi i campi del recall (piano 4); Codex tocca solo le classi delle
  fonti, se gli servono.
- `EnrichmentPanel.tsx` e `MediaGallery.tsx`: in questo giro solo le parti del piano 9.
