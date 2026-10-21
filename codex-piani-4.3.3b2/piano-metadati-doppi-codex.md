# Piano 2 · Lezione con metadati già usati: dire quali e permettere di cambiarli

Agente: da assegnare all'avvio della b2. Oggi creare una lezione con data, materia e argomenti di una
lezione esistente fallisce **nel worker** con `ValueError: Esiste già una lezione con questi metadati`:
non dice quali, e "Riprova" rimanda lo stesso job che fallirà di nuovo.

(La causa più frequente, l'unione degli audio fallita che lasciava una lezione a metà, è già corretta
nella b1 con la PR #116.)

## Come si decide il doppione

`create_source_lesson` (`rt/services/materials_lesson_service.py`) e `create_notes_lesson`
(`rt/services/notes_lesson_service.py`): la cartella è `[<data>] <MATERIA>` + ` - <argomenti>` se ci
sono. Doppione = stessa **data**, stessa **materia** e stessi **argomenti** (anche vuoti). Docente e
ora non contano.

## Cosa fare

1. Funzione unica `find_lesson_conflict(date, materia, argomenti, dest_dir)` che costruisce il
   percorso come oggi e, se esiste, restituisce `{lesson_id, titolo, data, materia, argomenti}` della
   lezione esistente. Usala nei due servizi al posto del controllo attuale; l'errore diventa
   un'eccezione `LessonConflict` con quei dati.
2. **Controllo prima di accodare**: `POST /lessons` (`rt/api/routers/jobs.py:create_lesson`) e la rotta
   degli appunti chiamano `find_lesson_conflict` prima di creare il job e rispondono `409`
   `lesson_exists` con i dati sopra in `details`. Così il caso normale non arriva mai al worker.
3. Nel popup **Nuova lezione**: con il `409` il popup resta aperto con i dati inseriti; sotto i campi
   un avviso breve "Esiste già: <titolo della lezione esistente>" (link che la apre in una nuova
   scheda della SPA) e i campi **data, materia, argomenti** evidenziati in rosso. Cambiandone uno
   l'avviso sparisce e "Avvia" riprova.
4. Se il conflitto nasce comunque nel worker (due job in coda con gli stessi dati): il job fallisce con
   codice `lesson_exists` e i dati in `result`. Nella card del job in errore, accanto a "Riprova",
   compare un pulsante a icona "Cambia i dati" (`PencilLine`) che apre **Nuova lezione** precompilato
   con le fonti e le opzioni del job (i file sono già caricati: il payload ha i percorsi), con i campi
   in conflitto già evidenziati. "Riprova" in quel caso resta, ma con il suggerimento "Esiste già una
   lezione con questi dati".
5. Messaggio dell'errore: "Esiste già una lezione del 21/10/2026 di PATOLOGIA GENERALE" + " con
   argomenti «…»" se ci sono.

## Test

- pytest: `POST /lessons` con gli stessi data/materia/argomenti risponde 409 `lesson_exists` con la
  lezione esistente e nessun job; con argomenti diversi passa; docente e ora diversi non bastano.
- pytest: due job uguali in coda → il secondo fallisce con codice `lesson_exists` e i dati.
- vitest `NewLessonDialog`: con il 409 resta aperto, mostra l'avviso e i campi evidenziati; cambiando
  la materia l'avviso sparisce.
- vitest card del job: con `lesson_exists` c'è "Cambia i dati" e apre il popup precompilato.
