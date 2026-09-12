# Task 26 — `rt config`: libreria di profili modello riutilizzabili (fondamenta)

Dipende dallo stato attuale di `rt/pipeline/configure.py` (task 20-22, 25 già completati) —
leggi quel file per intero prima di procedere, questo task lo **refactora**, non lo riscrive da
zero. Il Task 27 (selezione del modello per singola fase) dipende da questo: completalo per
primo. Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza
produrre un piano preliminare.

## Contesto

L'utente usa DAVVERO modelli diversi per fasi diverse della pipeline (esempio reale datomi in
chat): un modello "intelligente" via OpenRouter per `outline`, `gemini-3.5-flash-lite` in
round-robin pesante su molte chiavi Google per `rewrite`, un modello forte (o un altro
round-robin pesante) per `review_science`, GLM per i job di recall, un modello vision leggero
per le immagini. Il wizard `rt config` oggi (`_configure_llm_provider_section`) chiede UN solo
provider/modello e lo applica identico a TUTTI gli 11 job — il contrario di quello che serve.
**L'architettura sotto (RTConfig/RoutingEngine/YAML per-job) supporta già pienamente modelli
diversi per job** (verificato: ogni `config/<job>.yaml` è già indipendente) — il problema è
solo nella UX del wizard.

Decisione presa in chat: introdurre una **libreria di "profili modello" riutilizzabili**. Un
profilo è un bundle nominato (provider + base_url + una o più credenziali/route, eventualmente
round-robin) che il wizard propone di riusare tra una fase e l'altra, invece di richiedere da
capo lo stesso provider per ogni job. Il primo profilo configurato si chiama per default
`"generale"`. Questo task (26) prepara le fondamenta (libreria profili + funzione di creazione/
applicazione) mantenendo per ora il comportamento finale invariato (il profilo creato viene
applicato a tutti i job, come oggi) — la vera selezione per-fase arriva nel Task 27, che dipende
da questo.

## Dati: nuova sezione `model_profiles:` in `config/general.yaml`

Pura contabilità del wizard — **NON tocca `RTConfig`/`RoutingEngine`**: verificato che
`RTConfig` non ha `model_config = ConfigDict(extra=...)`, quindi Pydantic v2 di default ignora
silenziosamente chiavi sconosciute nello YAML (`extra="ignore"`). Ciò che conta davvero per
l'esecuzione resta, come oggi, `primary:`/`primary_routes:`/`round_robin:` in ciascun
`config/<job>.yaml` — `model_profiles:` è solo memoria del wizard per riproporre le stesse
scelte in futuro, non serve validarla con Pydantic.

Struttura:
```yaml
model_profiles:
  generale:
    provider: "openrouter"
    base_url: null
    round_robin: false
    routes:
      - credential: "openrouter_1"
        model: "openai/gpt-5.6-luna"
  rewrite_rr_gemini:
    provider: "google"
    base_url: null
    round_robin: true
    routes:
      - credential: "google_1"
        model: "gemini-3.5-flash-lite"
      - credential: "google_2"
        model: "gemini-3.5-flash-lite"
```
(oggi tutte le route di un profilo condividono lo stesso `model`, coerentemente con la
semplificazione già presa nel Task 25 — mantieni comunque `model` per-route nella struttura dati
per non precludere flessibilità futura, non serve però esporla nella UI di oggi).

## Refactoring di `rt/pipeline/configure.py`

Estrai dalla `_configure_llm_provider_section` attuale (che oggi fa tutto in una funzione unica:
selezione provider, base_url, singola chiave o round-robin multi-chiave, recupero modelli,
scrittura su tutti i job) le seguenti funzioni riutilizzabili:

### 1. `_load_model_profiles(general_data: dict) -> Dict[str, Dict[str, Any]]`
Legge `general_data.get("model_profiles", {})`, normalizza (ignora voci malformate invece di
sollevare eccezioni).

### 2. `_save_model_profiles(general_data: dict, profiles: Dict[str, Dict[str, Any]]) -> None`
Scrive `general_data["model_profiles"] = profiles` (il chiamante persiste su disco con
`_atomic_write_text`+`yaml.safe_dump`, stesso pattern già usato ovunque nel file).

