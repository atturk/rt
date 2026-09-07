Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Configurazione divisa in più file (`config/`) + pricing per-route sotto il modello

## Contesto

`rt.config.yaml` è cresciuto nel tempo mescolando impostazioni globali (retry, soglie, credenziali, pricing) con la configurazione di 4 job cognitivi diversi in un unico file lungo, reso ancora meno leggibile dai numerosi commenti aggiunti in sessione. Si vuole poter dividere la configurazione in più file (uno per job + uno generale), mantenendo **piena retrocompatibilità** con il singolo file esistente, e spostare il pricing custom direttamente sotto ogni route (accanto al modello che lo usa) invece che in una sezione globale separata. Questo è anche propedeutico a un prossimo task (selezione interattiva dei prezzi da aggiornare) che scriverà direttamente nei file per-job.

**Verificato prima di procedere**: il resto della codebase (client, router, pipeline) lavora esclusivamente sull'oggetto `RTConfig` già assemblato in memoria — nessun altro file legge `rt.config.yaml` direttamente. Questo significa che il cambiamento è isolato quasi interamente a `rt/core/config.py`, funzione `load_config()`: cambia solo **come** l'oggetto viene costruito da disco, non la sua forma finale.

---

## A. Caricamento da cartella `config/` con fallback al singolo file

### Design
`load_config(config_path=None)` oggi (righe 322-339 di `rt/core/config.py`) legge sempre `rt.config.yaml` (o il path esplicito passato). Comportamento nuovo:
- Se `config_path` è passato esplicitamente (usato ovunque nei test esistenti) → **comportamento invariato al 100%**, singolo file, nessun cambiamento.
- Se `config_path` è `None`: controllare se esiste una cartella `config/` nella working directory.
  - Se sì → modalità "split": caricare `config/general.yaml` (impostazioni globali) + ogni altro `config/<nome>.yaml` (uno per job, nome del file = nome del job), unire tutto in un unico dizionario e passarlo a `RTConfig.model_validate()` **esattamente come oggi** (così tutta la logica esistente di normalizzazione/validazione, inclusa la registrazione delle credenziali custom, si applica automaticamente senza modifiche).
  - Se no → fallback al comportamento attuale con `rt.config.yaml` singolo, invariato.

### Implementazione
Refactoring minimo di `rt/core/config.py`:
```python
def _load_rtconfig_from_file(path: str) -> RTConfig:
    """Carica un singolo file YAML e lo valida come RTConfig. Comportamento invariato
    rispetto alla load_config() precedente per un path esplicito."""
    if not os.path.exists(path):
        return RTConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_text = f.read()
        data = yaml.safe_load(raw_text)
        if isinstance(data, dict):
            return RTConfig.model_validate(data)
    except Exception:
        pass
    return RTConfig()


def _load_config_dir(config_dir: str) -> RTConfig:
    """Carica la configurazione divisa: config/general.yaml (impostazioni globali) +
    un file config/<job>.yaml per ciascun job (il nome del file, senza estensione,
    diventa la chiave in 'jobs'). Il file 'general.yaml' non è un job."""
    merged_data: Dict[str, Any] = {}

    general_path = os.path.join(config_dir, "general.yaml")
    if os.path.isfile(general_path):
        with open(general_path, "r", encoding="utf-8") as f:
            general_data = yaml.safe_load(f.read())
        if isinstance(general_data, dict):
            merged_data.update(general_data)

    jobs_data: Dict[str, Any] = {}
    for fname in sorted(os.listdir(config_dir)):
        if not fname.endswith(".yaml") or fname == "general.yaml":
            continue
        job_name = fname[:-len(".yaml")]
        with open(os.path.join(config_dir, fname), "r", encoding="utf-8") as f:
            job_data = yaml.safe_load(f.read())
        if isinstance(job_data, dict):
            jobs_data[job_name] = job_data
    if jobs_data:
        merged_data["jobs"] = jobs_data

    return RTConfig.model_validate(merged_data)


def load_config(config_path: Optional[str] = None) -> RTConfig:
    """Carica la configurazione. Se config_path è esplicito, comportamento invariato
    (singolo file). Se None: usa la cartella 'config/' se presente (modalità divisa),
    altrimenti ricade su 'rt.config.yaml' singolo (comportamento storico)."""
    if config_path is not None:
        return _load_rtconfig_from_file(config_path)

    config_dir = os.path.join(os.getcwd(), "config")
    if os.path.isdir(config_dir):
        try:
            return _load_config_dir(config_dir)
        except Exception:
            pass
        return RTConfig()

    return _load_rtconfig_from_file(os.path.join(os.getcwd(), "rt.config.yaml"))
```
Rimuovere il vecchio corpo di `load_config` sostituendolo con questo. Nessuna modifica al `model_validator(mode="before")` `normalize_llm_and_jobs_config` (righe 237-292) — riceve lo stesso dizionario unito di sempre, la registrazione delle credenziali custom (già presente per il caso `credentials:` in `general.yaml`) funziona automaticamente senza modifiche.

