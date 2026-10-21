# Piano 3 · Archivio: si apre subito, con il caricamento animato

Agente: **agy**. L'Archivio resta bianco per parecchi secondi ogni volta che si apre.

## Causa (verificata nel codice)

`archive_service.list_entries` chiama `row(meta)` per **ogni** file dell'archivio, e `row` chiama
`archive_usages(sha)`, che per ogni file:

- rifà `lesson_directories()`, cioè una query al DB **più un `os.walk` di tutta la cartella delle
  lezioni**;
- per ogni lezione rilegge `sources.json` (`load_sources`), per ogni fonte chiama `archive.find`
  (che legge `meta.json` e `alias.json`), poi legge `descriptions.json` e `info.yaml`.

Con N file e L lezioni sono N × (walk + L × letture). `/archive/summary` (il riquadro "Archivio ·
16 file" del pannello) rifà tutto lo stesso. In più `ArchivePage.tsx` fa partire la lista con
`materia=''` e poi di nuovo quando arrivano le lezioni e la materia diventa quella della lezione:
due giri completi.

## Backend

1. Nuova funzione `usage_index()` in `archive_service.py`: **un solo** giro su `lesson_directories()`,
   che costruisce `{impronta: [usage, ...]}`:
   - fonti: per ogni fonte con `impronta`, risolvi l'alias con una mappa letta **una volta**
     (`alias.json`), non con `archive.find` per fonte;
   - immagini: per ogni voce di `descriptions.json` la cui immagine esiste, l'impronta è la chiave
     della voce; `info.yaml` letto una volta per lezione;
   - stessa forma e stesso ordinamento di `archive_usages` (le pagine come oggi).
2. `archive_usages(sha)` diventa `usage_index().get(sha, [])`; `list_entries`, `detail`, `lookup`,
   `summary` e `delete_entry` usano un solo indice per richiesta (passato come argomento, non
   ricalcolato per riga).
3. `/archive/summary` senza `materia` non ha bisogno degli usi: conta le cartelle valide e calcola
   `da_continuare` con lo stesso indice, una volta.
4. Cache breve in memoria dell'indice (per esempio 5 s, oppure invalidata quando cambia l'mtime di
   `alias.json` o di un `sources.json`/`descriptions.json`): facoltativa; se la fai, aggiungi un test
   che dopo una modifica l'indice si aggiorna.
5. Misura: aggiungi un test che con 30 file in archivio e 20 lezioni finte `lesson_directories` viene
   chiamata **una volta** per `list_entries` (monkeypatch con contatore).

## Frontend (`frontend/src/components/archive/ArchivePage.tsx`)

1. La lista parte solo quando la materia è nota: se c'è `da` (lezione d'origine) aspetta
   `lessons.data` (`enabled`), così non fa due giri.
2. Mentre carica (`files.isPending`): uno scheletro come `LessonsSkeleton` in `routes/lessons.tsx`
   (righe con icona e due barre `bg-muted`), con l'effetto **splendente** delle animazioni di
   caricamento già usate nell'app (cerca la classe/keyframe esistente, es. in `DocumentSkeleton` o
   `ReadingSkeleton`; se non c'è un effetto shimmer comune, crealo una volta in `index.css` come
   `rt-shimmer` e usalo anche qui). Anche la colonna di dettaglio a destra ha il suo scheletro
   (riquadro miniatura + due righe) mentre `query.isPending`.
3. `aria-busy="true"` e `role="status"` sullo scheletro, `aria-label="Carico l'archivio"`.
4. La ricerca testuale non fa una richiesta per tasto: debounce 250 ms.

## Test

- pytest: `usage_index` dà gli stessi usi di prima (fonti, alias, immagini) su un archivio di prova;
  il contatore sopra.
- vitest `ArchivePage.test.tsx`: lo scheletro c'è mentre la lista carica e sparisce dopo; con `da`
  la lista non parte finché le lezioni non sono arrivate.

## File

`rt/services/archive_service.py`, `rt/api/routers/archive.py`,
`frontend/src/components/archive/ArchivePage.tsx` (+ test), `frontend/src/index.css` (solo se serve
la classe shimmer comune).
