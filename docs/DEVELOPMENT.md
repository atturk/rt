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

### Dipendenze di sistema (macOS)

- **ffmpeg**: ritaglio/riproduzione clip audio durante la review (`rt/core/audio_clip.py`). `brew install ffmpeg`.
- **macparakeet-cli**: trascrizione ASR delle lezioni (`rt/pipeline/setup.py::find_macparakeet_binary()`). Installato automaticamente da `./install.sh` via Homebrew (`brew install moona3k/tap/macparakeet-cli`).
- **micro** (consigliato al posto di `nano`): editor per le correzioni testuali durante la review interattiva (`rt/core/editor_edit.py`), navigazione a frecce/mouse e scorciatoie standard (`Ctrl+S` salva, `Ctrl+Q` esce) invece dei comandi di `nano`. `brew install micro`, poi `export EDITOR=micro` nel proprio shell profile. Se `$EDITOR` non è impostata, il fallback resta `nano`.

---

## 2. Esecuzione della Test Suite

La suite di test è collocata nella cartella `tests/` ed è suddivisa in 25 file di test mirati:

- `test_audio_run.py`: pipeline audio ingest, split e normalizzazione.
- `test_checkpointing.py`: recovery e checkpointing transazionale per-unità.
- `test_cli_review.py`: comandi interattivi human-in-the-loop della CLI.
- `test_dag_freshness.py`: invalidazione transitiva del DAG e freschezza artefatti.
- `test_encoding.py`: bonifica mojibake e sanitizzazione codifica UTF-8.
- `test_idempotency.py`: suite di idempotenza, economia token (0 chiamate LLM al rerun) e crash-safety.
- `test_integration.py`: esecuzione end-to-end completa su fixture sintetica.
- `test_issue_accounting.py`: contabilità deterministica delle issue ASR e Science.
- `test_ledger.py`: funzionamento del decision ledger e applicazione atomica idempotente delle decisioni.
- `test_llm_config.py`: validazione configurazione YAML, routing dei job e gestione sicura dei secret.
- `test_llm_google_provider.py`: adapter Google Gemini nativo e configurazione Dual-Key.
- `test_llm_router.py`: routing deterministico, failover a cascata e policy di fallback.
- `test_llm_timeout_retry.py`: timeout wall-clock reale, deadline attempt e retry bounded.
- `test_pricing.py`: pricing listini ufficiali, formalizzazione openrouter/free e matching deterministico.
- `test_regression_biochem.py`: test di regressione sui 499 segmenti della lezione reale di biochimica.
- `test_renderer.py`: **test vincolo timestamp** (verifica che il timestamp derivi dal segmento e fallisca se manomesso).
- `test_science.py`: classificazione nei 4 scenari scientifici (`ERR_DOCENTE`, `ERR_RECONSTRUCTION`, `SCIENCE_CHECK`).
- `test_science_grounding.py`: ancoraggio epistemico al trascritto ASR e mitigazione allucinazioni.
- `test_segments.py`: parser ASR (macparakeet-cli e MacWhisper legacy), intervalli temporali e finestra di contesto scorrevole ~90s.
- `test_setup.py`: setup cartella, mock deterministico ASR e inizializzazione info.yaml.
- `test_source_truth_json.py`: integrità e immutabilità del trascritto grezzo sorgente.
- `test_telemetry.py`: telemetria unificata, aggregazione breakdown per job/provider e persistenza disco.
- `test_timestamp.py`: conversioni tra stringhe timecode e float seconds, parsing intervalli.
- `test_validation.py`: controlli di ordinamento, coerenza e calcolo della copertura didattica dell'outline.

Per eseguire l'intera suite:
```bash
python3 -m pytest tests/ -q
```

---

## 3. Configurazione Provider LLM

RT supporta **OpenRouter**, **DeepSeek direct** e **Google Gemini** tramite provider adapter dedicati in `rt/llm/providers/`.

### Configurazione (`config/`):
Il sistema viene configurato copiando `config.example/` in `config/`:
- `general.yaml` (solo nella cartella radice) per le impostazioni globali e credenziali/provider/pricing globali.
- Un file `<job>.yaml` per ciascun job cognitivo, cercato ricorsivamente in tutta `config/` — nel template sono organizzati in `config/rt/` (pipeline principale: `outline.yaml`, `rewrite.yaml`, `review_asr.yaml`, `review_science.yaml`) e `config/telegram/` (active recall: `recall_quiz.yaml`, `recall_mirata.yaml`, `recall_vasta.yaml`, `recall_eval_mirata.yaml`, `recall_eval_vasta.yaml`), ma la struttura di sottocartelle è libera.

Lo schema di configurazione mappa ciascun job cognitivo con route `primary`, fallback dedicati ed eventuale `pricing:` per-route:
```yaml
# In config/rt/outline.yaml:
max_output_chars: 60000
primary:
  provider: "openrouter"            # Provider di default per outline
  credential: "openrouter"
  model: "deepseek/deepseek-chat"
  thinking: true
  reasoning_effort: "low"
  max_tokens: 16384
  timeout_seconds: 180
  # Pricing per-route opzionale (priorità massima: sovrascrive pricing globale e DEFAULT_PRICING):
  # pricing:
  #   input_per_million: 0.14
  #   output_per_million: 0.28
```

### Variabili d'Ambiente:
- Per OpenRouter: `export OPENROUTER_API_KEY="sk-or-..."`
- Per DeepSeek: `export DEEPSEEK_API_KEY="sk-..."`
- Per Google Gemini: `export GOOGLE_API_KEY_1="AIzaSy..."` e `export GOOGLE_API_KEY_2="AIzaSy..."` (Dual-Key) oppure `export GEMINI_API_KEY="AIzaSy..."`
(oppure inserite in `.env` locale non versionato).

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
