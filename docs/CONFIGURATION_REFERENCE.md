# Guida alla Configurazione (CONFIGURATION_REFERENCE.md)

I file YAML in `config.example/` costituiscono un **guscio vuoto out-of-the-box**: non assumono alcun provider o credenziale preimpostata nel codice. Questo documento spiega la struttura dei file, come dichiarare esplicitamente le credenziali e i modelli, e come configurare le route opzionali avanzate (dual-key round-robin, fallback mirati).

> **💡 Configurazione Automatica**: È possibile generare e aggiornare la configurazione in modo interattivo eseguendo `./bin/rt config`. Il wizard ti guiderà nella scelta dei profili modello LLM per ciascuna fase della pipeline, API key, topic Telegram, motore STT e listino prezzi custom.
>
> **Libreria Profili Modello (`model_profiles:`)**: `config/general.yaml` può contenere una sezione `model_profiles:` con profili modello riutilizzabili salvati dal wizard `rt config`. Questa sezione è ad uso esclusivo del wizard per comodità di configurazione; `RTConfig` e il motore di routing ignorano completamente `model_profiles:`. L'effettivo comportamento a runtime di ciascun job resta determinato esclusivamente dai campi `primary:`, `primary_routes:` e `round_robin:` nei file `config/<job>.yaml`. Chi preferisce modificare i file a mano può continuare a farlo direttamente nei singoli file per-job ignorando `model_profiles:`.

Per iniziare manualmente: copia l'intera cartella in `config/` e personalizza i file al suo interno — `config/` è ignorata da git per proteggere le tue impostazioni locali.
```bash
cp -r config.example config
```

---

## 1. `general.yaml` — Impostazioni Globali e Credenziali

| Campo | Significato |
|---|---|
| `version` | Versione dello schema di configurazione. |
| `mock_llm` | Se `true`, esegue l'intera pipeline offline senza chiamate API, usando risposte mock deterministiche. |
| `streaming` | Abilita lo streaming SSE delle risposte (mostra l'emissione token in tempo reale). |
| `show_monitor` | Abilita il monitor interattivo con barra di avanzamento e metriche a terminale. |
| `retry.max_timeout_retries` | Numero massimo di retry bounded sulla stessa route in caso di timeout di rete. |
| `retry.timeout_backoff_seconds` | Attesa (in secondi) tra un retry e il successivo sulla stessa route. |
| `retry.idle_read_timeout_seconds` | Timeout di inattività applicativa: tempo massimo senza contenuto/reasoning reale prima di considerare la risposta bloccata. |
| `thresholds.green` | Soglia di confidence ASR (0-1) sopra la quale una correzione fonetica è considerata certa e viene auto-approvata nel ledger. |
| `thresholds.yellow` | Soglia sotto la quale un'ambiguità è plausibile e viene inserita nella coda di revisione umana. Sotto `yellow` (fascia "RED", non è un campo di configurazione ma una fascia implicita) il rischio è considerato elevato e richiede verifica d'ascolto umana obbligatoria. |
| `telegram.default_channel` | Canale di default per la pipeline (`"terminal"` o `"telegram"`). |
| `telegram.lessons_root` | Cartella radice assoluta contenente tutte le cartelle delle lezioni per l'enumerazione via bot Telegram. |
| `telegram.topics` | Mappa da materia in maiuscolo (es. `BIOCHIMICA`) a `message_thread_id` del topic Telegram dedicato nel gruppo. |
| `telegram.misc_topic_id` | `message_thread_id` del topic "Varie/Generale" per materie non presenti in `topics`. |

### Dichiarazione delle Credenziali (`credentials:`)

**Ogni provider, inclusi quelli nativi (`deepseek`, `openrouter`, `google`), richiede una dichiarazione esplicita sotto `credentials:` in `config/general.yaml`.** Non esiste alcuna scorciatoia o variabile d'ambiente assunta implicitamente nel codice:
- Impostare `provider: "openrouter"` in un job senza una voce `credentials:` corrispondente in `general.yaml` fallirà al momento dell'esecuzione reale indicando l'errore di autenticazione/variabile mancante.

#### Flusso di configurazione:
1. Apri `config/general.yaml` e dichiara le credenziali desiderate sotto `credentials:`.
2. Imposta le variabili d'ambiente indicate in `.env` (oppure esportale nell'ambiente shell).
3. Nei singoli file `config/<job>.yaml`, imposta `provider` e `model` sotto `primary:`.

#### Esempio base con OpenRouter (già presente come template in `config.example/general.yaml`):
```yaml
credentials:
  - name: "openrouter"
    provider: "openrouter"
    env_var: "OPENROUTER_API_KEY"
```

#### Regola per la credenziale di default:
Se dichiari **una sola** credenziale per un dato `provider`, essa diventa automaticamente la credenziale di default per quel provider: puoi quindi omettere il campo `credential:` nelle route dei file per-job.

