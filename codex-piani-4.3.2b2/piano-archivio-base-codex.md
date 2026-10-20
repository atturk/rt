# Piano 6 · Archivio delle fonti: un solo posto per ogni file, niente rielaborazioni

Giro 1. Solo backend. I piani 7 (pagina Archivio) e 8 (Aggiungi fonte) si appoggiano a questo.

## Com'è oggi

- Ogni fonte ha l'impronta sha256 del file (`Source.impronta`, `rt/core/sources.py:34`), ma tutto
  quello che si ricava dal file sta **dentro la lezione**:
  - pagine dei materiali: `materials/<impronta>/pages.json`, `page-N.json`, `page-N-K.png`
    (`material_pages`, `rt/core/materials.py:167`), con la vision di `_describe` (`:50`);
  - trascrizioni: `source_update.json` → `sources[<sid>]` per le fonti aggiunte
    (`rt/pipeline/source_update.py:40,110,159`), `trascritto grezzo.json` al setup
    (`rt/pipeline/setup.py:587`).
- Lo stesso PDF o lo stesso audio in un'altra lezione si rielabora da zero (estrazione, vision,
  trascrizione).
- L'unica cache condivisa è quella tecnica dell'audio in `<data>/cache/` (`rt/services/audio_service.py:28`).

## Cosa deve succedere

1. Esiste un **archivio** in `<data>/archivio/` (data dir di `rt/core/paths.py`, come `cache/`), con
   una cartella per contenuto: `archivio/<sha256>/`.
2. Ogni file aggiunto a RT (fonte di una lezione, immagine dal pannello Arricchimento, immagine
   trascinata o incollata nell'editor) finisce nell'archivio con quello che se ne ricava.
3. Se lo stesso file torna, in qualsiasi lezione, **niente nuova estrazione, vision o trascrizione**:
   si riusa l'archivio.
4. Per lezione restano solo le decisioni che dipendono dalla lezione: assegnazione delle pagine alle
   unità (`material_decisions.json`, `material_attachments.json`), placement, testo.
5. Le lezioni esistenti popolano l'archivio una volta, senza chiamate ai modelli.

## Contenuto di `archivio/<sha>/`

```
meta.json          {impronta, nome, tipo, estensione, dimensione, aggiunto_il, estrai,
                    alias: [sha dell'upload originale se diverso], pagine_totali, durata_s,
                    ignorate: [n], eliminate: [n], ritagli: {...}}
originale.<ext>    il file (per gli audio la versione ottimizzata .m4a, mai il wav originale)
pages.json         come oggi {impronta, pages}
page-N.json        come oggi
page-N-K.png       come oggi
trascrizione-<motore>.json   {segments, duration} per motore di trascrizione
```

- `tipo`: `slide` (PDF, PPTX), `testo` (DOCX, TXT, piano 8), `audio`, `immagine`.
- `estrai`: `testo` o `immagini` (piano 8). Se il file c'è già con `testo` e ora serve `immagini`,
  si estraggono solo le immagini mancanti e `estrai` diventa `immagini`. Il contrario non rifà niente.
- `originale.<ext>`: `os.link` dal file della lezione quando possibile, altrimenti copia. La lezione
  tiene la sua copia come oggi: export, backup della lezione e cancellazioni non cambiano.
- `ignorate` / `eliminate` le usa il piano 7. Qui serve solo che `pages_for_use()` (sotto) le salti.

## Modulo nuovo `rt/core/archive.py`

- `archive_dir()`, `entry_dir(sha)`, `load_meta(sha)`, `save_meta(sha, meta)` (scrittura atomica,
  lock su file come gli altri in `<data>/locks`).
- `register_file(path, *, nome, tipo, sha=None, alias=None) -> meta`: crea o aggiorna la voce e
  collega l'originale. Idempotente.
- `find(sha) -> meta | None`, che cerca anche negli `alias` (indice `archivio/alias.json`
  `{sha_upload: sha_archivio}`).
- `page_image_path(sha, name) -> path` per le immagini delle pagine.
- `cached_transcript(sha, motore)` / `store_transcript(sha, motore, data)`.
- `pages_for_use(sha, pagine=None) -> list[page]`: le pagine dell'archivio tolte `ignorate` ed
  `eliminate`, e filtrate per `pagine` se date (il campo `Source.pagine` del piano 8; finché non
  esiste, `None` = tutte).

## Dove si aggancia

- **Materiali.** `material_pages` (`rt/core/materials.py:167`) legge e scrive in
  `archivio/<impronta>/` al posto di `materials/<impronta>/`. Se la lezione ha ancora la vecchia cache
  e l'archivio no, la importa nell'archivio (copia dei file, nessuna chiamata) e la usa. La vecchia
  cartella della lezione non si cancella.
  - Le voci delle pagine tengono in `immagini` i nomi `page-N-K.png`. Tutti i punti che oggi aprono
    quelle immagini con un percorso relativo alla lezione passano da `page_image_path`:
    `rt/pipeline/material_mapping.py` (copia in `assets/images` con `save_raw_image`),
    `rt/api/routers/images.py` (`GET /materials/{impronta}/{name}` e la lista
    `GET /lessons/{id}/images`), `rt/pipeline/add_images.py:451`, `POST /media/material-page`,
    `rt/core/update_history.py:37-55` (lo snapshot non deve più copiare `materials/` se è vuota).
  - I punti che scorrono le pagine usano `pages_for_use` al posto di tutte le pagine:
    `source_update.py:141-145`, `material_mapping.py:567,607`, `materials.py:243`,
    `add_images.py:451`, `sources_view.py:46-48`.
- **Audio.** Prima di trascrivere (`_transcribe` in `source_update.py:40` e la trascrizione del
  setup in `setup.py`) si cerca `cached_transcript(impronta, motore)`, anche tramite alias. Dopo,
  `store_transcript`. Il motore è quello della configurazione attiva: una trascrizione di un altro
  motore non vale.
  - `add_source` (`sources.py:85-125`) calcola lo sha dell'upload **prima** di convertire. Se
    `find(sha_upload)` trova la voce, usa `originale.m4a` dell'archivio e salta la conversione. Se
    converte, registra la voce con lo sha dell'm4a e `alias=[sha_upload]`.
  - Lo stesso vale per il setup di una lezione nuova con audio (`setup.py:577-584`): stesso controllo
    prima di convertire.
- **Immagini.** `upload_image` (`rt/services/editor_media_service.py:23`) e le immagini del pannello
  (`run_add_images`, `add_images.py:578`) registrano ogni immagine nell'archivio (`tipo: immagine`,
  pagina unica). Le descrizioni vision già calcolate per uno sha (`descriptions.json` di qualsiasi
  lezione, chiave sha256) si salvano anche in `archivio/<sha>/descrizione.json`.
  `describe_new_images` (`add_images.py:134`) guarda lì prima di chiamare la vision.
