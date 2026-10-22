# RT 4.3.3b3 · piani

La b2 è stata la correzione degli aggiornamenti dall'app (come la 4.3.2.2): questi piani vanno nella b3.
Via di Attilio il 22/10/2026. Codex: piani 1, 2, 9, 8 sul ramo `codex/4.3.3b3`; agy: piani 5, 3, 4, 6, 7 sul ramo `agy/4.3.3b3`. Istruzioni in `TASK-codex.md` e `TASK-agy.md`.

| # | Piano | Agente |
|---|-------|--------|
| 1 | `piano-esporta-importa-codex.md`: Esporta tutto e Importa nel menu dell'app, senza chiavi API | Codex |
| 2 | `piano-metadati-doppi-codex.md`: lezione con metadati già usati, dire quali e permettere di cambiarli | Codex |
| 3 | `piano-invio-tastiera.md`: ⌘/Ctrl + Invio invia la risposta scritta, Invio va a capo | agy |
| 4 | `piano-campi-senza-bordo.md`: niente bordo nero di focus nei campi di testo | agy |
| 5 | `piano-formule-domande.md`: formule in LaTeX nelle domande generate | agy |
| 6 | `piano-formule-lettura-veloce.md`: formule lunghe adattate alla loro misura reale e centrate | agy |
| 7 | `piano-rumore-timer-lettura.md`: dissolvenza di 1 s sul rumore e conto alla rovescia (0–10 s) prima della lettura veloce | agy |
| 8 | `piano-anello-scudo-lezioni.md`: spunta nell'anello a unità tutte con uno stato, scudo solo se verificata | Codex |
| 9 | `piano-lezioni-mancanti.md`: inizio del periodo accademico e avviso delle lezioni mancanti per materia | Codex |

Già nella b1 (PR #116): l'unione di più audio in una nuova lezione non fallisce più e non lascia lezioni a metà.
