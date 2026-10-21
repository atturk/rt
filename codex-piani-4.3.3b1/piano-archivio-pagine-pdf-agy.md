# Piano 4 · Archivio: le pagine dei PDF non diventano immagini

Agente: **agy**. Nella vista "Tutti" dell'Archivio ogni pagina dei PDF compare anche come immagine
singola (`28a4e18e451c5e2d.png · 1 pagine · 1 lezioni`). Non dipende solo dalle lezioni vecchie: è un
bug che si ripete a ogni PDF aggiunto.

## Causa (verificata nel codice)

`rt/pipeline/add_images.py`:

- `save_raw_image` chiama `register_image(full_path)` per **ogni** immagine salvata nella lezione;
- `save_image_descriptions` chiama `register_image` per **ogni** voce di `descriptions.json`.

Le pagine dei PDF (`source` = `pdf:<file>#<n>` o `material:<id>:<n>`), quelle aggiunte dall'Archivio
(`archive:<sha>:<n>`) e i ritagli fatti nel pannello passano di lì e finiscono nell'archivio come
file `immagine`. Anche il popolamento iniziale (`rt/services/archive_backfill.py`) registra tutte le
immagini di `assets/images`.

## Regola

Nell'archivio va come file `immagine` solo un'immagine **aggiunta come immagine** dall'utente:

| `source` della descrizione | Nell'archivio come immagine |
|---|---|
| `editor:<nome>` (trascinata/incollata nel testo) | sì |
| `folder:<nome>` (png/jpg caricati nel pannello o in Nuova lezione) | sì |
| `websearch:...` | sì |
| `pdf:...`, `material:...`, `archive:...`, `asset:...`, voci con `crop_of` | no |

Il ritaglio salvato come nuova immagine **dall'Archivio** (`archive_service.crop`, che chiama
`archive.register_image` direttamente) resta com'è: è una scelta esplicita dell'utente.

## Backend

1. `save_raw_image`: togli la registrazione. Non sa da dove viene l'immagine.
2. `save_image_descriptions`: registra solo le voci la cui `source` è nella tabella "sì" e che non
   hanno `crop_of`. Funzione unica `is_standalone_image(description) -> bool` in `add_images.py`,
   usata anche al punto 3.
3. Controlla che i percorsi "sì" passino tutti da `save_image_descriptions` con la `source` giusta
   (`editor_media_service.upload_image`, `job_handlers` per `folder:`, `fetch_web_images`); se uno
   salvava senza descrizione e contava sulla registrazione di `save_raw_image`, registralo lì in
   modo esplicito.
4. `archive_backfill`: registra da `assets/images` solo le immagini la cui descrizione passa
   `is_standalone_image`; un'immagine senza descrizione non va registrata.
5. **Pulizia una tantum** delle voci già create per errore, in `archive_backfill.py` come funzione
   `prune_page_images()`, avviata dove parte oggi il popolamento (un marcatore
   `prune_page_images_done` in `archive_dir()`, come `backfill_done`). Elimina una voce dell'archivio
   solo se **tutte** queste condizioni valgono:
   - `tipo == 'immagine'` e nessun `ritaglio_di` nel `meta.json`;
   - in **nessuna** lezione esiste una descrizione con quella impronta che passa
     `is_standalone_image`;
   - in almeno una lezione esiste una descrizione con quella impronta (cioè è davvero una pagina
     estratta, non un file messo a mano nell'archivio).
   Rimuove la cartella e le voci in `alias.json` che puntano lì (stesso codice di
   `archive_service.delete_entry`, senza il controllo sugli usi). Le immagini nelle lezioni non si
   toccano: ogni lezione ha la sua copia in `assets/images`.
6. Niente cambi all'interfaccia: il filtro "Immagini" dell'Archivio mostrerà da solo solo le immagini
   vere.

## Test

- Aggiungere un PDF a una lezione (fixture con 3 pagine, percorso `material:` e `pdf:`) non crea voci
  `immagine` nell'archivio; il PDF c'è come `slide`/`documento`.
- Un'immagine `editor:` e una `folder:` vengono registrate.
- `prune_page_images`: con un archivio che ha una pagina estratta registrata per errore, una
  immagine `folder:` e un ritaglio dall'Archivio, elimina solo la prima; seconda esecuzione non fa
  niente (marcatore).
- I test esistenti di `archive_backfill` e dell'Archivio restano verdi; aggiorna quelli che si
  aspettavano la registrazione di ogni immagine.

## File

`rt/pipeline/add_images.py`, `rt/services/archive_backfill.py`, eventualmente
`rt/services/editor_media_service.py` (solo il punto 3), test relativi.