- **Fonti nuove.** `add_source` registra la voce (`register_file`) per ogni materiale e audio.

## Popolamento iniziale

- Job `archive_backfill`, avviato una volta all'avvio del server se in `archivio/indice.json` manca
  `backfill_done: true`.
- Scorre tutte le lezioni (`load_sources` per ognuna, db e cartelle) e per ogni fonte non rimossa
  chiama `register_file`. Se la lezione ha la cache `materials/<impronta>/`, la copia nell'archivio.
  Se ha trascrizioni (`source_update.json` → `sources[sid]`, oppure `trascritto grezzo.json` per
  l'audio del setup), le salva come `trascrizione-<motore>.json` solo se il motore è noto, altrimenti
  le salta. Le immagini di `assets/images` con la loro voce di `descriptions.json` diventano voci
  `immagine`.
- Nessuna chiamata ai modelli. Un errore su una lezione si registra nel log e il job va avanti.
- Alla fine scrive `backfill_done: true`.

## Backup e spazio

- `rt/services/backup_service.py`: il backup include `archivio/` (stesso schema content-addressed di
  `media-store`, i file già presenti non si duplicano). Il ripristino lo rimette.
- `rt/services/data_service.py`: `archivio` va in `SUBDIRS` e si sposta con la cartella dati.
- `DELETE /system/cache` **non** tocca l'archivio.
- Cancellare una lezione non cancella niente dall'archivio (si cancella a mano, piano 7).

## Test

- `tests/test_archive.py`:
  - stesso PDF in due lezioni: la seconda `material_pages` non chiama `_describe` né rielabora
    (mock che conta le chiamate) e restituisce le stesse pagine;
  - vecchia cache `materials/<impronta>/` di una lezione importata nell'archivio al primo uso;
  - `pages_for_use` salta `ignorate`/`eliminate` e rispetta `pagine`;
  - audio wav: il secondo `add_source` dello stesso wav trova l'alias, non converte e non trascrive;
  - trascrizione di un altro motore ignorata;
  - `estrai` da `testo` a `immagini` estrae solo le immagini;
  - `archive_backfill` registra fonti, cache e immagini di due lezioni finte, senza modelli, e non
    riparte una seconda volta.
- Aggiornare i test esistenti che leggono `materials/<impronta>/` (`test_materials.py`,
  `test_material_mapping.py`, `test_material_only_lesson.py`, `test_update_history.py`,
  `test_api_images_mock.py`): devono passare con l'archivio, senza saltarli.
- Backup: un file dell'archivio torna dopo `restore_backup`.

## Changelog

- Archivio delle fonti: un PDF, un audio o un'immagine già usati in una lezione non si rielaborano
  più quando tornano in un'altra (niente nuove trascrizioni né descrizioni).