### 3. `_suggest_profile_name(provider: str, model: str, existing_names: Iterable[str]) -> str`
Suggerisce un nome leggibile (es. `f"{provider}_{model}"` sanitizzato: minuscolo, spazi/slash
sostituiti con `_`), con un suffisso numerico se già esistente (`_2`, `_3`, ...) per garantire
unicità come DEFAULT proposto — l'utente potrà comunque sovrascriverlo con un nome libero.

### 4. `_create_new_model_profile(config_dir: str, env_path: str, general_data: dict, default_name_hint: Optional[str] = None) -> Tuple[str, Dict[str, Any]]`
Contiene **esattamente** la logica oggi in `_configure_llm_provider_section` per: selezione
provider (`questionary.select` tra `deepseek`/`openrouter`/`google`/`openai_compatible`), base_url
(con i default noti da `KNOWN_PROVIDER_DEFAULT_BASE_URLS`), scelta singola-chiave vs round-robin
multi-chiave con raccolta N chiavi (logica già scritta nel Task 25 — spostala qui as-is, non
riscriverla), registrazione credenziali in `.env`/`general_data["credentials"]`, recupero
automatico della lista modelli via `GET {base_url}/models` con fallback a inserimento manuale.

**Novità rispetto a oggi**: dopo aver scelto il modello, invoca `_configure_pricing_section(config_dir, provider, chosen_model)` (funzione già esistente, non modificarne la firma) come step
opzionale INLINE per QUESTO profilo (skippabile, default no, esattamente come oggi si comporta a
fine wizard) — il pricing va configurato quando si crea il modello, non più come unico step
globale a fine wizard (vedi sotto, quella chiamata separata va rimossa).

Infine chiedi il nome del profilo: `questionary.text("Nome per questo profilo modello (per
riusarlo in altre fasi):", default=_suggest_profile_name(provider, chosen_model, existing profile
names))`. Se il nome coincide con uno già esistente, avvisa e chiedi conferma prima di
sovrascriverlo (non sovrascrivere silenziosamente un profilo esistente con lo stesso nome).

Ritorna `(profile_name, profile_dict)` dove `profile_dict` ha la forma descritta sopra
(`provider`, `base_url`, `round_robin`, `routes: [{"credential":..., "model":...}, ...]`).
Non scrive ancora nulla nei file `<job>.yaml` — se ne occupa la funzione successiva.

### 5. `_apply_profile_to_job(job_file: str, profile: Dict[str, Any]) -> None`
Contiene la logica oggi in `_configure_llm_provider_section` (sezione "6. Aggiornamento di tutti
i file `<job>.yaml`") che: legge lo YAML esistente del job, preserva i campi di tuning non-
provider/model/credential/base_url (`thinking`, `reasoning_effort`, `max_thinking_tokens`,
`max_tokens`, `timeout_seconds`, `provider_routing`) dal blocco `primary`/`primary_routes[0]`
esistente, e scrive `round_robin`/`primary`/`primary_routes` in base al `profile` passato
(stessa logica esatta già scritta per il caso round-robin nel Task 25, generalizzata per operare
su UN profilo qualsiasi passato come parametro invece che sulle variabili locali della vecchia
funzione monolitica).

## Comportamento di `_configure_llm_provider_section` DOPO il refactoring (Task 26)

Nuova firma: `_configure_llm_provider_section(config_dir: str, env_path: str) -> Dict[str, str]`
(prima ritornava `Tuple[Optional[str], Optional[str], List[str]]` — **cambio di contratto
intenzionale**, aggiorna il chiamante e tutti i test, vedi sotto).

Comportamento per QUESTO task (il Task 27 sostituirà la parte finale con la vera selezione per
fase — per ora mantieni il comportamento "un profilo per tutti i job", ma usando le nuove
funzioni):
1. Carica `model_profiles` esistenti (rerun) con `_load_model_profiles`.
2. Se non ce ne sono ancora: crea il primo con `_create_new_model_profile(..., default_name_hint="generale")`, aggiungilo alla libreria.
3. Se ce ne sono già (rerun): usa il primo/il profilo chiamato `"generale"` se esiste, altrimenti il primo della lista (comportamento provvisorio, sostituito dal Task 27).
4. Applica quel profilo a TUTTI i job trovati da `find_job_yaml_paths` con `_apply_profile_to_job`.
5. Persisti `model_profiles` in `general.yaml` con `_save_model_profiles` + scrittura atomica.
6. Ritorna `{job_name: profile_name for job_name in updated_jobs}`.

## Aggiornamento di `run_config_wizard()`

- Cambia `provider, model, updated_jobs = _configure_llm_provider_section(...)` in
  `job_profiles = _configure_llm_provider_section(...)`.
- **Rimuovi** la chiamata separata `pricing_res = _configure_pricing_section(config_dir, provider, model)` a fine wizard — il pricing ora si configura inline per ciascun profilo appena
  creato (vedi sopra). La funzione `_configure_pricing_section` resta definita e usata
  internamente da `_create_new_model_profile`, semplicemente non viene più chiamata da
  `run_config_wizard()` direttamente.
- Aggiorna il riepilogo finale stampato: sostituisci la riga "Provider LLM: X/Y (applicato a N
  job)" + la riga "Pricing custom" con un elenco per-job, es.:
  ```
  Modelli assegnati:
  - outline: generale
  - rewrite: generale
  ... (uguali per tutti in questo task, il Task 27 li differenzierà)
  ```
  (in questo task saranno tutti uguali dato che il comportamento "un profilo per tutti" è ancora
  invariato — è il Task 27 che introduce la vera differenziazione per fase).

