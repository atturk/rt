# Task 24 — Round-robin su N route (non solo 2)

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare. Il Task 25 (wizard `rt config`
per N chiavi) dipende da questo: completalo per primo.

## Contesto

L'utente vuole distribuire le chiamate LLM di un job su un numero arbitrario di chiavi/account
(es. 9 chiavi API per lo stesso provider), non solo 2. Il modello di configurazione lo permette
già in parte: `JobRoutingConfig.primary_routes: Optional[List[RouteConfig]]`
(`rt/core/config.py:144`) accetta una lista di lunghezza arbitraria, ed è già validato/caricato
correttamente da YAML (vedi `tests/test_llm_config.py::test_load_config_with_primary_routes_list_yaml`,
oggi testato solo con 2 elementi). Il registro credenziali (`rt/llm/credentials.py`) è già
generico: non c'è alcun limite a 2 credenziali per provider, si possono registrare
`google_1`...`google_9` (o `openrouter_1`...`openrouter_9`) ciascuna con il proprio `env_var`.

**Il vero limite è solo in `rt/llm/router.py::RoutingEngine.select_initial_route`**
(righe 84-102): quando `round_robin: true`, alterna SOLO `primary`/`secondary` con
`count % 2`, ignorando qualunque route oltre la seconda anche se `primary_routes` ne contiene
di più (`model_post_init` in `rt/core/config.py:151-155` usa `primary_routes` solo per
popolare `primary`/`secondary` con i primi due elementi, il resto della lista non viene mai
usato per lo scheduling round-robin, solo come candidati di fallback nella cascata di errore
già esistente in `router.py:169-177`).

## Modifiche

### 1. `rt/llm/router.py::select_initial_route`

Generalizza la selezione round-robin per usare l'intera lista di route configurate, non solo
`primary`/`secondary`:

```python
def select_initial_route(self, job_name: str) -> ExecutionRoute:
    job_cfg = self._get_job_config(job_name)

    if job_cfg.round_robin:
        routes = job_cfg.primary_routes if job_cfg.primary_routes else [
            r for r in (job_cfg.primary, job_cfg.secondary) if r is not None
        ]
        if len(routes) >= 2:
            with self._lock:
                count = self._rr_counters.get(job_name, 0)
                self._rr_counters[job_name] = count + 1
            idx = count % len(routes)
            role = "primary" if idx == 0 else f"round_robin_{idx + 1}"
            return ExecutionRoute(route=routes[idx], route_role=role)

    return ExecutionRoute(route=job_cfg.primary, route_role="primary")
```

Nota: `route_role` è un campo puramente descrittivo/di telemetria (vedi `rt/llm/telemetry.py`,
`rt/llm/client.py`) — nessun codice esistente fa branching sulla stringa esatta "secondary", quindi
è sicuro sostituirla con un'etichetta più informativa (`round_robin_2`, `round_robin_3`, ...) per
N > 2. Verifica comunque, prima di modificare, che nessun test asserisca
`route_role == "secondary"` per la selezione iniziale (l'ho già verificato io: non ce n'è nessuno
per `select_initial_route`, solo per i path di fallback che restano invariati da questo task).

I test esistenti (`tests/test_llm_router.py::test_round_robin_selection_alternation`,
`test_round_robin_disabled`) devono continuare a passare invariati (verificano solo `route_id`,
non `route_role`, quindi non sono sensibili alla rietichettatura).

### 2. `rt/core/config.py` — messaggio di validazione

Il controllo esistente in `JobRoutingConfig.model_post_init`:
```python
if self.round_robin and not self.secondary:
    raise ValueError("Configurazione non valida: round_robin è abilitato ma manca la route 'secondary'.")
```
resta corretto (richiede comunque almeno 2 route, che sia via `primary`+`secondary` espliciti o
via `primary_routes` con ≥2 elementi — `secondary` viene già popolato automaticamente da
`primary_routes[1]` se presente). Aggiorna solo il messaggio d'errore perché non assuma che
l'utente stia necessariamente usando la sintassi `secondary:` (potrebbe usare `primary_routes:`
con un solo elemento): es. "round_robin è abilitato ma è disponibile una sola route (serve
'secondary:' oppure 'primary_routes:' con almeno 2 elementi)".

