# Task 70 — `max_attempts` deve garantire di raggiungere il fallback anche con pool round-robin grandi

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Il Task 63 ha introdotto l'esaurimento completo del pool round-robin PRIMA di scattare verso il
fallback dedicato (`rt/llm/router.py::select_fallback_route`). Bug scoperto analizzando log reali
(`llm_debug.log`) su una config reale: un job round-robin con **6** chiavi (`primary_routes`) e
`max_attempts: 3` (valore scelto dall'utente PRIMA che il Task 63 esistesse, quando bastava per
"1 tentativo primario + 1 fallback") — un errore sistemico che colpisce indistintamente tutte le
chiavi del pool (es. 503 "high demand" su Google, non isolato a una singola chiave) esaurisce il
cap di 3 tentativi ciclando SOLO 3 delle 6 chiavi, senza mai raggiungere `fallback.generic`
configurato. Confermato riga per riga: `route_role` risultava sempre `round_robin_N` o
`fallback_alternative_configured` (altre chiavi dello stesso pool), mai `fallback_generic`.

**Causa esatta**: `rt/llm/client.py` riga 247, `max_global_attempts = 1 if (override_provider or
override_credential) else job_routing_cfg.max_attempts` — questo valore governa SIA il loop
esterno (`while route_attempt <= max_global_attempts:`, riga 294) SIA il check interno di
`select_fallback_route` (`if current_attempt >= job_cfg.max_attempts: return None`, in
`router.py`). Nessuno dei due tiene conto di quante route esistono nel pool round-robin
(`job_routing_cfg.effective_routes`, proprietà già esistente in `rt/core/config.py`).

## Comportamento richiesto (deciso con l'utente)

`max_attempts` configurato dall'utente resta il valore di riferimento per i job SENZA pool
round-robin (o con pool piccoli). Ma per un job round-robin, il cap EFFETTIVO usato internamente
deve garantire SEMPRE almeno un tentativo oltre l'esaurimento completo del pool, così il fallback
dedicato (se configurato) viene sempre raggiunto — senza che l'utente debba calcolare/aggiornare
manualmente `max_attempts` in base al numero di chiavi. L'utente non deve fare nulla: il
comportamento si applica automaticamente.

## Modifica

- In `rt/llm/client.py`, riga 247: calcola un `max_global_attempts` che, per i job con
  `round_robin=True` (o più in generale con `len(job_routing_cfg.effective_routes) > 1`), sia
  `max(job_routing_cfg.max_attempts, len(job_routing_cfg.effective_routes) + 1)` — **tranne** che
  per il caso `override_provider`/`override_credential`, che deve restare fissato a `1` come oggi
  (nessuna modifica a quel ramo).
- Applica la STESSA logica di calcolo in `rt/llm/router.py::select_fallback_route`, dove oggi il
  check è `if current_attempt >= job_cfg.max_attempts: return None` (riga ~120 dell'attuale
  implementazione post-Task-63) — deve usare lo stesso valore effettivo, non il
  `job_cfg.max_attempts` grezzo, altrimenti il router taglierebbe la catena anche se il loop
  esterno in `client.py` avesse più iterazioni disponibili.
- Centralizza il calcolo in un unico punto per evitare divergenze tra `client.py` e `router.py`
  (es. una funzione/proprietà tipo `JobRoutingConfig.effective_max_attempts` in
  `rt/core/config.py`, calcolata da `max_attempts` ed `effective_routes`, usata da entrambi i
  file invece di ricalcolarla due volte in modo indipendente).
- Non modificare il valore SALVATO in `general.yaml`/`config/rt/*.yaml`: `max_attempts` resta
  quello scritto dall'utente, il boost è solo un comportamento interno a runtime (se in futuro
  serve mostrarlo esplicitamente all'utente in `rt config`/`rt status`, valuta se ha senso ma non è
  richiesto in questo task).

## Test

- Test con pool round-robin di 6 route e `max_attempts: 3` configurato: un errore che colpisce
  TUTTE le 6 route deve comunque risultare, alla fine, in un tentativo sulla route di
  `fallback.generic` configurata (verifica `route_role == "fallback_generic"` o simile
  nell'ultima route tentata), non un fallimento prematuro dopo solo 3 tentativi.
- Test che verifica che un job SENZA round-robin (`primary` singolo, nessun `primary_routes`)
  mantenga il comportamento esistente invariato: `max_attempts` grezzo continua a valere così
  com'è, nessun boost applicato (non ha senso boostare un pool di dimensione 1).
- Test che verifica che `override_provider`/`override_credential` continuino a forzare esattamente
  UN tentativo, boost escluso.
- Aggiorna/verifica gli scenari esistenti in `tests/test_llm_router.py` legati al Task 63
  (`test_round_robin_pool_exhaustion_before_dedicated_fallback` e affini) — potrebbero già
  configurare `max_attempts` sufficientemente alto per il pool di test usato e non essere
  affetti, ma verificalo esplicitamente invece di assumerlo.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare la logica di cooldown/contatore fallback-consecutivi del Task 63: questo task
riguarda solo QUANTI tentativi sono disponibili in totale, non il comportamento di
esaurimento-pool-poi-fallback né il cooldown, entrambi già corretti.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se possibile, riproduci con un mock che il fallback generico scatti effettivamente dopo aver
   esaurito un pool di 6 route con `max_attempts: 3` configurato nel file di job.