## Test

`tests/test_configure_wizard.py` ha test esistenti (task 20, 25) che assumono: (a) la vecchia
firma a 3 valori di ritorno, (b) che UN SOLO provider/modello venga applicato a tutti i job. **Non
è una regressione da preservare, è il refactoring voluto** — riscrivi quei test per riflettere il
nuovo contratto invece di provare a mantenerne l'assert letterale. In particolare:
- `test_configure_llm_provider_section_success_http_models`,
  `test_configure_llm_provider_section_http_failure_fallback_manual`,
  `test_configure_llm_provider_section_multi_key_round_robin`,
  `test_configure_llm_provider_section_multi_key_append_rerun`,
  `test_configure_llm_provider_section_multi_key_single_key_fallback` vanno adattati al nuovo
  ritorno (`Dict[str, str]`) e, se testano ancora scenari validi (creazione profilo con recupero
  modelli via HTTP, fallback manuale, round-robin multi-chiave, fallback a chiave singola),
  aggiornali per verificare lo stesso comportamento ma attraverso le nuove funzioni estratte
  (`_create_new_model_profile`, `_apply_profile_to_job`) invece che tramite l'intera
  `_configure_llm_provider_section` se questo rende il test più mirato e semplice da mantenere —
  a tua discrezione, l'importante è che la stessa copertura funzionale non vada persa.
- Aggiungi test dedicati per `_suggest_profile_name` (unicità, sanitizzazione) e per
  `_load_model_profiles`/`_save_model_profiles` (round-trip, merge con profili preesistenti non
  toccati in questa sessione).
- Aggiungi un test per `_configure_llm_provider_section` di alto livello che verifichi: primo
  avvio senza profili → ne crea uno chiamato "generale" e lo applica a tutti i job; rerun con un
  profilo "generale" già esistente → lo riusa senza richiedere di nuovo provider/API key da zero.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa (non solo i nuovi
test — molti test esistenti richiederanno modifiche per il cambio di contratto, è atteso).

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale in una copia temporanea del repo senza `config/`: esegui `./bin/rt config`,
   configura il profilo "generale" con valori di prova, verifica che `config/general.yaml`
   contenga `model_profiles: {generale: {...}}` e che tutti i file `config/rt/*.yaml`/
   `config/telegram/*.yaml` abbiano `primary`/`primary_routes` coerenti con quel profilo.
   Riesegui `./bin/rt config` una seconda volta e verifica che il profilo "generale" venga
   riusato senza richiedere di nuovo API key/modello da zero. Pulisci la cartella temporanea
   alla fine.
