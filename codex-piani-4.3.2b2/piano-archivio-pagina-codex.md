# Piano 7 · Pagina Archivio

Giro 1. Dipende dal piano 6. Wireframe approvato: tavola "Pagina Archivio" del canvas
https://claude.ai/artifact/P1KzSVbQfXixTkEJ1kPBjf (le note grigie sotto le tavole spiegano ogni
comportamento). Interfaccia minimale: pulsanti a icona con suggerimento, niente leggende.

In questo giro **non** toccare `EnrichmentPanel.tsx`, `MediaGallery.tsx`, `MediaSelectionBar.tsx`,
`MediaCropView.tsx` (li cambia il piano 10 nel giro 2). `MediaCropView` si può importare così com'è.

## Cosa deve succedere

- Una pagina `archivio` (rotta nuova in `frontend/src/routes/index.tsx`, `handle: bare`) con tutti i
  file dell'archivio. Ci si arriva solo dal pulsante in cima al pannello Arricchimento (piano 10) e da
  Ritaglia nel pannello: **nessuna voce** nella barra laterale né nel menu.
- Parametri: `?da=<lessonId>&file=<sha>&pagina=<n>&ritaglia=1`, tutti facoltativi.
  - `da`: la freccia in alto a sinistra torna a `/lezioni/<da>?panel=arricchimento`, e la materia di
    quella lezione è il filtro iniziale. Senza `da`, la freccia fa `navigate(-1)`.
  - `file` + `pagina` aprono quel file, in vista a pagina singola su quella pagina. Con `ritaglia=1`
    parte direttamente il ritaglio.

## API (`rt/api/routers/archive.py`, servizio `rt/services/archive_service.py`)

- `GET /archive?materia=&tipo=&q=` → elenco
  `{impronta, nome, tipo, pagine_totali, durata_s, dimensione, materie, usi, da_continuare}`:
  - `materie`: le materie delle lezioni che lo usano (`Lesson.materia`);
  - `usi`: numero di lezioni;
  - `da_continuare`: per i PDF usati solo in parte, l'intervallo dopo l'ultima pagina usata fino alla
    fine (es. `"31–64"`), altrimenti `null`.
  - Ordine: più recenti in alto.
- `GET /archive/summary?materia=` → `{file, da_continuare}` (conteggi per il pulsante del pannello,
  piano 10).
- `GET /archive/{sha}` → dettaglio:
  `{…riga, pagine: [{numero, ignorata, lezione_id|null}], lezioni: [{id, titolo, data, pagine}],
  trascrizione_inizio}`. Per ogni pagina, la lezione che l'ha usata per ultima. `trascrizione_inizio`
  sono le prime righe della trascrizione per gli audio.
- `GET /archive/{sha}/pages/{n}.png` → immagine della pagina (miniatura e pagina singola).
- `PUT /archive/{sha}/ignored {pagine: [n], ignorata: bool}`.
- `POST /archive/{sha}/pages/delete {pagine}`: le aggiunge a `eliminate` e cancella le loro immagini e
  i `page-N.json`. Le immagini già copiate nei media di una lezione restano.
- `POST /archive/{sha}/pages/{n}/crop {rect, sostituisci: bool}` (rect normalizzato `[l,t,w,h]`
  come `cropMediaImage`):
  - `sostituisci`: sovrascrive l'immagine della pagina;
  - altrimenti salva il ritaglio come nuova voce `immagine` dell'archivio (sha del ritaglio,
    `meta.ritaglio_di: {sha, pagina}`) e la restituisce.
