# Task 49 — `/list` dice "nessuna lezione trovata" senza spiegare che la lezione potrebbe essere fuori da `lessons_root`

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

L'utente ha creato una lezione con successo (build completata, notifica Telegram ricevuta), ma
`/list` nel topic corrispondente risponde "Nessuna lezione trovata per questo topic." — un
messaggio generico che non aiuta a capire il problema.

**Causa verificata**: `rt/telegram/daemon.py::handle_list_command` (righe 144-183) enumera le
lezioni con `scan_lessons(runtime_cfg.lessons_root)` (`rt/core/lesson_index.py`, righe 22-48),
che elenca **solo le sottocartelle DIRETTE** di `lessons_root` (non ricorsivo). Se una lezione
viene creata in una cartella che non è una sottocartella diretta di `lessons_root` configurato
in `rt config` (es. l'utente lancia `rt run` su un file altrove, tipo direttamente sul Desktop,
mentre `lessons_root` punta a una sottocartella specifica), `scan_lessons` non la troverà mai —
comportamento tecnicamente corretto rispetto a come `lessons_root` è definito, ma il messaggio
d'errore a riga 174 non lo comunica: è identico sia che non esista NESSUNA lezione sia che la
lezione esista ma sia fuori dal percorso indicizzato. Da notare: la notifica di build completata
(Task 48) e la sua ricezione con successo sono un percorso di codice completamente indipendente
da `/list` — non è contraddittorio che l'una funzioni e l'altro no.

## Modifica

In `handle_list_command`, quando `scoped` (l'elenco filtrato di lezioni per il topic) risulta
vuoto DOPO `scan_lessons`, distingui il messaggio in base a cosa succede:
- Se `entries` (il risultato grezzo di `scan_lessons`, prima del filtro per materia) è
  anch'esso vuoto: la cartella `lessons_root` stessa non contiene alcuna lezione — messaggio
  esplicito che menzioni il percorso configurato (es. `f"Nessuna lezione trovata in
  '{runtime_cfg.lessons_root}'. Se hai appena creato una lezione altrove, verifica che sia dentro
  questa cartella (configurabile con 'rt config' o 'rt config --telegram'), oppure spostala/
  copiala lì."`).
- Se `entries` non è vuoto ma il filtro per materia (`filter_by_materia`/`filter_unmapped`) ha
  scartato tutto: la cartella ha lezioni ma nessuna per QUESTA materia/topic — messaggio diverso
  che lo chiarisca (es. "Nessuna lezione trovata per la materia di questo topic. Ci sono
  {len(entries)} lezioni totali in altri topic/materie.").

Non serve rendere `scan_lessons` ricorsivo o cambiare `lessons_root` — è un cambiamento di
messaggistica, non di logica di scoping (che resta corretta e intenzionale).

## Test

- Test con `lessons_root` che punta a una cartella vuota: verifica il nuovo messaggio esplicito
  che menziona il percorso configurato.
- Test con `lessons_root` che contiene lezioni ma nessuna per la materia del topic corrente:
  verifica il messaggio che distingue questo caso (menziona il conteggio di lezioni esistenti
  in altre materie).
- Verifica che il caso "lessons_root non configurato affatto" (righe 155-158, già gestito
  esplicitamente) resti invariato.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale: crea una lezione fuori da `lessons_root` in una cartella di test, verifica
   che `/list` ora dia un messaggio che permette di capire il problema invece del generico
   "nessuna lezione trovata".