### Edge case e invarianti
- **Precedenza esplicita**: se esistono ENTRAMBI `config/` e `rt.config.yaml`, vince `config/` (comportamento deciso e da documentare chiaramente).
- Tutti i test esistenti che chiamano `load_config(qualche_path_esplicito)` devono continuare a passare invariati — verificarlo esplicitamente.
- Se `config/` esiste ma è vuota o priva di `general.yaml`, il caricamento non deve fallire — semplicemente usa i default di `RTConfig` per le impostazioni globali e solo i job effettivamente trovati come file.

---

## B. Campo `pricing` per-route, sotto il modello

### Design
Aggiungere un campo opzionale a `RouteConfig` (`rt/core/config.py`, righe 30-46):
```python
from rt.llm.pricing import ModelPricing  # nessun rischio di import circolare: rt/llm/pricing.py non importa nulla da rt.core né da altri moduli rt.llm (verificato)

class RouteConfig(BaseModel):
    ...
    pricing: Optional[ModelPricing] = Field(default=None, description="Prezzo specifico per questa route (priorità massima: sovrascrive sia il pricing custom globale sia DEFAULT_PRICING)")
```
Così un utente può scrivere, direttamente sotto una route:
```yaml
primary:
  provider: "google"
  model: "gemini-3.5-flash-lite"
  pricing:
    input_per_million: 0.0
    output_per_million: 0.0
```
(esempio volutamente a costo zero, per un modello genuinamente free-tier che l'utente non vuole veder "corretto" da un prezzo di listino live in un task futuro).

### Risoluzione del prezzo effettivo in `rt/llm/client.py`
Oggi `calculate_cost(..., custom_pricing=self.config.pricing)` viene chiamato in 2 punti (cercare `custom_pricing=self.config.pricing` nel file — il numero di riga esatto potrebbe essere cambiato rispetto a versioni precedenti di questa sessione). Aggiungere un metodo helper alla classe `LLMClient`:
```python
def _resolve_custom_pricing(self, route: "RouteConfig", provider_name: str, model_name: str) -> Optional[Dict[str, Any]]:
    """Se la route ha un pricing specifico, lo inietta come override esatto per
    (provider_name, model_name) sopra il pricing custom globale — priorità massima,
    nessuna ambiguità di matching perché la chiave è esattamente quella usata."""
    base = dict(self.config.pricing or {})
    if getattr(route, "pricing", None) is not None:
        prov_dict = dict(base.get(provider_name, {}))
        prov_dict[model_name] = route.pricing.model_dump()
        base[provider_name] = prov_dict
    return base or None
```
E sostituire entrambe le chiamate `custom_pricing=self.config.pricing` con `custom_pricing=self._resolve_custom_pricing(route, provider_name, model_name)` (in entrambi i punti in cui oggi si chiama `calculate_cost`, sia nel ramo di streaming che in quello di successo/errore finale — `route`, `provider_name`, `model_name` sono già variabili nello scope locale in entrambi i punti). **Nessuna modifica a `rt/llm/pricing.py`**: `calculate_cost` continua a funzionare esattamente come oggi, riceve solo un dizionario `custom_pricing` già arricchito.

### Edge case e invarianti
- Priorità finale del prezzo: **route.pricing** (se impostato) > **cfg.pricing globale** (sezione `pricing:` in `general.yaml`/nel file singolo) > **DEFAULT_PRICING hardcoded**. Nessuna modifica a questo ordine per chi non usa `route.pricing`.
- Se `route.pricing` non è impostato (`None`, il default), il comportamento è **identico a oggi**, bit per bit.
- `ModelPricing` importato da `rt/llm/pricing.py` in `rt/core/config.py`: verificare che non si crei un ciclo di import eseguendo l'intera suite di test dopo la modifica (atteso: nessun problema, il modulo pricing.py non ha dipendenze interne).

---

## C. `.gitignore`, file di esempio, documentazione

1. In `.gitignore`, accanto alle righe esistenti `rt.config.yaml` / `!rt.config.yaml.example`, aggiungere:
```
config/
!config.example/
```
2. Creare una cartella `config.example/` (parallela a `rt.config.yaml.example`, quindi versionata in git) con lo stesso contenuto di `rt.config.yaml.example` ma diviso: `config.example/general.yaml` (versione/retry/thresholds/mock_llm/streaming/show_monitor*/pricing_staleness_warning_days/eventuale sezione `credentials:` di esempio) + `config.example/outline.yaml`, `config.example/rewrite.yaml`, `config.example/review_asr.yaml`, `config.example/review_science.yaml` (ciascuno con lo stesso contenuto della sezione corrispondente già presente in `rt.config.yaml.example`, inclusi tutti i commenti esistenti). Aggiungere anche un esempio di `pricing:` per-route nel file di un job (es. `config.example/rewrite.yaml`, sul modello free-tier, mostrando `pricing: {input_per_million: 0.0, output_per_million: 0.0}`).
3. Aggiornare `README.md`/`docs/DEVELOPMENT.md` con una breve sezione che spiega le due modalità equivalenti: file singolo `rt.config.yaml` (copiandolo da `rt.config.yaml.example`) OPPURE cartella `config/` (copiandola da `config.example/`), con la nota sulla precedenza (`config/` vince se entrambi presenti).

---

## Invarianti generali da rispettare in tutto il task

1. **Zero regressioni per chi usa il singolo file**: tutti gli utenti/test che oggi usano `rt.config.yaml` (con o senza path esplicito) devono continuare a funzionare identicamente.
2. **Nessuna modifica al modello `RTConfig`/`JobRoutingConfig`/logica di normalizzazione esistente** oltre al nuovo campo `pricing` su `RouteConfig` — la struttura in memoria resta la stessa, cambia solo come viene popolata da disco.
3. **Nessuna migrazione automatica**: questo task non scrive/converte file per l'utente, si limita a supportare entrambe le modalità di lettura. La migrazione (se vorrà farla) resta manuale per ora.

## Test di accettazione (`pytest tests/`)

In un nuovo file `tests/test_config_split.py`:
1. Con una cartella `config/` di test (`tmp_path`) contenente `general.yaml` (con `retry:`, `pricing_staleness_warning_days: 3`) e `outline.yaml`/`rewrite.yaml` (ciascuno con un `primary:` valido), verificare che `load_config()` (chiamato con `cwd` puntata a quella cartella, o adattando la funzione per accettare la working directory nei test — usare `monkeypatch.chdir(tmp_path)`) produca un `RTConfig` equivalente a quello che si otterrebbe costruendo lo stesso contenuto in un unico `rt.config.yaml`.
2. Verificare la precedenza: se sia `config/` che `rt.config.yaml` esistono nella stessa working directory di test, vince `config/`.
3. Verificare che con `config_path` esplicito passato a `load_config`, il comportamento sia identico a prima di questo task (nessuna modalità split applicata), anche se una cartella `config/` esiste nella working directory.
4. Verificare che `credentials:` dichiarate in `config/general.yaml` vengano registrate correttamente in `GLOBAL_CREDENTIALS` (stesso test pattern già usato per il caso singolo file in `tests/test_openai_compatible_provider.py`).
5. Un test per il campo `pricing` su `RouteConfig`: costruire una `RouteConfig` con `pricing={"input_per_million": 0.0, "output_per_million": 0.0}`, verificare che `route.pricing.input_per_million == 0.0`.
6. Un test per `LLMClient._resolve_custom_pricing`: con una route che ha `pricing` impostato, verificare che il dizionario risultante contenga quell'esatta voce per (provider, model), preservando le altre voci eventualmente già presenti in `self.config.pricing`.
7. Un test end-to-end: un job con `route.pricing` impostato a un valore volutamente diverso sia da `DEFAULT_PRICING` sia da un eventuale `cfg.pricing` globale, verificare (mockando `requests.post` con token noti) che il costo stimato nella telemetria rifletta il prezzo della route, non gli altri due.
8. Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e confermare zero regressioni sui test esistenti (205 attuali + i nuovi).

## Verifica finale
Rieseguire `python3 -m pytest tests/ -q`. Verificare che la CI passi su entrambe le versioni Python della matrice per il commit di questo task.
