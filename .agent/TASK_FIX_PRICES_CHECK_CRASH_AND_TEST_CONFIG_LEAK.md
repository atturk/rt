Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Fix crash di `prices-check` su route non configurate + isolamento dei test da una `config/` reale in locale

## Contesto

Dopo il task sul "guscio vuoto" (`TASK_EMPTY_SHELL_PROVIDERS_AND_EXPLICIT_CREDENTIALS.md`), sono emersi due problemi concreti, verificati entrambi in prima persona (non per ipotesi):

1. **Crash reale riportato dall'utente**: `./bin/rt prices-check` solleva `AttributeError: 'NoneType' object has no attribute 'lower'` non appena un job ha una route con `provider: null` (lo stato di default oggi in `config.example/`, e lo stato temporaneo di qualunque job che l'utente non ha ancora finito di configurare).
2. **La suite di test non è isolata da una `config/` reale nella working directory di sviluppo**: rieseguendo `python3 -m pytest tests/ -q` dalla root del repository con una vera cartella `config/` presente (esattamente come consigliato dal README per l'uso normale di RT), 21 test fallivano — non per un bug nella loro logica, ma perché leggevano ambientalmente la `config/` reale invece di partire da uno stato controllato. In CI questo non si manifesta mai (il checkout di GitHub non ha una `config/`, essendo in `.gitignore`), ma in locale sì, per chiunque segua le istruzioni ufficiali del progetto e poi lanci anche la suite di test nello stesso checkout.

---

## A. Fix del crash in `rt/llm/pricing_sync.py`

In `collect_configured_routes(cfg)`, il ciclo che costruisce la chiave normalizzata:
```python
for route, path in candidates:
    key = (route.provider.lower().strip(), route.model.lower().strip().lstrip("~"))
```
va protetto saltando le route non configurate (stato legittimo dopo il task del guscio vuoto, non un errore):
```python
for route, path in candidates:
    if route.provider is None or route.model is None:
        continue
    key = (route.provider.lower().strip(), route.model.lower().strip().lstrip("~"))
```
(Adattare alla forma esatta attuale del ciclo — nel frattempo la funzione include già la tupla `path` introdotta dal task sui prezzi interattivi; non toccare quella parte, solo aggiungere il guard.)

Verificare inoltre `check_configured_pricing(cfg)` (stessa funzione, chiama `collect_configured_routes`): con il guard sopra, i job non configurati semplicemente non compaiono nel report — comportamento corretto e sufficiente, non serve stampare un avviso speciale per loro (chi vuole sapere se un job è configurato usa già l'errore chiaro introdotto da `_job_has_configured_route` in `rt/cli.py` quando prova a eseguirlo davvero).

### Test di accettazione
In `tests/test_pricing_sync.py` (file esistente), aggiungere un test che costruisce un `RTConfig` con almeno un job avente `primary=RouteConfig(provider=None, model=None)` e verifica che `collect_configured_routes`/`check_configured_pricing` non sollevino eccezioni e semplicemente omettano quel job dal risultato.

---

## B. Isolare i test da una `config/` reale nella working directory

### Causa esatta (verificata)
`load_config(config_path=None)` (in `rt/core/config.py`) fa `os.path.isdir(os.path.join(os.getcwd(), "config"))`: se la working directory da cui parte `pytest` (tipicamente la root del repo) contiene una `config/` reale, `LLMClient(force_mock=...)` costruito senza un `config_path` esplicito nei test (decine di call site in `tests/test_llm_config.py`, `test_llm_router.py`, `test_llm_timeout_retry.py`, `test_free_tier_guard.py`, `test_monitor_ux_and_abort.py`, `test_reasoning_required_retry.py`, `test_telemetry.py`, `test_openai_compatible_provider.py`, tra gli altri) legge silenziosamente quella `config/` reale invece di partire da uno stato di test controllato. Il meccanismo di mitigazione già introdotto dal task precedente (`tests/conftest.py`, fixture `_setup_test_jobs` che sostituisce `RTConfig.__init__`) non copre questo caso: quando `load_config()` trova una `config/` reale, costruisce `RTConfig.model_validate(merged_data)` con la chiave `"jobs"` già popolata dai file reali, quindi la condizione `"jobs" not in kwargs` della fixture esistente è falsa e l'iniezione dei job di test non scatta — la config reale vince comunque.

### Fix: sostituire `load_config` stesso nei punti in cui è importato a livello di modulo

Individuati con `grep -rn "^from rt.core.config import.*load_config" rt/` esattamente questi 3 moduli che importano `load_config` a livello di modulo (binding indipendente, va patchato in ciascuno separatamente — patchare solo `rt.core.config.load_config` NON basta per questi, per la normale semantica di `from X import Y` in Python):
- `rt/llm/client.py` (usato da `LLMClient.__init__`, che è la via con cui la stragrande maggioranza dei test e di `rt/pipeline/outline.py`, `rewrite.py`, `review_science.py`, `review_asr.py` costruisce il client)
- `rt/pipeline/review_asr.py`
- `rt/pipeline/smoke_test.py`

Patchare anche l'attributo su `rt.core.config` stesso, per coprire gli import locali dinamici già presenti in `rt/cli.py` (es. `from rt.core.config import load_config` dentro il corpo di `cmd_outline`/`cmd_run`/ecc.), che essendo eseguiti ad ogni chiamata rileggono l'attributo corrente del modulo e quindi vedono automaticamente la versione patchata.

In `tests/conftest.py`, aggiungere una nuova fixture `autouse` (accanto a quelle esistenti):
```python
@pytest.fixture(autouse=True)
def _isolate_load_config_from_ambient_repo_config(monkeypatch):
    """Una vera cartella config/ nella working directory di sviluppo (creata per l'uso
    reale di RT, come consigliato dal README) non deve mai influenzare i test che non la
    richiedono esplicitamente: altrimenti chiunque esegua 'pytest' dalla root del repo dopo
    aver configurato RT per uso reale otterrebbe risultati diversi da un checkout pulito
    (es. CI, dove config/ non esiste essendo in .gitignore). Sostituisce load_config, in
    ciascun modulo che lo importa a livello di modulo, con una versione che ignora
    l'auto-discovery su disco quando invocata senza un config_path esplicito, restituendo
    invece job di test predefiniti e operativi.

    I test che vogliono ESATTAMENTE testare l'auto-discovery su disco di load_config
    (tests/test_config_split.py, tests/test_empty_shell_credentials.py) importano load_config
    a livello di modulo PRIMA che questa fixture venga applicata: mantengono quindi un proprio
    riferimento alla funzione originale, del tutto immune a questa sostituzione (semantica
    standard di 'from X import Y' in Python — un monkeypatch.setattr successivo sull'attributo
    del modulo sorgente non altera un binding già effettuato altrove). Nessuna esclusione
    esplicita per nodeid è quindi necessaria, a differenza della fixture _setup_test_jobs qui sopra."""
    import rt.core.config
    import rt.llm.client
    import rt.pipeline.review_asr
    import rt.pipeline.smoke_test

    original_load_config = rt.core.config.load_config

    def patched_load_config(config_path=None):
        if config_path is not None:
            return original_load_config(config_path)
        return rt.core.config.RTConfig(jobs=_test_default_jobs())

    monkeypatch.setattr(rt.core.config, "load_config", patched_load_config)
    monkeypatch.setattr(rt.llm.client, "load_config", patched_load_config)
    monkeypatch.setattr(rt.pipeline.review_asr, "load_config", patched_load_config)
    monkeypatch.setattr(rt.pipeline.smoke_test, "load_config", patched_load_config)
```
(Riusa `_test_default_jobs()`, già definita in `tests/conftest.py` dal task precedente — non duplicarla.)

### Verifica di non-ridondanza con la fixture esistente
Con questa nuova fixture attiva, `LLMClient(force_mock=...)` senza `config_path` esplicito non arriva mai più a costruire una `RTConfig()` bare tramite `load_config()` che legga il disco: riceve direttamente `RTConfig(jobs=_test_default_jobs())` dal `patched_load_config`. Questo rende probabilmente **ridondante** la fixture `_setup_test_jobs` esistente (quella che patcha `RTConfig.__init__`), la cui unica ragion d'essere era coprire proprio questo caso con un meccanismo più fragile (basato su corrispondenza di sottostringa sul `nodeid`). Verificare concretamente (rieseguendo la suite con `_setup_test_jobs` temporaneamente disattivata) se resta ancora necessaria per qualche test che costruisce `RTConfig()` bare DIRETTAMENTE (non tramite `load_config`) — se non ne resta nessuno, rimuoverla e tenere solo la nuova fixture, più semplice e robusta. Se invece resta un caso reale che la richiede, mantenerle entrambe e documentare chiaramente nel commento perché servono entrambe.

### Verifica esplicita della correzione (fondamentale)
Il modo per cui l'utente si è accorto del problema è specifico: una vera cartella `config/` nella root del repository. **Riprodurre esattamente questa condizione prima di dichiarare il fix corretto**: NON limitarsi a rieseguire la suite in un ambiente pulito senza `config/` (che oggi passa già ed è il caso meno interessante). Creare temporaneamente una `config/` di prova nella root del repository (es. copiando `config.example/` e impostando in un job un `provider`/`model` reale, come ha fatto l'utente), rieseguire `python3 -m pytest tests/ -q` da lì, confermare che il conteggio dei test passati non cambi rispetto a un ambiente senza quella cartella, poi rimuovere la cartella di prova al termine (non lasciarla nel repository, non è un file da versionare).

---

## Verifica finale
1. `python3 -m pytest tests/ -q` deve passare per intero, sia con sia senza una `config/` reale nella working directory (vedi verifica esplicita sopra).
2. Eseguire manualmente `python3 -m rt.cli prices-check` (o `./bin/rt prices-check`) in una directory con un `config/` che abbia almeno un job con `provider: null`, e confermare che non crashi più e produca un report che semplicemente omette quel job.
3. `grep -rn "^from rt.core.config import.*load_config" rt/` deve continuare a restituire esattamente gli stessi 3 moduli elencati sopra (se in futuro se ne aggiungono altri, andranno inclusi nella fixture di isolamento — annotarlo come nota nel commento della fixture stessa, già presente nella bozza sopra).
