# Task 46 — Bug di rendering: le card del wizard `rt config` si duplicano invece di sostituirsi

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Test reale: dopo aver completato il sotto-questionario di creazione di un nuovo profilo modello
(`_create_new_model_profile`) per la prima card (fase "outline"), la card successiva ("rewrite")
appare STAMPATA SOTTO quella precedente nel terminale invece che al posto di essa — il log
incollato dall'utente mostra pannelli `╭─── 🤖 FASE [N/5] ───╮` che si accumulano uno sotto
l'altro invece di sostituirsi in place, ripetutamente, ogni volta che si apre il sotto-flusso di
creazione profilo per una nuova fase.

**Ipotesi più probabile, verificata leggendo il codice**: `_configure_llm_provider_section`
(`rt/pipeline/configure.py`, righe ~778-940) usa `rich.Live` per il rendering della card
corrente, ma attorno all'invocazione di `_create_new_model_profile` (che stampa molte righe
normali via `questionary`/`print`, NON un programma a schermo intero come un editor esterno) fa
semplicemente:
```python
live.stop()
p_name, p_dict = _create_new_model_profile(config_dir, env_path, general_data, default_name_hint=group_jobs[0])
...
live.start()
```
`Live` in Rich, quando viene fermato e poi riavviato, riprende a disegnare dalla posizione
CORRENTE del cursore — non sa che, mentre era fermo, `_create_new_model_profile` ha stampato un
numero arbitrario di righe (domande, risposte, messaggi) che hanno fatto avanzare il cursore
molto più in basso. Il prossimo `live.update()` disegna quindi il pannello della card successiva
partendo da quella nuova posizione, sotto tutto quello che è stato stampato nel frattempo,
anziché sovrascrivere l'area dove si trovava l'ultimo pannello — risultato visivo: pannelli che
si accumulano invece di sostituirsi.

Per confronto, lo stesso pattern `live.stop()`/`live.start()` in `rt/pipeline/issue_review.py`
(attorno a `edit_text_in_editor()`, un editor esterno a schermo intero tipo vim/nano) NON mostra
questo problema — perché un editor a schermo intero pulisce e ripristina lo schermo per conto
suo all'uscita, lasciando il cursore in una posizione nota, mentre `_create_new_model_profile`
si limita a stampare righe normali senza alcun ripristino dello schermo.

## Modifica

Prima di implementare, verifica EMPIRICAMENTE il comportamento in un vero terminale interattivo
(non fidarti solo di questa ipotesi) per confermare che il problema si manifesta esattamente
attorno al ciclo `live.stop()`/`_create_new_model_profile()`/`live.start()` e non altrove.

Fix proposto: subito prima di `live.start()` (dopo che `_create_new_model_profile` è tornato),
forza un reset pulito dello schermo così il prossimo render parte da uno stato noto:
```python
live.stop()
p_name, p_dict = _create_new_model_profile(...)
...
console.clear()
live.start()
```
Verifica che `console` sia la stessa istanza usata per costruire `Live(console=console, ...)` a
monte (riga ~776-779) — se `_create_new_model_profile` stampa usando un `Console()`/`print()`
diverso, verifica comunque che un `console.clear()` sullo stesso oggetto `Console` prima di
`live.start()` risolva il problema. Se questo approccio non basta empiricamente, valuta
l'alternativa più robusta: invece di riusare lo stesso oggetto `Live`, chiudi il blocco `with
Live(...) as live:` prima del sotto-questionario e riaprine uno NUOVO (`with Live(...) as
live:`) al rientro nel carosello — un nuovo `Live` all'apertura pulisce sempre il proprio stato
interno.

Applica lo stesso fix a QUALUNQUE altro punto di `_configure_llm_provider_section` che fa
`live.stop()` seguito da output non a schermo intero prima di `live.start()` (verifica se ce ne
sono altri oltre a questo).

## Test

Dato che il bug è di rendering interattivo, è difficile da testare con un assert automatico
diretto sul contenuto visivo. Copri almeno:
- Un test che verifica che `console.clear()` (o l'equivalente fix scelto) venga effettivamente
  chiamato tra la chiusura del sotto-questionario e la ripresa di `Live` (mocka `console.clear`
  e verifica che sia stato chiamato dopo `_create_new_model_profile`).
- Se possibile, un test che cattura l'intero output stdout durante una sessione simulata
  (mockando `read_single_key` e `_create_new_model_profile`) e verifica che la sequenza di
  escape ANSI prodotta contenga un clear-screen (`\033[2J` o `\033[H`) immediatamente prima del
  render della card successiva.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Leggi la nota su come isolare l'ambiente di test da `config/`
reale prima di qualunque verifica funzionale diretta.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale interattivo REALE (non solo mockato) in un terminale vero: lancia `rt config`,
   crea un nuovo profilo per la prima fase, verifica visivamente che la card della fase
   successiva sostituisca quella precedente invece di apparire sotto di essa. Questo è
   l'unico modo per confermare davvero il fix su un bug di questo tipo — documentalo
   esplicitamente nel riepilogo finale.
