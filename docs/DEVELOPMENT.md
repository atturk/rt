# Guida allo Sviluppo e Manutenzione (DEVELOPMENT.md)

Questo documento guida sviluppatori e maintainer all'estensione del sistema RT, all'esecuzione dei test e all'aggiunta di nuovi reviewer o provider LLM.

---

## 1. Setup dell'Ambiente Locale

Il progetto richiede Python 3.10+ ed è progettato per operare sia con le librerie standard sia con `pydantic` (v2):

```bash
# Esecuzione della CLI direttamente dal repository
./bin/rt --help
# Oppure tramite modulo Python
python3 -m rt.cli --help
```

---

## 2. Esecuzione della Test Suite

La suite di test è collocata nella cartella `tests/` ed è suddivisa per moduli:

- `test_timestamp.py`: conversioni tra stringhe timecode e float seconds, parsing intervalli.
- `test_segments.py`: parser per JSON MacWhisper e Markdown grezzo, calcolo durate, validazione.
- `test_validation.py`: controlli di ordinamento, coerenza e calcolo della copertura didattica dell'outline.
- `test_renderer.py`: **test vincolo timestamp** (verifica che il timestamp derivi dal segmento e fallisca se manomesso).
- `test_science.py`: classificazione nei 4 scenari scientifici (`ERR_DOCENTE`, `ERR_RECONSTRUCTION`, `SCIENCE_CHECK`).
- `test_ledger.py`: funzionamento del decision ledger e applicazione atomica idempotente delle decisioni.
- `test_idempotency.py`: **test suite di idempotenza ed economia token** (verifica chiamate LLM = 0 e delta costo = 0 al rerun, rielaborazione forzata con `--force`, rerun parziale `--unit`, recupero da corruzione `INVALID`, crash safety atomica e diagnostica `rt status`).
- `test_integration.py`: esecuzione end-to-end completa su fixture sintetica.
- `test_regression_biochem.py`: test di regressione sui 499 segmenti della lezione reale di biochimica.

Per eseguire l'intera suite:
```bash
python3 -m pytest tests/ -v
```

---

## 3. Configurazione Provider LLM e Micro Smoke Test

RT supporta sia **DeepSeek direct** sia **OpenRouter** tramite provider adapter dedicati in `rt/llm/providers/`.

### Configurazione in `rt.config.yaml`:
```yaml
llm:
  outline:
    provider: "deepseek"               # oppure "openrouter"
    model: "deepseek-v4-flash"        # oppure "deepseek/deepseek-v4-pro"
    thinking: true
    reasoning_effort: "low"
    max_tokens: 16384
```

### Variabili d'Ambiente:
- Per DeepSeek: `export DEEPSEEK_API_KEY="sk-..."`
- Per OpenRouter: `export OPENROUTER_API_KEY="sk-or-..."`
(oppure inserite in `.env` locale non versionato).

### Esecuzione Micro Smoke Test:
Un comando leggero per validare connettività, streaming e telemetria con una singola richiesta minima (`{"ok": true}`):
```bash
# Smoke test verso DeepSeek (default)
./bin/rt test-llm --provider deepseek

# Smoke test verso OpenRouter
./bin/rt test-llm --provider openrouter --model deepseek/deepseek-chat

# Esecuzione senza streaming
./bin/rt test-llm --provider deepseek --no-stream
```

### Aggiungere un Nuovo Provider:
1. Crea un adapter in `rt/llm/providers/<nome>.py` estendendo `BaseLLMProvider`.
2. Registralo nel dizionario `_PROVIDERS` in `rt/llm/providers/__init__.py`.
3. Assicurati che le credenziali provengano da `get_api_key(provider)` in `rt/core/config.py`.
4. Aggiungi il listino di riferimento in `rt/llm/pricing.py`.

---

## 4. Aggiungere un Nuovo Reviewer Specialistico

Per aggiungere un controllo specialistico (es. controllo formule chimiche o dosaggi farmacologici):

1. Definisci il modello dati dell'issue in `rt/core/models.py`.
2. Crea il prompt dedicato in `rt/llm/prompts.py`.
3. Implementa lo step in `rt/pipeline/review_<nome>.py`.
4. Integra il comando corrispondente in `rt/cli.py` (`rt review-<nome>`).
5. Aggiungi il rendering dell'output in `rt/pipeline/build.py`.

---

## 5. Rollback e Ripristino Stato

Se una fase fallisce o si desidera rieseguire un passaggio:
1. Lo stato può essere ripristinato rieseguendo la fase precedente (es. `./bin/rt prepare <cartella>`).
2. I file sorgente (`trascritto grezzo.md`, `audio.m4a`, `trascritto grezzo.json`) **non vengono mai modificati**.
3. Il file `review_decisions.json` preserva le decisioni umane già prese, evitando di dover rispondere due volte allo stesso quesito.
