# Task 63 — Il fallback deve esaurire il pool round-robin prima di scattare, tornare subito al round-robin dopo un uso, cooldown solo al secondo fallback consecutivo

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa
direttamente, senza produrre un piano preliminare.

## Contesto

Oggi, in `rt/llm/router.py::RoutingEngine.select_fallback_route` (righe 104-221), un SINGOLO
errore di rate limit (429) su una qualunque chiave del pool round-robin (`job_cfg.primary_routes`,
esposto da `job_cfg.effective_routes`) scatta SUBITO la route dedicata `fallback.rate_limit` (o
`fallback.generic` se non configurata) — vedi il ramo `elif isinstance(failure, RateLimitFailure)`
a riga 134-137. Solo se QUELLA route di fallback risulta già visitata/non disponibile, il codice
scende al punto 3a (riga 168-190) e prova altre `effective_routes` non ancora visitate — quindi il
pool round-robin viene usato come ripiego del ripiego, non come prima linea.

`visited_route_ids` (passato da `rt/llm/client.py`, righe 247 e 300) vive per la durata di una
SINGOLA catena di chiamata (un'unità di lavoro), non fra chiamate diverse: non è adatto da solo a
tracciare "quanti fallback consecutivi sono scattati fra unità diverse", serve stato che sopravviva
oltre la singola chiamata a `select_fallback_route`.

`RoutingEngine` viene istanziato una volta sola per `LLMClient` (riga 73 di `client.py`,
`self.router = RoutingEngine(self.config)`) — verifica se `LLMClient` stesso è longevo per l'intera
pipeline o ricreato per unità/lezione: se è longevo, `RoutingEngine` è il posto naturale dove far
vivere lo stato persistente richiesto qui; se viene ricreato spesso, valuta se serve spostare lo
stato in un oggetto ancora più esterno (es. un modulo-level singleton o uno stato passato
esplicitamente) — verifica il ciclo di vita reale prima di scegliere dove mettere lo stato,
descrivilo nel riepilogo finale.

## Comportamento richiesto (confermato con l'utente)

Per un fallimento di tipo rate-limit (e, per coerenza, per le altre classi di errore che oggi hanno
un mapping analogo — timeout/generic; **non** toccare la logica speciale già esistente per
safety/auth ai punti 3a, che esclude deliberatamente route dello stesso provider/della stessa
credenziale: quella resta invariata) su un job con `round_robin=True`:

1. **Esaurisci prima il pool round-robin**: se esistono ancora route in `job_cfg.effective_routes`
   non presenti in `visited_route_ids` (e non escluse dalle regole speciali safety/auth già
   esistenti), scegli la prossima di queste PRIMA di considerare `fallback.rate_limit`/
   `fallback.generic` — indipendentemente dal fatto che la route di fallback dedicata sia libera o
   meno.
2. **Solo quando il pool è esaurito** (tutte le `effective_routes` sono in `visited_route_ids`),
   scatta la route di fallback dedicata (`fallback.rate_limit` o `fallback.generic`), esattamente
   come già mappato oggi.
3. **Dopo un uso del fallback, si torna subito al round-robin**: la scelta di fallback per
   QUESTA catena non deve "restare sticky" per le chiamate successive — la prossima unità/job deve
   ripartire dal round-robin normale (`select_initial_route`, comportamento già corretto e da NON
   toccare).
4. **Cooldown solo al secondo fallback CONSECUTIVO**: mantieni un contatore persistente (nello
   stato scelto al punto sopra) di quante catene DI FILA hanno dovuto ricorrere al fallback (reset
   a 0 non appena una catena si conclude con successo SENZA aver avuto bisogno del fallback,
   cioè un'unità risolta interamente dal pool round-robin). Quando il contatore raggiunge 2
   (secondo fallback consecutivo), attiva un cooldown configurabile (default 30 secondi): mentre il
   cooldown è attivo, se il pool round-robin si esaurisce di nuovo per una nuova catena, NON
   scatta il fallback (la catena termina in fallimento come se il fallback non fosse configurato,
   lasciando che la gestione errori/retry esistente a monte se ne occupi) — non bloccare/attendere
   il cooldown con uno `sleep`, deve essere un rifiuto immediato di usare il fallback finché il
   cooldown non è scaduto. Il cooldown si applica al job (`job_name`), non globalmente a tutti i
   job.

## Modifica

- Aggiungi un campo `cooldown_seconds: int = 30` a `JobFallbackConfig` (`rt/core/config.py`,
  righe 131-137) per rendere il cooldown configurabile per job (default 30, coerente con la
  richiesta).
- In `RoutingEngine.__init__` (riga 57-60), aggiungi lo stato necessario per tracciare, per
  `job_name`: il contatore di fallback consecutivi e il timestamp dell'ultima escalation a
  fallback (per calcolare se il cooldown è scaduto). Proteggi l'accesso con `self._lock` (già
  esistente), coerente col resto della classe.
- Riscrivi `select_fallback_route` (o estrai una funzione helper dedicata, se risulta più chiaro)
  per implementare i 4 punti sopra. Mantieni intatta la logica esistente di loop protection e le
  esclusioni speciali safety/auth (punti 3 del codice attuale) — si applicano comunque quando si
  sceglie la prossima route del pool round-robin, non solo per la route di fallback dedicata.
- Aggiungi un metodo (o un modo) per segnalare a `RoutingEngine` che una catena si è conclusa con
  successo SENZA fallback, per resettare il contatore consecutivo — verifica il punto esatto in
  `rt/llm/client.py` dove una catena termina con successo (sia nel percorso a riga ~243-330 sia in
  quello a riga ~1052+, sembrano esistere due punti di chiamata quasi identici: verifica se sono
  davvero duplicati o gestiscono casi diversi, es. structured vs streaming, e aggiorna entrambi in
  modo coerente).

## Test

Aggiungi in `tests/test_llm_router.py` (segui lo stile degli scenari esistenti, es.
`test_scenario_b_rate_limit_google1_to_openrouter` a riga 291, che resta valido invariato: usa un
solo elemento in `primary_routes`, quindi il pool è già "esaurito" al primo fallimento — nessuna
regressione attesa lì):

- Test con un pool round-robin di almeno 3 route: il primo 429 su una chiave NON deve produrre una
  telemetria con `fallback_to_provider` verso la route di fallback dedicata, ma un tentativo sulla
  prossima route del pool; solo quando TUTTE le route del pool hanno fallito con 429 la catena deve
  arrivare al fallback dedicato.
- Test che verifica che, dopo che una catena ha usato il fallback con successo, la catena
  SUCCESSIVA (nuova chiamata a `select_initial_route`) riparta dal round-robin normale (non
  continua a usare la route di fallback).
- Test che verifica l'attivazione del cooldown al SECONDO fallback consecutivo: due catene di fila
  esauriscono il pool e vanno in fallback -> la terza catena, se il pool si esaurisce di nuovo
  entro il cooldown, deve fallire (nessuna route disponibile) invece di riusare il fallback.
- Test che verifica che il contatore si resetti a 0 se una catena intermedia si risolve con
  successo tramite il round-robin (senza toccare il fallback) — il fallback successivo NON deve
  quindi essere considerato "secondo consecutivo" e deve poter scattare di nuovo senza cooldown.
- Test che verifica che il cooldown sia per-job: un job diverso non ne risente.
- Test che verifica che, passato il tempo di cooldown configurato (mocka il clock/tempo usato,
  verifica come il resto del codice gestisce il tempo — `time.time()`/`time.monotonic()`, sii
  coerente con eventuali convenzioni già in uso nel progetto), il fallback torni disponibile.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare `select_initial_route` né la logica di loop protection/esclusioni safety-auth già
corretta — questo task riguarda solo QUANDO scatta il fallback rispetto al pool round-robin, non
come si sceglie la route iniziale né le regole di sicurezza già esistenti.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Rileggi la sezione "Comportamento richiesto" sopra e verifica riga per riga che il codice finale
   implementi esattamente i 4 punti, non un'approssimazione.
