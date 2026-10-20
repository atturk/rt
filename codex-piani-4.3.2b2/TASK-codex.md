# Task Codex · RT 4.3.2b2

Lavori sul ramo **`codex/4.3.2b2`** (già creato da `claude/rt-4.3.2-beta`). A fine lavoro apri una PR
verso **`claude/rt-4.3.2-beta`**. agy lavora in parallelo su `agy/4.3.2b2` con altri piani:
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

1. `piano-archivio-base-codex.md` (piano 6): archivio unico in `<data>/archivio/`, riuso di
   estrazione, vision e trascrizione, popolamento dalle lezioni esistenti.
2. `piano-aggiungi-fonte-codex.md` (piano 8): `Source.pagine/estrai/uso`, finestra Aggiungi fonte,
   DOCX e TXT.
3. `piano-archivio-pagina-codex.md` (piano 7): API e pagina Archivio, componente
   `components/ui/selection-bar.tsx`.

Il 7 e l'8 dipendono dal 6. Il 7 usa `uso` e `pagine` dell'8, per questo l'8 viene prima.

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
- `python-docx` va in `requirements.txt`. Non toccare `scripts/build_app.py` (lo cambia agy): se
  il bundle dell'app ha bisogno di elencare il pacchetto a mano, scrivilo nella PR e lo aggiungo io.

## La PR

Titolo `4.3.2b2 · Codex: archivio delle fonti, Aggiungi fonte, pagina Archivio`. Nella descrizione:
per ogni piano una riga con fatto o non fatto, le scelte fatte sui punti ambigui, e le righe per il
changelog prese dalla sezione "Changelog" dei piani.

## File dell'altro agente (non toccarli)

`rt/window.py`, `rt/window_signals.py`, `rt/window_permissions.py`, `rt/desktop.py`,
`rt/core/app_update.py`, `rt/api/routers/system.py`, `scripts/build_app.py`,
`scripts/make_dmg_background.py`, `packaging/`, `.github/workflows/app.yml`,
`frontend/src/components/Layout.tsx`, `frontend/src/components/settings/update.tsx`,
`frontend/src/components/settings/shortcuts.tsx`, `frontend/src/components/jobs/JobsIndicator.tsx`,
`frontend/src/components/shell/GlobalFileDrop.tsx`, `frontend/src/components/shell/globalFileDropUtils.ts`,
`frontend/src/components/lesson/lessonImages.ts`, `frontend/src/components/lesson/lessonUnits.ts`,
`frontend/src/components/lesson/DocumentView.tsx`, `frontend/src/components/images/*`,
`frontend/src/components/lesson/panels/EnrichmentPanel.tsx`, `MediaGallery.tsx`,
`MediaSelectionBar.tsx`, `MediaCropView.tsx` (questo si può importare, non modificare),
`frontend/src/components/recall/*`, `rt/pipeline/recall.py`, `rt/services/recall_*.py`.

File condivisi:
- `frontend/src/routes/index.tsx`: tu aggiungi solo la rotta `archivio`; agy aggiunge
  `app/aggiornamento` e la pagina Risposte.
- `rt/api/routers/images.py`: tu cambi i percorsi delle immagini dei materiali (piano 6); agy tocca
  solo `find_units_for_image` e `in_document` per riconoscere `#w=` (piano 9).
- `rt/core/models.py`: agy aggiunge campi al recall (piano 4); tu non ci servi, se ti serve tocca solo
  le classi delle fonti.
