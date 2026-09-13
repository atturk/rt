# Task 71 — Nuovo comando `rt cost <cartella> [--split]`

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

L'utente vuole un comando per vedere il costo cumulativo di TUTTE le chiamate LLM fatte finora su
una lezione — outline, rewrite, review, generazione domande di recall, valutazione risposte di
recall — indipendentemente da quante volte si è rilanciata una fase, rigenerata l'outline, o fatta
una sessione di recall in più.

**Buona notizia, verificata nel codice, non serve nuova infrastruttura di logging**: `rt/llm/
client.py::_append_debug_log` scrive già, in modalità APPEND (mai troncato, riga
`open(log_path, "a", ...)`), una riga JSON per OGNI tentativo di chiamata LLM (successo o
fallimento) in `<lesson_dir>/_state/llm_debug.log`, con almeno questi campi rilevanti:
`timestamp`, `execution_id`, `job`, `unit_id`, `provider`, `model`, `route_role`,
`credential_ref`, `attempt`, `status` (`"success"` o `"error"`/`"timeout"`), `failure_class` (solo
sui fallimenti), `estimated_cost`. Verificato che TUTTI i job cognitivi ci scrivono, incluse le
generazioni/valutazioni di recall (`rt/pipeline/recall.py`, righe 446/515/535, passano tutte
`lesson_dir=lesson_dir` a `client.call_structured`) — quindi il costo di generazione domande e
valutazione risposte è GIÀ loggato lì, contrariamente al dubbio dell'utente.

`rt cost` deve quindi limitarsi a LEGGERE e SOMMARE questo file esistente, non introdurre un
ledger separato.

## Comportamento richiesto (deciso con l'utente)

- **`rt cost <cartella>`** (nessun flag) = **overview**: costo totale cumulativo (somma di
  `estimated_cost` su TUTTE le righe del file, incluse quelle con `status` di errore/fallimento —
  l'utente ha confermato esplicitamente di volerle contare: rappresentano soldi spesi comunque,
  anche se il tentativo non è andato a buon fine), più un elenco compatto di sottototali per
  `job` (nome job, numero di chiamate, costo totale di quel job) — non serve il dettaglio per
  `unit_id` in questa modalità.
- **`rt cost <cartella> --split`** = **debug dei costi**, massimo dettaglio possibile: per
  ciascun `job`, mostra il sottototale E il dettaglio per `unit_id` all'interno di quel job (dove
  presente — alcuni job come `outline`/`recall_quiz` potrebbero non avere `unit_id` per-riga,
  verifica caso per caso leggendo righe reali di `llm_debug.log`); per ciascun `unit_id`, mostra
  OGNI tentativo registrato (successo e fallito) con almeno: numero di tentativo, esito
  (successo/classe di errore), provider/modello/route usati, costo di quella singola riga. È
  pensato per capire ESATTAMENTE da dove viene ogni centesimo speso, quindi preferisci più
  dettaglio a meno, seguendo lo stile già usato da `rt status`/altri comandi diagnostici del
  progetto per la formattazione testuale (non serve una tabella complessa, righe indentate ad
  albero sono sufficienti — guarda `rt/cli.py::cmd_status` per lo stile esistente da imitare).
- Se `llm_debug.log` non esiste o è vuoto: messaggio chiaro tipo "Nessun dato di costo disponibile
  per questa lezione (nessuna chiamata LLM registrata)" — MAI mostrare "$0.00" come se fosse un
  dato reale quando in realtà manca il file.
- Righe malformate/non parsabili come JSON nel file (should not happen, ma il file è scritto in
  append senza garanzie di atomicità perfetta) vanno IGNORATE silenziosamente riga per riga, non
  devono far crashare l'intero comando.
- Valuta se sommare `estimated_cost` solo quando non è `None`/mancante (righe con costo non
  calcolabile, es. errore prima di ricevere token, vanno escluse dalla somma ma possono comunque
  comparire nel dettaglio `--split` con costo "N/D" o simile, per trasparenza totale).

## Implementazione

- Nuova funzione, es. `rt/pipeline/cost.py::compute_lesson_cost(lesson_dir, split=False) ->
  <struttura dati>` che legge e parsa `llm_debug.log` (usa `lesson_path(lesson_dir,
  "llm_debug.log")`, stesso helper già usato da `_append_debug_log`) e produce i dati aggregati;
  una funzione separata per il rendering testuale (`render_cost_summary`/`render_cost_split`),
  seguendo la separazione dati/presentazione già usata altrove nel progetto (es. `rt/telegram/
  formatting.py` per il pattern generale, anche se qui il rendering è per terminale non Telegram).
- Nuovo subcommand in `rt/cli.py`: `rt cost <lesson_dir> [--split]`. È un comando "niche"
  (diagnostico, non tra i comandi principali) — segui lo stesso trattamento già dato dal Task 61
  ai "Comandi diagnostici" in `RTHelpFormatter` (help=argparse.SUPPRESS sul subparser + riga
  manuale nell'epilogo dell'help, stesso blocco/stile degli altri comandi diagnostici esistenti).

## Test

- Test con un `llm_debug.log` sintetico contenente più job, più unit_id, mix di successi e
  fallimenti con `estimated_cost` variabili (incluso almeno una riga con `estimated_cost: null` e
  una riga di fallimento CON un costo parziale non nullo): verifica che `rt cost` (overview) somma
  correttamente il totale INCLUDENDO i fallimenti con costo non nullo, ed ESCLUDENDO le righe con
  costo nullo dalla somma (ma non dal conteggio delle chiamate, se mostri anche quello).
- Test che verifica il sottototale per-job nell'overview (nomi job e importi corretti).
- Test che verifica che `--split` mostri il dettaglio per `unit_id` e le singole righe/tentativi,
  con la classe di errore visibile per i tentativi falliti.
- Test per file mancante/vuoto: messaggio chiaro, nessun crash, nessun "$0.00" fuorviante.
- Test per righe malformate nel file (una riga JSON non valida in mezzo a righe valide): il resto
  del calcolo prosegue correttamente, nessun crash.
- Test che verifica la registrazione del subcommand in `rt -h` (non compare nella sezione
  "Comandi principali", compare nell'elenco manuale dei comandi diagnostici nell'epilogo — stesso
  schema di verifica già usato in `tests/test_cli_help_reorganization.py` per gli altri comandi
  diagnostici).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non modificare `_append_debug_log`/il formato delle righe scritte in `llm_debug.log`: questo task
è solo di LETTURA/aggregazione di dati già esistenti, non tocca la scrittura.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se disponibile una lezione reale con `llm_debug.log` popolato da più fasi/sessioni di recall,
   lancia `rt cost <cartella>` e `rt cost <cartella> --split` e verifica manualmente che i numeri
   abbiano senso rispetto al riepilogo costi già stampato a fine `rt run`/`rt review`.