Se invece dichiari **più credenziali** per lo stesso provider (es. due quote o progetti Google separati), devi specificare esplicitamente il campo `credential:` nelle route che le utilizzano:
```yaml
credentials:
  - name: "google_1"
    provider: "google"
    env_var: "GOOGLE_API_KEY_1"
  - name: "google_2"
    provider: "google"
    env_var: "GOOGLE_API_KEY_2"
```

#### Provider Generico OpenAI-compatible e modelli locali (es. Ollama, vLLM, Groq, Mistral):
Per un provider custom con autenticazione API key:
```yaml
credentials:
  - name: "mistral_official"
    provider: "openai_compatible"
    env_var: "MISTRAL_API_KEY"
```
Per un modello locale senza autenticazione (es. Ollama su `http://localhost:11434/v1`): puoi omettere del tutto la dichiarazione `credentials:` per esso e specificare semplicemente nel job `provider: "openai_compatible"` e `base_url: "http://localhost:11434/v1"`.

### Campo opzionale: `show_monitor_verbose`
Se aggiunto e impostato a `true`, mostra la vista estesa del monitor invece di quella compatta:
```yaml
show_monitor_verbose: false
```

### Funzionalità opzionale: listino prezzi custom globale
In alternativa al pricing per-route (vedi sezione 2), è possibile definire in `general.yaml` un listino custom globale per provider e modello, con priorità sulle stime hardcoded in `rt/llm/pricing.py`:
```yaml
pricing:
  deepseek:
    deepseek-v4-flash:
      input_per_million: 0.14
      output_per_million: 0.28
```

---

## 2. File per-job

Ogni file `<job>.yaml` corrisponde a uno dei job cognitivi della pipeline: il nome del file (senza estensione) è il nome del job, cercato **ricorsivamente** in tutta la cartella `config/` — la sottocartella in cui lo metti è a tua scelta, il codice non ne assume una struttura fissa. Nel template (`config.example/`) sono organizzati per chiarezza in due sottocartelle:
- `config.example/rt/`: i 3 job della pipeline principale (`outline`, `rewrite`, `review`).
- `config.example/telegram/`: i job legati all'active recall via Telegram (`recall_quiz`, `recall_mirata`, `recall_vasta`, `recall_eval_mirata`, `recall_eval_vasta`).

