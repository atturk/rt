# Task 68 — Rimuovi `rt/core/keyboard.py`, ora orfano dopo la migrazione a Textual

Ultimo dei 5 task di migrazione a Textual (64-68). **Esegui questo task solo dopo che i Task 64,
65, 66 e 67 sono TUTTI completati e verificati** — prima di allora `rt/core/keyboard.py` è ancora
usato da almeno uno dei 4 file migrati. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

`rt/core/keyboard.py` (`read_single_key`, `raw_mode`, parsing manuale delle sequenze ANSI per le
frecce) esisteva solo per alimentare i 4 caroselli `rich.Live` migrati a Textual nei Task 64-67.
Con Textual, che gestisce l'input da tastiera internamente, questo modulo non ha più alcun
consumatore.

## Modifica

1. Esegui `grep -rn "rt.core.keyboard\|from rt.core import keyboard\|read_single_key\|raw_mode"
   rt/ tests/` per confermare che NESSUN file di produzione lo importi più (i 4 file migrati non
   devono più comparire in questo grep, a parte eventuali import residui dimenticati durante i
   Task 64-67 — se ne trovi, è un segnale che uno dei task precedenti ha lasciato codice morto:
   ripulisci anche quello).
2. Se il grep conferma che è orfano: elimina `rt/core/keyboard.py`.
3. Elimina anche il file di test dedicato, se esiste (`grep -rl "rt.core.keyboard\|read_single_key\|
   raw_mode" tests/` per trovarlo).
4. Se il grep al punto 1 trova ANCORA un uso reale in produzione (uno dei Task 64-67 non ha
   completato la migrazione per qualche ramo di codice), NON eliminare il modulo: segnala
   esattamente quale file/riga lo usa ancora e fermati, non è compito di questo task completare
   una migrazione lasciata a metà da un task precedente.

## Test

Esegui `python3 -m pytest tests/ -q` — deve continuare a passare per intero (la rimozione di un
modulo orfano non deve rompere nulla; se qualcosa si rompe, il modulo non era davvero orfano).

## Vincoli

Nessuna modifica funzionale oltre alla rimozione del modulo orfano e del suo test dedicato.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. `grep -rn "rt.core.keyboard\|read_single_key\|raw_mode" rt/ tests/` non deve produrre alcun
   risultato.
3. Riepiloga in chat lo stato finale dell'intera migrazione (Task 64-68): le 4 schermate ora su
   Textual, il modulo `keyboard.py` rimosso, ed esplicitamente se il bug di duplicazione delle card
   è confermato risolto su tutte e 4 (non solo sul pilota del Task 64).
