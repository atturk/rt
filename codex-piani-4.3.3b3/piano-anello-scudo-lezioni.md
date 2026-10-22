# Piano 8 · Elenco lezioni: spunta nell'anello, scudo solo se verificata

Agente: da assegnare all'avvio della b3. Richiesta di Attilio (22/10/2026) sugli indicatori a destra di
ogni lezione (`frontend/src/components/lessons/LessonsView.tsx`, `StudyRing` e `ReviewShield`).

## Anello dello studio

Se **tutte** le unità hanno uno stato diverso da "da apprendere", cioè
`study_learned + study_learning + study_ignored >= unit_count` (con `unit_count > 0`), dentro
l'anello compare una **spunta** piccola (tratto sottile, colore `text-study-learned`, centrata,
circa metà del diametro). L'anello resta disegnato come oggi; tooltip e link invariati.
Se una sola unità è ancora "da apprendere", niente spunta.

## Scudo della verifica

Lo scudo compare **solo** quando la lezione è verificata (`phases.review === 'VALID'` e
`pending_issues === 0`), con il colore attuale di "Verifica fatta". Nei casi che oggi mostrano lo
scudo giallo ("Verifica da fare", issue da decidere) non compare nulla. Lo spazio della colonna
resta, così gli anelli restano allineati fra le righe.

## Test

Vitest su `LessonsView`/`StudyRing`: spunta con tutte le unità in uno stato diverso da "da
apprendere" (anche miste fra apprese, in apprendimento, ignorate), nessuna spunta con una "da
apprendere"; scudo presente solo con review VALID e 0 issue, assente con review da fare o issue
aperte. Aggiornare gli e2e che oggi cercano `lesson-review-shield` su lezioni non verificate.
