# Piano per Codex · 4.3.2b1 · Docenti per materia, suggeriti nel campo Docente, Invio nel calendario

Base: `claude/rt-4.3.2-beta`. Tre parti, tre commit, una PR.

## Richiesta (Attilio)
1. I docenti diventano una proprietà della materia: in Impostazioni › Materie si possono aggiungere uno o più docenti per ogni materia.
2. Quando si compila il campo "Docente" (aggiunta o modifica di un'ora nel calendario, Dettagli della lezione, Nuova lezione), il menu a tendina propone i docenti di quella materia. Si può sempre scrivere un nome nuovo, che viene aggiunto alla materia.
3. Nel popup del calendario "Aggiungi ora / Modifica ora" si conferma con Invio.

## Stato attuale
- Materie: tabella `subjects` (solo `nome`, migrazione `0018_subjects.py`), servizio `rt/services/subjects.py`. `_view` unisce le materie registrate a quelle usate da lezioni e calendario; `register_subject` registra in automatico quando si salva una lezione (`LessonRepository.update_fields`) o un'ora (`calendar_service`, righe con `register_subject(session, ...)`). API in `rt/api/routers/subjects.py`, client in `frontend/src/api/subjects.ts`, pagina `frontend/src/components/settings/subjects.tsx`.
- Docente: testo libero in `Lesson.docente`, `CalendarTemplateEntry.docente`, `CalendarOverride.docente`. Solo Nuova lezione ha suggerimenti (datalist con i docenti di tutte le lezioni, `NewLessonDialog.tsx` riga ~199). Calendario (`CalendarPopups.tsx`, campo Docente ~riga 605) e Dettagli (`DetailsPanel.tsx`, `details-teacher`) non ne hanno.
- Il popup del calendario non è un `<form>`: Invio non fa nulla, si conferma solo col pulsante ✓.

## 1. Backend: docenti della materia
- **Tabella** `subject_teachers` (migrazione `0019_subject_teachers.py`, `down_revision = "0018"`): `materia` String(256) e `nome` String(256), chiave primaria composta, più `creata_il`. Nel modello `rt/db/models.py`: `SubjectTeacher`. Il confronto di materia e nome è sempre senza maiuscole (`casefold`), come per le materie, ma si conserva la grafia scritta la prima volta.
- **Popolamento iniziale** nella migrazione: tutte le coppie (materia, docente) non vuote già presenti in `lessons`, `calendar_template_entries` e `calendar_overrides`, senza doppioni (casefold). Così Attilio ritrova subito i docenti che ha già scritto.
- **Registrazione implicita:** `register_teacher(session, materia, docente)` in `rt/services/subjects.py`, chiamata negli stessi tre punti di `register_subject` (lezione, ora della settimana tipo, ora di una settimana/intervallo) quando il docente non è vuoto. Questo copre il punto 2, "un nome nuovo viene aggiunto alla materia".
- **Vista:** `SubjectView` aggiunge `docenti: list[str]`, ordinati alfabeticamente. Sono i docenti registrati per quella materia: niente unione dinamica con le lezioni, così un docente tolto resta tolto.
- **API:**
  - `POST /subjects/{nome}/teachers` con corpo `{nome}`: 201 con la materia aggiornata. 409 `teacher_exists` se c'è già, 404 se la materia non esiste. Se la materia è solo "usata" (non ancora nella tabella `subjects`), registrarla prima.
  - `DELETE /subjects/{nome}/teachers/{docente}`: 204. Toglie solo il docente dall'elenco; le lezioni e le ore già salvate non cambiano.
  - Rigenerare `frontend/src/api/schema.d.ts` con lo script del repo e spostare `subjects.ts` sui tipi generati, se semplice.
- `delete_subject` cancella anche i suoi docenti.

## 2. Frontend
- **Impostazioni › Materie** (`subjects.tsx`): sotto il nome di ogni materia, una riga con i docenti come piccole etichette (`rounded-full border px-2 text-meta`), ciascuna con una X "Togli <docente> da <materia>". In fondo alla riga un campo compatto "Aggiungi docente" (Invio o + per aggiungere). Gli errori nell'`Alert` già presente. Aggiornare il testo introduttivo: "Ogni materia ha i suoi docenti, proposti quando compili il campo Docente. Un docente scritto in una lezione o nel calendario si aggiunge da solo."
- **Suggerimenti nel campo Docente:** un hook `useTeacherSuggestions(materia: string)` in `frontend/src/api/subjects.ts`. Restituisce i docenti della materia (match casefold). Se la materia è vuota o sconosciuta, restituisce tutti i docenti di tutte le materie, senza doppioni.
  Usarlo con un `<datalist>` (come per le materie) in:
  - `CalendarPopups.tsx`, campo Docente (segue la materia scritta nel popup);
  - `DetailsPanel.tsx`, campo `details-teacher` (segue la materia selezionata);
  - `NewLessonDialog.tsx`, sostituendo l'elenco attuale preso dalle lezioni (segue la materia del form).
  Il datalist propone e non obbliga: il testo libero resta valido.
- Dopo un salvataggio che può aver aggiunto un docente (ora del calendario, metadati della lezione, nuova lezione), invalidare `subjectsKeys.all`.

## 3. Invio nel popup del calendario
- In `CalendarPopups.tsx` avvolgere i campi in un `<form onSubmit>`. Il pulsante ✓ diventa `type="submit"`; Annulla resta `type="button"`. Spostare in `onSubmit` la logica che oggi è nell'`onClick` di ✓ (con `preventDefault`).
- Invio in qualunque campo conferma, se la materia non è vuota. Se il menu dei suggerimenti è aperto, il primo Invio sceglie la voce, come fa il browser.
- Escape continua a chiudere.

## Test
- pytest (`tests/test_subjects*.py`, `tests/test_calendar*.py`):
  - la migrazione 0019 popola le coppie da lezioni e calendario senza doppioni di maiuscole;
  - POST e DELETE dei docenti, con 409 e 404;
  - salvare una lezione o un'ora con un docente nuovo lo registra sulla materia;
  - togliere un docente non modifica le lezioni;
  - `delete_subject` toglie i suoi docenti.
- vitest:
  - Materie: aggiungere e togliere un docente chiama le API giuste e aggiorna la riga;
  - popup del calendario: il datalist del Docente contiene i docenti della materia scritta e cambia se cambia la materia; Invio nel campo Fine chiama `onAdd` e chiude; con materia vuota Invio non fa nulla;
  - Dettagli e Nuova lezione: il datalist del Docente segue la materia.

Comandi: `python -m pytest -q`, `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`.

## Changelog
Sezione 4.3.2b1, Novità:
- "Ogni materia ha i suoi docenti: si aggiungono in Impostazioni › Materie, e il campo Docente del calendario, dei Dettagli e di Nuova lezione li propone. Un docente nuovo scritto lì si aggiunge da solo alla materia."
- "Nel calendario un'ora si aggiunge o si salva anche con Invio."
