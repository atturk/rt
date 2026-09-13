# Task 52 — `llm_debug.log` non registra quale credenziale/route reale è stata usata per ogni chiamata

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Durante l'analisi di un 429 reale su una lezione, `llm_debug.log` (il file di debug per-lezione
scritto da `_append_debug_log`) si è rivelato insufficiente a diagnosticare con precisione quale
credenziale round-robin (es. `google_9` vs `google_10`) avesse effettivamente fallito o avuto
successo in ciascun tentativo: il log riporta solo `route_role` (un'etichetta come
`"round_robin_9"`, `"fallback_alternative_configured"`), non l'identità reale della credenziale
(`credential_ref`, es. `"google_9"`) né il `route_id` completo.

**Causa**: `rt/llm/client.py`, nei due punti dove viene costruito l'oggetto scritto su
`llm_debug.log` — `debug_entry` (righe 854-873, caso successo) e `err_debug_entry` (righe
982-1001, caso errore) — questi dizionari sono costruiti a mano ed omettono `credential_ref` e
`route_id`, anche se ENTRAMBI i valori sono già disponibili come variabili locali in quel punto
del codice (righe 299, 304: `route_id = route.route_id`, `credential_ref = route.credential or
...`) e vengono correttamente inclusi nel `LLMTelemetryRecord` completo passato a
`GLOBAL_TELEMETRY.add(...)` (righe 815-825 e 949-959) — solo la versione scritta su file per il
debug per-lezione li perde.

## Modifica

Aggiungi `"credential_ref": credential_ref` e `"route_id": route_id` a entrambi i dizionari
(`debug_entry` righe 854-873, `err_debug_entry` righe 982-1001), usando le stesse variabili
locali già in scope in quel punto (verifica che siano effettivamente in scope a entrambi i call
site — se per l'errore il nome della variabile locale è diverso, verifica e usa quella corretta,
es. potrebbe essere `current_exec_route.credential`/`current_exec_route.route_id` invece delle
variabili `route_id`/`credential_ref` usate nel ramo di successo, a seconda di come sono
strutturate le variabili locali in quel punto specifico del codice — leggi il contesto
circostante prima di scegliere quale usare, l'importante è che il valore scritto corrisponda
realmente alla credenziale usata in QUEL tentativo specifico).

Aggiungi anche `"failure_class"` (già presente nel `LLMTelemetryRecord` completo, es.
`classified_failure.failure_class`/l'equivalente già calcolato in quel punto per
`err_rec`) a `err_debug_entry`, se non già presente — utile per distinguere rapidamente
`rate_limit` da `timeout`/`auth_error`/altro leggendo solo il debug log senza dover fare
parsing di `error_message`.

## Test

- Test che verifica che, dopo una chiamata `call_structured` mockata con una route/credenziale
  nota, l'entry scritta (mockando o catturando `_append_debug_log`) includa `credential_ref` e
  `route_id` corretti sia nel caso di successo sia in quello di errore.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Non toccare la struttura di `LLMTelemetryRecord`/
`GLOBAL_TELEMETRY`: già corretta, il gap è solo nel dizionario scritto su file.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Verifica manualmente (anche con `--mock`) che una riga di `llm_debug.log` prodotta da una
   chiamata reale includa ora `credential_ref`/`route_id` popolati, non `null`.