Nei file di template, ciascun job ha solo il blocco `primary:` con `provider: null` e `model: null` (da compilare prima dell'uso), mentre i parametri di tuning ottimizzati sono preimpostati.

### File di config non-job: `config/telegram/recall_lessons.yaml`

Non tutti i file `.yaml` sotto `config/` sono job LLM: `recall_lessons.yaml` (se presente, sempre nella sottocartella `telegram/`) è un'eccezione esplicitamente esclusa dalla ricerca ricorsiva dei job (vedi `rt.core.config.find_job_yaml_paths`) e serve a un altro scopo — dire a `/recall` lanciato da Telegram **quale cartella usare per ciascuna materia**, al posto del comportamento automatico di default.

Per default, `/recall` da Telegram usa l'ultima lezione con build completata in quel topic (tracciata automaticamente da `notify_build_completed`, nessuna configurazione richiesta) — se non hai mai fatto una build in un topic, `/recall` non trova nulla e te lo dice, non è un browser/indice di lezioni. `recall_lessons.yaml` è per chi vuole fissare esplicitamente la cartella indipendentemente dall'ultima build:

```yaml
# config/telegram/recall_lessons.yaml
BIOCHIMICA: "/percorso/assoluto/[2026-09-05] BIOCHIMICA - trigliceridi"
```

La chiave è la stessa materia usata in `topics:` dentro `general.yaml`. Facoltativo per materia: quelle non elencate continuano a usare il comportamento automatico.

### Campi comuni di livello superiore
| Campo | Significato |
|---|---|
| `round_robin` | Se `true`, alterna le chiamate tra `primary` e `secondary` (richiede obbligatoriamente la definizione della route `secondary:`). |
| `max_attempts` | Numero massimo di tentativi complessivi per il job, attraverso l'intera catena primary → fallback. |
| `max_output_chars` | Limite di caratteri sull'output atteso dal modello per questo job. |

### Campi di una route (`primary`, `secondary`, e ogni voce di `fallback`)
| Campo | Significato |
|---|---|
| `provider` | Provider LLM: `openrouter`, `deepseek`, `google`, oppure `openai_compatible`. |
| `credential` | Nome simbolico della credenziale dichiarata in `general.yaml` (opzionale se esiste un solo default per il provider). |
| `model` | Nome del modello presso il provider. |
| `base_url` | URL dell'endpoint API (richiesto obbligatoriamente per `openai_compatible`). |
| `thinking` | `true` forza il reasoning acceso; `false` tenta di disattivarlo (su OpenRouter omette il campo per sicurezza); `null`/omesso lascia decidere al provider/modello nativo. |
| `reasoning_effort` | Livello di sforzo del reasoning (es. `"low"`, `"medium"`, `"high"`, oppure `null`/omesso per lasciare la decisione al modello/provider). |
| `max_thinking_tokens` | Limite di token dedicati al reasoning. |
| `max_tokens` | Limite di token sull'output totale (`null` = nessun limite esplicito). |
| `timeout_seconds` | Timeout di rete per la singola chiamata su questa route. |
| `pricing` | Override opzionale del pricing (`input_per_million`, `output_per_million`) per questa route specifica. |
| `provider_routing` | Oggetto `provider` di OpenRouter (`only`, `quantizations`, `sort`, `allow_fallbacks`, ...) per questa route (pass-through non validato, vedi Sezione 4). |

### Route opzionali aggiuntive

#### 1. Round-Robin N-way (`secondary:` oppure `primary_routes:`)
Se si desidera distribuire il carico tra più account/chiavi (es. per il job `rewrite`), è possibile usare `secondary:` per 2 chiavi oppure `primary_routes:` per un numero N arbitrario di chiavi (es. 3+):

- ogni voce della lista è una `RouteConfig` completa (stessi campi di `primary`/`secondary`);
- ogni voce dovrebbe avere una `credential` distinta (registrata in `general.yaml` sotto `credentials:` con un `env_var` diverso ciascuna) altrimenti il round-robin non ha senso (userebbe la stessa chiave API più volte);
- il conteggio round-robin è persistente per tutta la vita del processo `rt` (non per singola chiamata), quindi chiamate successive allo stesso job ciclano deterministicamente su tutte le route in ordine, non solo tra le prime due.

Esempio con 2 chiavi (`primary:` / `secondary:`):
```yaml
round_robin: true
max_attempts: 5
max_output_chars: 45000

primary:
  provider: "google"
  credential: "google_1"
  model: "gemini-3.5-flash-lite"
  thinking: true
  reasoning_effort: "high"
  timeout_seconds: 180

secondary:
  provider: "google"
  credential: "google_2"
  model: "gemini-3.5-flash-lite"
  thinking: true
  reasoning_effort: "high"
  timeout_seconds: 180
```

Esempio con 3+ chiavi (`primary_routes:`):
```yaml
round_robin: true
max_attempts: 5
max_output_chars: 45000

primary_routes:
  - provider: "google"
    credential: "google_1"
    model: "gemini-3.5-flash-lite"
    thinking: true
    reasoning_effort: "high"
    timeout_seconds: 180
  - provider: "google"
    credential: "google_2"
    model: "gemini-3.5-flash-lite"
    thinking: true
    reasoning_effort: "high"
    timeout_seconds: 180
  - provider: "google"
    credential: "google_3"
    model: "gemini-3.5-flash-lite"
    thinking: true
    reasoning_effort: "high"
    timeout_seconds: 180
```

#### 2. Mappa di `fallback` mirata
È possibile aggiungere un blocco `fallback:` per gestire classi specifiche di errore:
```yaml
fallback:
  timeout:
    provider: "deepseek"
    model: "deepseek-v4-flash"
    thinking: true
    reasoning_effort: "low"
    timeout_seconds: 240
  rate_limit:
    provider: "openrouter"
    model: "deepseek/deepseek-v4-flash"
    thinking: true
    reasoning_effort: "low"
    timeout_seconds: 240
  safety:
    provider: "openrouter"
    model: "deepseek/deepseek-v4-flash"
    thinking: true
    reasoning_effort: "high"
    timeout_seconds: 300
  auth:
    provider: "google"
    credential: "google_2"
    model: "gemini-3.5-flash-lite"
    timeout_seconds: 180
  generic:
    provider: "deepseek"
    model: "deepseek-v4-flash"
    timeout_seconds: 240
```

Le 5 chiavi di fallback e il loro trigger:
- `timeout`: scatta quando la route primaria va in timeout oltre i retry bounded.
- `rate_limit`: errore di rate limit o quota esaurita.
- `safety`: blocco da parte dei filtri di sicurezza/contenuto del provider (utile instradare su un provider differente).
- `auth`: credenziale non valida o fallimento di autenticazione.
- `generic`: qualsiasi altro errore di rete o runtime non classificato.

### Funzionalità opzionale: pricing custom per-route
Puoi sovrascrivere il prezzo per una singola route con massima priorità:
```yaml
primary:
  provider: "google"
  model: "gemini-3.5-flash-lite"
  # ... altri campi ...
  pricing:
    input_per_million: 0.0
    output_per_million: 0.0
```

---

## 3. Note sui tuning preimpostati per i job

I template out-of-the-box in `config.example/` mantengono i parametri di tuning ideali testati per ciascun job:
- **`outline.yaml`**: `thinking: true`, `reasoning_effort: "low"`, `timeout_seconds: 300`.
- **`rewrite.yaml`**: `thinking: true`, `reasoning_effort: "high"`, `timeout_seconds: 180`.
- **`review.yaml`**: `thinking: true`, `reasoning_effort: "high"`, `max_thinking_tokens: 16392`, `timeout_seconds: 300` (analisi di plausibilità concettuale e critica scientifica).
- **`image_description.yaml`**: `thinking: true`, `reasoning_effort: "low"`, `max_tokens: 2048`, `timeout_seconds: 120` (descrizione vision strutturata di slide/foto/immagini web). Nota: il job `image_description` richiede un provider/modello con capacità vision (es. `google` con Gemini, `openrouter` con modelli multimodali, oppure `openai_compatible` con endpoint vision). I provider puramente testuali come `deepseek` non supportano input visivo.

---

## 4. Routing dei backend OpenRouter (`provider_routing:`)

OpenRouter espone nel payload della richiesta un oggetto [`provider: { ... }`](https://openrouter.ai/docs/guides/routing/provider-selection) che consente di controllare a quali backend/hoster viene instradata la chiamata: `only`/`ignore` (whitelist/blacklist per slug provider), `quantizations` (filtro qualità quantizzazione, es. `["fp8", "bf16", "fp16"]`), `sort` (`"price"` | `"throughput"` | `"latency"`), `allow_fallbacks`, `require_parameters`, `max_price`, `data_collection`, `zdr`.

### Perché è solo per-route e non esiste un default globale

Quali provider siano affidabili (in termini di token per secondo, stabilità e quantizzazione) **dipende dal modello specifico**: un hoster eccellente per servire `deepseek/deepseek-v4-flash` potrebbe non servire affatto o servire male `z-ai/glm-5.3`.

Per questa ragione **non esiste alcun default globale** e il campo non va mai inserito in `general.yaml`: va configurato **esclusivamente per singola route** tramite il campo `provider_routing:` all'interno del file del job (`config/<job>.yaml`), accanto a `provider: "openrouter"` e `model:`. Il campo è un **pass-through non validato** inoltrato direttamente a OpenRouter (ed è ignorato per provider diversi da `openrouter`).

### Esempi di configurazione

#### Singola route primaria con whitelist, filtro quantizzazioni e sort throughput
```yaml
primary:
  provider: "openrouter"
  model: "deepseek/deepseek-v4-flash"
  thinking: true
  reasoning_effort: "low"
  timeout_seconds: 240
  provider_routing:
    only: ["nome-provider-buono-per-deepseek-1", "nome-provider-buono-per-deepseek-2"]
    quantizations: ["fp8", "bf16", "fp16"]
    sort: "throughput"
    allow_fallbacks: true
```

#### Whitelist differenziata per modelli diversi nello stesso job
```yaml
primary:
  provider: "openrouter"
  model: "deepseek/deepseek-v4-flash"
  provider_routing:
    only: ["nome-provider-buono-per-deepseek-1", "nome-provider-buono-per-deepseek-2"]
    quantizations: ["fp8", "bf16", "fp16"]
    sort: "throughput"

fallback:
  generic:
    provider: "openrouter"
    model: "z-ai/glm-5.3"
    provider_routing:
      only: ["nome-provider-buono-per-glm-1"]
      sort: "throughput"
```

### Note e buone pratiche

1. **Tradeoff della whitelist (`only`)**: se nessun provider presente nella whitelist `only` è disponibile o online in quel momento per il modello richiesto, la richiesta fallirà con errore HTTP di OpenRouter anziché degradare silenziosamente su provider non desiderati. Questo garantisce che non vengano utilizzate quantizzazioni scadenti o backend lenti, ma richiede di scegliere provider affidabili o abilitare `allow_fallbacks: true` se consentito.
2. **Criterio di ordinamento (`sort`)**: OpenRouter supporta **un solo criterio alla volta** (`"price"` | `"throughput"` | `"latency"`), senza concatenazione. L'effetto di selezionare "il più veloce tra i provider affidabili ad alta qualità" si ottiene combinando i filtri `only` / `quantizations` con l'ordinamento `sort: "throughput"`.
3. **Come trovare gli slug dei provider**: sulla pagina del singolo modello su [openrouter.ai](https://openrouter.ai/models) (es. `openrouter.ai/<vendor>/<modello>`), è presente la lista dei provider attivi con l'apposito pulsante per copiare lo slug esatto (es. `deepinfra`, `together`, `hyperbolic`, ecc.). Poiché la copertura varia da modello a modello, la lista va verificata specificamente per ciascun modello configurato.