- `DELETE /archive/{sha}`: solo se nessuna lezione lo usa, altrimenti 409 con le lezioni.
- `POST /archive/{sha}/add-to-lesson {lesson_id, uso, pagine|null, estrai}`: aggiunge il file come
  fonte della lezione senza rielaborarlo (copia di `originale.*` nella lezione con `add_source`, che
  trova la voce nell'archivio). `uso` e `pagine` come nel piano 8.
- `POST /archive/{sha}/add-to-media {lesson_id, pagine}`: copia quelle pagine nei media della
  lezione come immagini (come `POST /media/material-page`), con la descrizione dell'archivio se c'è.
  Non diventano fonte.
- Lease e lock come le altre scritture sulle lezioni. Rigenera lo schema OpenAPI.

## Pagina (`frontend/src/components/archive/`)

- **Intestazione:** freccia indietro, ricerca, select della materia ("Tutte le materie" più le
  materie), filtri a icona per tipo (Tutti, Slide e PDF, Testo, Audio, Immagini; `SlideToggle` o
  gruppo di `IconButton` con `active`).
- **Elenco a sinistra:** icona del tipo, nome, pagine o durata, in quante lezioni è usato, chip
  "pag. 31–64" per i da continuare. Clic: apre il dettaglio.
- **Dettaglio a destra:**
  - nome e dati del file;
  - `+` (Aggiungi alla lezione come fonte) ed Elimina (disattivato con suggerimento "Usato da N
    lezioni" se usato);
  - le pagine, con sotto ognuna una barretta del colore della lezione che l'ha usata (grigia se mai
    usata);
  - l'elenco delle lezioni che lo usano (link alla lezione), con lo stesso colore;
  - per gli audio, l'inizio della trascrizione.
- **Larghezza del dettaglio:** si trascina il bordo sinistro (`role="separator"`, frecce da tastiera
  ±20 px, Maiusc ±80). Minimo 380 px, massimo quanto lascia 300 px all'elenco. La larghezza si
  ricorda in localStorage. Le miniature crescono con la larghezza. La griglia scorre dentro un
  riquadro alto al massimo 440 px, e la pagina singola ha un'altezza massima, così l'elenco delle
  lezioni sotto resta visibile.
- **Viste:** Griglia e Una pagina alla volta (frecce ‹ › e "31 / 64"; frecce della tastiera fuori
  dai campi di testo; i suggerimenti dicono "(←)" e "(→)").
- **Selezione nella griglia come nel Finder:**
  - clic sceglie solo quella pagina, un secondo clic sulla sola pagina scelta la deseleziona;
  - Maiusc+clic seleziona l'intervallo dall'ultima pagina cliccata;
  - Cmd+clic (Ctrl su Windows) aggiunge o toglie una pagina;
  - Esc deseleziona.
- **Barra della selezione** (componente nuovo `frontend/src/components/ui/selection-bar.tsx`, lo
  userà anche il piano 10):
  - una barra bianca con bordo sottile (`border`), angoli arrotondati (10 px), ombra leggera,
    `padding 4px 6px`;
  - il conteggio in grigio piccolo ("3 pagine", "pag. 12" in vista singola);
  - poi solo pulsanti a icona 32 px trasparenti con suggerimento.
  - Pulsanti: Aggiungi ai media di una lezione (ImagePlus, blu), Ignora / Non ignorare (EyeOff /
    Eye), Ritaglia (Crop, solo con una pagina: altrimenti disattivato con "Una pagina alla volta"),
    Elimina per sempre (Trash2, rosso, con conferma).
- **Pagine ignorate:** tratteggiate e attenuate, con l'icona EyeOff piccola.
- **Ritaglia:** passa alla vista singola su quella pagina e mostra `MediaCropView` con Sovrascrivi la
  pagina e Salva come nuova immagine. Al salvataggio si torna alla pagina.
- **Riquadro Aggiungi** (dal `+` o da Aggiungi ai media), sotto l'intestazione del dettaglio:
  - Lezione: select con la lezione `da` preselezionata, poi le lezioni della materia, più recenti
    prima.
  - Solo per il `+`:
    - Pagine: se ci sono pagine selezionate, l'**elenco esatto** compresso ("1, 10", "1–3, 10") e
      niente campi; se non ce ne sono, due campi Da/A precompilati con `da_continuare` (o tutto il
      file);
    - Uso: tre pulsanti a icona Guida / Contesto / Integra (stesse icone e suggerimenti del piano 8),
      predefinito Contesto, col nome dell'uso scelto accanto in grigio.
  - Annulla e Aggiungi chiudono il riquadro; lo chiude anche ricliccare il pulsante che l'ha aperto o
    scegliere un altro file.
- Stati vuoti: elenco vuoto senza frasi lunghe (solo l'icona dell'archivio e "Nessun file").

## Test

- Pytest `tests/test_api_archive.py`:
  - elenco con filtri per materia, tipo e testo;
  - `da_continuare` calcolato dalle pagine usate (1–18 e 19–30 su 64 → "31–64");
  - ignorate e non ignorate; pagine eliminate sparite da `GET /archive/{sha}` e da
    `pages_for_use`;
  - ritaglio con e senza `sostituisci`;
  - `DELETE` rifiutato se usato;
  - `add-to-lesson` non chiama estrazione né trascrizione;
  - `add-to-media` copia solo le pagine scelte.
- Vitest (`frontend/src/components/archive/*.test.tsx`):
  - selezione con clic, Maiusc e Cmd/Ctrl;
  - frecce in vista singola;
  - compressione dell'elenco pagine;
  - campi Pagine assenti con pagine selezionate;
  - riquadro che si chiude con Annulla;
  - freccia indietro verso `/lezioni/<da>?panel=arricchimento`;
  - ridimensionamento con la tastiera.

## Changelog

- Nuova pagina Archivio, dal pannello Arricchimento: tutti i file mai aggiunti, con le pagine usate
  da ogni lezione. Le pagine si possono ignorare (l'AI non le legge più), ritagliare o eliminare, e
  un file o alcune sue pagine si aggiungono a un'altra lezione senza rielaborarli.
