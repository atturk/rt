# Guida alla Configurazione (CONFIGURATION_REFERENCE.md)

I file YAML in `config.example/` costituiscono un **guscio vuoto out-of-the-box**: non assumono alcun provider o credenziale preimpostata nel codice. Questo documento spiega la struttura dei file, come dichiarare esplicitamente le credenziali e i modelli, e come configurare le route opzionali avanzate (dual-key round-robin, fallback mirati).

Per iniziare: copia l'intera cartella in `config/` e personalizza i file al suo interno — `config/` è ignorata da git per proteggere le tue impostazioni locali.
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
| `pricing_staleness_warning_days` | Giorni dopo i quali `rt run` avvisa che i prezzi configurati non sono stati riverificati con `rt prices-check` (`0` disattiva l'avviso). |

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

## 2. File per-job (`outline.yaml`, `rewrite.yaml`, `review_asr.yaml`, `review_science.yaml`)

Ogni file corrisponde a uno dei 4 job cognitivi. Nei file di template (`config.example/`), ciascun job ha solo il blocco `primary:` con `provider: null` e `model: null` (da compilare prima dell'uso), mentre i parametri di tuning ottimizzati sono preimpostati.

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
| `thinking` | Se `true`, richiede al modello l'uso del reasoning/thinking esteso. |
| `reasoning_effort` | Livello di sforzo del reasoning (es. `"low"`, `"high"`), quando supportato dal provider. |
| `max_thinking_tokens` | Limite di token dedicati al reasoning. |
| `max_tokens` | Limite di token sull'output totale (`null` = nessun limite esplicito). |
| `timeout_seconds` | Timeout di rete per la singola chiamata su questa route. |

### Route opzionali aggiuntive

#### 1. Round-Robin dual-key (`secondary:`)
Se si desidera distribuire il carico tra due account/chiavi (es. per il job `rewrite`):
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
- **`review_asr.yaml`**: `thinking: false`, `reasoning_effort: "low"`, `timeout_seconds: 300` (rilevamento errori fonetici su segmenti temporali brevi).
- **`review_science.yaml`**: `thinking: true`, `reasoning_effort: "high"`, `max_thinking_tokens: 16392`, `timeout_seconds: 300` (analisi di plausibilità concettuale e critica scientifica).

---

## 4. Verifica e applicazione dei prezzi (`rt prices-check`)

`rt prices-check` confronta i prezzi in uso (custom se dichiarati, altrimenti le stime hardcoded in `rt/llm/pricing.py`) con il catalogo live di LiteLLM, per ogni route effettivamente configurata (`provider`/`model` non `null`) in `config/`. Le route non ancora configurate vengono semplicemente omesse dal report, senza errori.

```bash
rt prices-check                # solo report a schermo, nessuna modifica
rt prices-check --interactive  # permette di scegliere quali prezzi live applicare
```

### Come funziona la selezione interattiva

`--interactive` apre una **checklist multi-selezione** (libreria `questionary`), una voce per ogni route con un modello trovato nel catalogo live:

```
? Seleziona i prezzi da applicare (SPAZIO per selezionare/deselezionare la voce
evidenziata, INVIO per confermare la selezione — le voci con ⚠ sono pre-selezionate,
spostare il cursore da solo NON seleziona nulla): (Use arrow keys to move, <space> to select, <a> to toggle, <i> to invert)
 » ○ [outline] openrouter/openai/gpt-5.6-luna  ...
   ○ [review_asr] openrouter/tencent/hy3  ...
   ● [rewrite] google/gemini-3.5-flash-lite  ⚠ DA VERIFICARE  ...
```

Punto importante, fonte comune di confusione: **il cursore (`»`) e la selezione (`●`/`○`) sono due cose indipendenti**, come in qualunque checkbox multi-selezione da terminale:
- Le **frecce** ↑/↓ spostano solo il cursore (dove sei "posizionato"), **non selezionano nulla**.
- La **barra spaziatrice** (o `a`) seleziona/deseleziona la voce su cui si trova il cursore in quel momento.
- Le voci marcate `⚠ DA VERIFICARE` (scarto di prezzo oltre il 15%) sono **pre-selezionate automaticamente** (`●`) fin dall'apertura del prompt — se vuoi applicare *solo* un'altra voce, devi prima deselezionare esplicitamente quelle pre-selezionate che non vuoi (cursore sopra + spazio) e selezionare quelle che vuoi, **prima** di premere Invio.
- **Invio** conferma l'insieme delle voci attualmente selezionate (marcate `●`) — non la voce su cui si trova il cursore.

Dopo Invio, prima di scrivere qualunque file viene mostrato un riepilogo esplicito di cosa sta per essere applicato e a quali job, con una conferma finale (`Confermi la scrittura? (y/N)`) — un'occasione per accorgersi ed annullare se la selezione non era quella voluta.

I prezzi selezionati vengono scritti nel campo `pricing:` della route esatta nel corrispondente `config/<job>.yaml`, preservando commenti e formattazione del file (round-trip `ruamel.yaml`). `rt.config.yaml` (deprecato) non viene mai toccato.
