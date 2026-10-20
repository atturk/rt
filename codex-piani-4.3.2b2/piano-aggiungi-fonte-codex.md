# Piano 8 · Aggiungi fonte: già nell'archivio, pagine, Estrai, Uso, DOCX e TXT

Giro 1. Dipende dal piano 6. Wireframe: tavola "Aggiungi fonte" del canvas
https://claude.ai/artifact/P1KzSVbQfXixTkEJ1kPBjf.

## Com'è oggi

- Una fonte ha `id, tipo, file, impronta, aggiunta_il, ordine, rimossa_il, parti`
  (`rt/core/sources.py:34`). La principale sta in `source_update.json` (`principale`,
  `primary_explicit`, `rt/core/source_selection.py`) e si sceglie con la stella (`SourcesSection.tsx`
  413-434, `NewLessonDialog.tsx` 633-660).
- Non si possono scegliere le pagine di un PDF, né se estrarre solo il testo.
- DOCX e TXT: il velo di trascinamento li accetta (`globalFileDropUtils.ts:1-19`), ma
  `NewLessonDialog` (`:51`, `:260-266`), `SourcesSection` (`:294`) e il backend (`MATERIAL_EXTENSIONS`
  in `rt/core/materials.py:16`, `_save_uploads` in `rt/api/routers/jobs.py:69`) li rifiutano.

## Modello

`Source` riceve tre campi facoltativi (le fonti vecchie restano valide):

- `pagine: list[int] | None`: le pagine da usare (`None` = tutte). Lo legge `pages_for_use` del
  piano 6.
- `estrai: Literal["testo", "immagini"] | None`. Predefinito per tipo: PDF, PPTX e foto `immagini`;
  DOCX e TXT `testo`. Con `testo`, `material_pages` non salva immagini e non chiama la vision.
- `uso: Literal["contesto", "integra"] | None`, `None` = contesto. **Guida** non è un valore di
  `uso`: è la principale di oggi, e sceglierla chiama `set_primary`. In questo giro `integra` si
  comporta come `contesto`; il comportamento vero arriva col piano 11.

## API

- `POST /lessons/{id}/sources` accetta `pagine` (testo tipo `"31-64"` o `"1,10,12-14"`), `estrai` e
  `uso` (`guida` | `contesto` | `integra`). Con `guida` imposta la principale come fa
  `PUT /sources/primary`.
- `PATCH /lessons/{id}/sources/{sid}` con gli stessi tre campi, per cambiarli dopo.
- Creazione lezione (`rt/api/routers/jobs.py:171`): oltre a `principale`, un campo `opzioni` JSON
  `{<nome file>: {pagine, estrai, uso}}`, passato fino a `create_source_lesson`.
- `POST /archive/lookup {sha: [..]}` → per ogni sha (anche alias del piano 6):
  `{impronta, pagine_totali, usate: [{lezione_id, titolo, data, pagine}], da_continuare}` oppure
  `null`.
- Rigenera lo schema OpenAPI.

## DOCX e TXT

- Backend: `.docx` e `.txt` entrano in `MATERIAL_EXTENSIONS` e negli upload. Aggiungi
  `python-docx>=1.1` a `requirements.txt` e al bundle dell'app (come `python-pptx`).
- `_extract` (`materials.py:139`):
  - TXT: testo letto come UTF-8, con fallback cp1252;
  - DOCX: paragrafi e tabelle in ordine; con `estrai=immagini` anche le immagini incorporate.
  - Il testo si divide in "pagine" di circa 400 parole, senza spezzare i paragrafi; ogni titolo
    (stile Heading) apre una pagina nuova.
- Frontend: `.docx` e `.txt` in `MATERIAL_EXTENSIONS` di `NewLessonDialog.tsx` e nell'`accept` dei
  materiali di `SourcesSection.tsx`. Il messaggio "Formato non supportato" deve citare anche DOCX e TXT.

## Finestra Aggiungi fonte (`frontend/src/components/sources/AddSourceDialog.tsx`)

Si apre per ogni materiale aggiunto dalla sezione Fonti, e dalle impostazioni di un file in Nuova
lezione (sotto). Contenuto, dall'alto:

1. **Riga del file:** icona del tipo, nome, e se il file è nell'archivio (sha calcolato nel browser
   con `crypto.subtle.digest`, poi `POST /archive/lookup`) il chip "Già nell'archivio" con l'icona
   dell'archivio.
2. **Pagine** (solo per file con pagine): due campi Da/A. Se il file è nell'archivio ed è stato usato
   in parte, partono da `da_continuare`, e accanto c'è "1–30 già usate" con il suggerimento
   "12 ottobre: 1–18 · 19 ottobre: 19–30". Altrimenti tutto il file.
3. **Estrai:** due pulsanti a icona (Type = Testo, suggerimento "Testo: niente immagini"; Image =
   Immagini, "Immagini: pagine e figure"). Predefinito per tipo.
4. **Uso:** tre pulsanti a icona:
   - Navigation = Guida, "Guida: fonte principale";
   - Layers = Contesto, "Contesto: arricchisce la fonte principale";
   - GitMerge (o Merge) = Integra, "Integra: può aggiungere unità".
   Accanto, in grigio, il nome dell'uso scelto. Predefinito Contesto; Guida predefinito solo se la
   lezione non ha altre fonti.
5. Annulla / Aggiungi.

Per gli audio niente finestra: si aggiungono come oggi. Gli appunti non cambiano.

## Nuova lezione

- La stella resta solo come scorciatoia visiva per la Guida. Un clic su un materiale scelto apre la
  stessa finestra (senza il pulsante Aggiungi: "Fatto") per impostarne pagine, estrai e uso. Le
  scelte viaggiano in `opzioni`.
- Se un file è già nell'archivio, sulla sua miniatura compare la piccola icona dell'archivio con il
  suggerimento "Già nell'archivio".

## Sezione Fonti

- Ogni riga di materiale mostra, in grigio piccolo, le pagine se non sono tutte ("pag. 31–64") e
  un'icona dell'uso se è Integra.
- Il menu della riga ha "Modifica" che riapre la finestra (salva con `PATCH`). Cambiare pagine, estrai
  o uso segna la lezione da aggiornare, come aggiungere una fonte.

## Test

- Pytest:
  - parsing di `pagine` ("31-64", "1,10,12-14", fuori intervallo → 422);
  - `estrai=testo` senza immagini né vision;
  - DOCX con titoli e tabella diviso in pagine;
  - TXT cp1252;
  - `uso=guida` imposta la principale;
  - `opzioni` alla creazione;
  - `PATCH` che cambia le pagine;
  - `POST /archive/lookup` con alias.
- Vitest:
  - `AddSourceDialog` con file già nell'archivio (chip e pagine da `da_continuare`);
  - predefiniti di Estrai per tipo;
  - Uso Guida predefinito senza altre fonti;
  - `NewLessonDialog` accetta DOCX e TXT e invia `opzioni`.

## Changelog

- Aggiungi fonte: RT riconosce i file già nell'archivio e propone le pagine da dove ci si era
  fermati; per ogni fonte si sceglie cosa estrarre (solo testo o anche immagini) e come usarla
  (Guida, Contesto, Integra).
- Si possono aggiungere documenti Word (.docx) e file di testo (.txt).