Facoltativo ma consigliato per ridurre duplicazione: aggiungi a `JobRoutingConfig` una property
(es. `effective_routes: List[RouteConfig]`) che centralizza la logica "route effettive per
questo job" (`primary_routes` se presente, altrimenti `[primary, secondary]` filtrando i `None`)
— usala sia nel nuovo `select_initial_route` sia, se lo trovi pulito senza stravolgere quel
codice, nella costruzione di `configured_candidates` in `select_fallback_route` (righe 169-177),
che oggi duplica una logica simile a mano. Non toccare altro della cascata di fallback: è fuori
scope di questo task, limitati a deduplicare la lista se è un cambiamento a basso rischio.

### 3. Documentazione (`docs/CONFIGURATION_REFERENCE.md`)

La sezione "Round-Robin dual-key (`secondary:`)" (circa riga 137) descrive oggi SOLO il caso a 2
chiavi. Espandila per documentare il caso N-way con `primary_routes:`, con un esempio concreto a
3+ voci (es. 3 credenziali diverse per lo stesso provider), spiegando che:
- ogni voce della lista è una `RouteConfig` completa (stessi campi di `primary`/`secondary`);
- ogni voce dovrebbe avere una `credential` distinta (registrata in `general.yaml` sotto
  `credentials:` con un `env_var` diverso ciascuna) altrimenti il round-robin non ha senso
  (userebbe la stessa chiave API più volte);
- il conteggio round-robin è persistente per tutta la vita del processo `rt` (non per singola
  chiamata), quindi chiamate successive allo stesso job ciclano deterministicamente su tutte le
  route in ordine, non solo tra le prime due.

Esempio da aggiungere (adatta se hai generalizzato diversamente il codice sopra):
```yaml
round_robin: true
max_attempts: 5
primary_routes:
  - provider: "google"
    credential: "google_1"
    model: "gemini-3.5-flash-lite"
  - provider: "google"
    credential: "google_2"
    model: "gemini-3.5-flash-lite"
  - provider: "google"
    credential: "google_3"
    model: "gemini-3.5-flash-lite"
```

## Test

Estendi `tests/test_llm_router.py` con almeno:
- Un test con 5 `primary_routes` e `round_robin: true`: verifica che 12 chiamate successive a
  `select_initial_route` producano l'esatta sequenza ciclica attesa (route 1,2,3,4,5,1,2,3,4,5,1,2).
- Un test che verifica che `primary_routes` con un solo elemento e `round_robin: true` sollevi
  ancora `ValueError` (nessuna regressione sul caso limite).
- Se aggiungi la property `effective_routes`, un test unitario dedicato in
  `tests/test_llm_config.py` che verifica il valore restituito nei 3 casi: solo `primary`/
  `secondary` espliciti, solo `primary_routes`, ed entrambi presenti contemporaneamente
  (verifica quale ha precedenza — dovrebbe essere `primary_routes` per coerenza con
  `model_post_init` esistente).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa (598+ test
esistenti, non solo i nuovi).

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`): se aggiungi una nuova annotazione `List[...]`/`Optional[...]` in
un file, verifica che sia importata esplicitamente.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale rapido: scrivi un file `config/rt/outline.yaml` di prova con `round_robin: true`
   e 4 `primary_routes` fittizie (provider/model/credential diversi, va bene anche senza
   credenziali reali dato che stai solo testando la selezione, non l'esecuzione di una chiamata
   reale), poi in un piccolo script Python istanzia `RoutingEngine`/`LLMClient` e chiama
   `select_initial_route("outline")` 8 volte di fila, verificando a schermo che la sequenza dei
   `route_id` ciclata sia quella attesa (1,2,3,4,1,2,3,4).
