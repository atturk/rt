Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Config out-of-the-box come guscio vuoto — provider/credenziali sempre espliciti, mai hardcoded

## Contesto e decisione presa

Oggi `rt/llm/credentials.py` registra automaticamente nel codice (`CredentialRegistry._register_default_credentials()`) le credenziali per `openrouter`/`deepseek`/`google_1`/`google_2`, con i relativi nomi di env var hardcoded. Questo significa che scrivendo `provider: "openrouter"` in un job YAML, senza mai dichiarare nulla in `general.yaml`, il sistema "indovina" comunque `OPENROUTER_API_KEY` come variabile d'ambiente da leggere.

**Decisione esplicita**: questo comportamento implicito va eliminato del tutto. `config.example/` deve essere un guscio realmente vuoto — nessun provider assunto, utile sia a chi vuole DeepSeek/OpenRouter/Google sia a chi vuole usare solo modelli locali (via il provider generico `openai_compatible`). Chiunque voglia usare un provider, **compreso uno di quelli "nativi"**, deve dichiararlo esplicitamente in `config/general.yaml` sotto `credentials:`. Zero magie implicite di nessun tipo.

**Vincolo altrettanto esplicito**: questo NON deve introdurre crash. Un file YAML con `provider: null` deve caricarsi senza errori (è lo stato "non ancora configurato", non un errore). L'utente deve ricevere un avviso chiaro a schermo quando prova a eseguire un comando che richiede un job non configurato — mai uno stack trace Pydantic grezzo.

---

## A. `rt/llm/credentials.py` — rimuovere le scorciatoie built-in

In `CredentialRegistry._register_default_credentials()`: rimuovere le registrazioni di `openrouter`, `deepseek`, `google_1`, `google_2` e la relativa assegnazione in `_provider_defaults` per questi tre provider reali. **Mantenere** la registrazione di `"mock"` (`CredentialRef(name="mock", provider="mock", env_var=None)` + `self._provider_defaults["mock"] = "mock"`) — non è un provider cloud reale, è lo scaffolding interno per `mock_llm`/`force_mock`, estraneo alla richiesta dell'utente.

Il metodo diventa quindi:
```python
def _register_default_credentials(self) -> None:
    """Registra solo il riferimento 'mock' (scaffolding interno per force_mock/mock_llm).
    Nessuna credenziale per provider reali (openrouter/deepseek/google) è registrata di
    default: ogni provider reale richiede una dichiarazione esplicita 'credentials:' in
    config/general.yaml, anche per i provider nativi. Zero magie implicite."""
    self.register(CredentialRef(name="mock", provider="mock", env_var=None))
    self._provider_defaults["mock"] = "mock"
```

In `get_api_key()`, rimuovere le due euristiche di fallback che aggirano una registrazione esplicita:
1. Il ramo `elif f"{clean_c.upper()}_API_KEY" in os.environ: return os.environ.get(f"{clean_c.upper()}_API_KEY")` (indovina il nome della env var dal nome della credenziale/provider).
2. Il fallback speciale per `ref.name == "google_1"` su `GEMINI_API_KEY`/`GOOGLE_API_KEY` (era legato al nome privilegiato built-in `google_1`, che ora non è più un nome speciale — un utente potrebbe chiamare una sua credenziale custom "google_1" e non deve ereditare comportamenti nascosti).

Il ramo "Fallback retrocompatibile: se clean_c è un provider registrato, prova la default" (righe `if clean_c in self._provider_defaults: ref = ...`) **resta invariato** — non reintroduce alcun bias hardcoded, consulta dinamicamente `_provider_defaults`, che ora è popolato solo da ciò che l'utente dichiara.

**Nessuna modifica necessaria a `client.py`**: il meccanismo che gestisce una API key mancante (`rt/llm/client.py` righe 285-313, `AuthenticationFailure` con il nome esatto della env var mancante, supporto failover su `fallback.auth` se configurato) è già corretto e non silenzioso — verificato leggendo il codice. Una volta rimosse le scorciatoie, questo meccanismo scatta naturalmente e correttamente per qualunque provider senza credenziale risolta.

---

## B. `rt/core/config.py` — route "non configurate" come stato legittimo, non un errore

### B.1 — `RouteConfig`
Cambiare i default dei due campi identità da valori hardcoded a `None`:
```python
provider: Optional[str] = Field(default=None, description="deepseek | openrouter | google | openai_compatible (None = route non ancora configurata)")
model: Optional[str] = Field(default=None, description="Identificativo del modello per il provider (None = route non ancora configurata)")
```

In `model_post_init`, aggiungere un ramo di uscita immediata quando la route è un placeholder intenzionalmente vuoto:
```python
def model_post_init(self, __context: Any) -> None:
    """Validazione config-time delle route. Una route con provider=None è uno slot
    intenzionalmente non configurato (placeholder in config.example/): non viene validata
    qui. Sta al chiamante (rt/cli.py, _job_has_configured_route) verificare che una route
    configurata esista prima di eseguire lavoro reale, con un messaggio chiaro."""
    if self.provider is None:
        return
    from rt.llm.credentials import GLOBAL_CREDENTIALS
    clean_p = self.provider.lower().strip()
    # ... TUTTO il resto del corpo esistente invariato (allowed_providers, controllo model
    # vuoto, controllo base_url per openai_compatible, anti-mismatch base_url, risoluzione
    # credential) ...
```
Importante: se `provider` è impostato (non `None`) ma `model` è vuoto/assente, il comportamento **deve restare quello attuale** (`ValueError: "Il modello per il provider ... non può essere vuoto."`) — una route "a metà" resta un errore di configurazione reale, solo lo stato "completamente vuoto" (entrambi `None`) è legittimo.

Aggiungere una proprietà di comodo, usata anche dal punto C:
```python
@property
def is_configured(self) -> bool:
    return self.provider is not None and self.model is not None
```

### B.2 — `_build_default_jobs()`
Questi sono i default "bare" di `RTConfig()` (usati solo quando non esiste alcuna sorgente di configurazione, prima ancora del controllo CLI). Oggi costruiscono route DeepSeek reali hardcoded — è esattamente lo stesso tipo di default silenzioso già eliminato a livello di `load_config()` nel task precedente (`TASK_NO_SILENT_CONFIG_DEFAULT_...`), solo un livello più in basso. Vanno resi anch'essi vuoti, mantenendo però i parametri di tuning (non identitari):
```python
def _build_default_jobs() -> Dict[str, JobRoutingConfig]:
    return {
        "outline": JobRoutingConfig(
            primary=RouteConfig(thinking=True, reasoning_effort="low", max_tokens=16384, timeout_seconds=240)
        ),
        "rewrite": JobRoutingConfig(
            primary=RouteConfig(thinking=True, reasoning_effort="low", max_tokens=8192, timeout_seconds=180)
        ),
        "review_asr": JobRoutingConfig(
            primary=RouteConfig(thinking=True, reasoning_effort="low", max_tokens=8192, timeout_seconds=120)
        ),
        "review_science": JobRoutingConfig(
            primary=RouteConfig(thinking=True, reasoning_effort="low", max_tokens=8192, timeout_seconds=180)
        ),
    }
```
(Rimossi `provider="deepseek"`, `model="deepseek-v4-flash"`, `base_url="https://api.deepseek.com"` da ciascuna; il resto dei parametri invariato.)

---

## C. `rt/cli.py` — avviso chiaro invece di crash quando un job non ha provider

Aggiungere un helper vicino a `_has_real_config_source()`:
```python
def _job_has_configured_route(job_cfg) -> bool:
    """Vero se il job ha almeno una route primaria con provider/model impostati."""
    return bool(job_cfg and job_cfg.primary and job_cfg.primary.is_configured)
```

Nei 4 comandi a job singolo (`cmd_outline`, `cmd_rewrite`, `cmd_review_asr`, `cmd_review_science`), **subito dopo** il controllo `_has_real_config_source()` già esistente dal task precedente (stesso blocco `if not getattr(args, "mock", False)`), aggiungere il controllo sul job specifico:
```python
if not getattr(args, "mock", False):
    from rt.core.config import load_config
    cfg = load_config()
    job_cfg = cfg.jobs.get("outline")  # nome job specifico per ciascun comando
    if not _job_has_configured_route(job_cfg):
        print(
            "❌ Il job 'outline' non ha alcun provider configurato in config/outline.yaml.\n"
            "   Apri config/general.yaml, dichiara una credenziale sotto 'credentials:' (nome, provider, env_var),\n"
            "   imposta la variabile d'ambiente corrispondente, poi imposta 'provider'/'model' sotto 'primary:'\n"
            "   in config/outline.yaml. Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi completa.",
            file=sys.stderr
        )
        sys.exit(1)
```
(Adattare il nome del job e il nome del file nel messaggio per ciascun comando: `outline`/`rewrite`/`review_asr`/`review_science`.)

In `cmd_run`, che esegue l'intera pipeline attraverso tutti e 4 i job, il controllo va fatto **una sola volta, per tutti e 4 i job insieme, prima di iniziare qualunque lavoro** (non job per job durante l'esecuzione — l'utente deve sapere subito tutto ciò che manca, non scoprirlo a metà pipeline dopo aver già speso tempo su trascrizione/setup):
```python
if not mock_mode:
    from rt.core.config import load_config
    cfg = load_config()
    missing = [j for j in ("outline", "rewrite", "review_asr", "review_science")
               if not _job_has_configured_route(cfg.jobs.get(j))]
    if missing:
        print(
            f"❌ I seguenti job non hanno un provider configurato: {', '.join(missing)}.\n"
            "   Apri config/general.yaml, dichiara una credenziale sotto 'credentials:' (nome, provider, env_var),\n"
            "   imposta la variabile d'ambiente corrispondente, poi imposta 'provider'/'model' sotto 'primary:'\n"
            "   nei rispettivi file config/<job>.yaml. Vedi docs/CONFIGURATION_REFERENCE.md per la sintassi completa.",
            file=sys.stderr
        )
        sys.exit(1)
```
Posizionarlo subito dopo il controllo `_has_real_config_source()` già presente in `cmd_run` (prima di `is_audio_input = any(...)`), quindi PRIMA di qualunque chiamata a `run_setup`/trascrizione/ecc.

**Nota**: questi due controlli chiamano `load_config()` una seconda volta (oltre a quella che avviene dentro `run_outline`/`run_rewrite`/ecc. più a valle) — è un costo trascurabile (lettura di pochi file YAML locali), accettabile per la chiarezza dell'errore upfront. Non tentare di ottimizzare passando la config già caricata attraverso le firme delle funzioni esistenti: fuori scope per questo task.

---

## D. `config.example/*.yaml` — provider/model/credential/base_url a `null`, tuning invariato

Per **tutti e 4** i file per-job (`outline.yaml`, `rewrite.yaml`, `review_asr.yaml`, `review_science.yaml`):
- Tenere **solo** il blocco `primary:` (rimuovere interamente `fallback:` e, in `rewrite.yaml`, anche `secondary:` — sono estensioni opzionali, documentate nel punto E, non necessarie per un primo avvio).
- In `primary:`, impostare `provider: null`, `credential: null`, `model: null`, `base_url: null`.
- **Mantenere invariati** tutti i campi di tuning non identitari: `thinking`, `reasoning_effort`, `max_thinking_tokens`/`max_tokens`, `timeout_seconds`, così come `round_robin`, `max_attempts`, `max_output_chars` in cima al file.
- **Attenzione in `rewrite.yaml`**: il file ha oggi `round_robin: true`, che richiede obbligatoriamente una route `secondary` (vincolo esistente in `JobRoutingConfig.model_post_init`, invariato da questo task) — se si rimuove `secondary:` senza cambiare `round_robin`, il file solleva un errore già al caricamento. Impostare quindi `round_robin: false` nel template out-of-the-box; il punto E documenta come riattivarlo insieme a `secondary:`.

Esempio (`outline.yaml`):
```yaml
round_robin: false
max_attempts: 4
max_output_chars: 45000

primary:
  provider: null
  credential: null
  model: null
  base_url: null
  thinking: true
  reasoning_effort: "low"
  max_thinking_tokens: 4098
  max_tokens: null
  timeout_seconds: 300
```

In `general.yaml`, aggiungere (non commentato, come template reale da duplicare/adattare) un esempio funzionante:
```yaml
credentials:
  - name: "openrouter"
    provider: "openrouter"
    env_var: "OPENROUTER_API_KEY"
```
(Nota per chi implementa: NON è più una scorciatoia nel codice — è l'utente stesso a scriverla nel proprio `config/general.yaml`, esattamente come qualunque altra credenziale custom. Chi vuole DeepSeek/Google o un provider locale duplica questo blocco cambiando `name`/`provider`/`env_var`.)

---

## E. `docs/CONFIGURATION_REFERENCE.md` — aggiornare la sezione credenziali

Riscrivere la sezione "Funzionalità opzionale: provider generico OpenAI-compatible e credenziali custom" (non è più "opzionale" per i provider nativi — ora è sempre richiesta) spiegando:
1. **Ogni provider, incluso quelli nativi (`deepseek`/`openrouter`/`google`), richiede una voce esplicita `credentials:` in `general.yaml`** — non esiste più alcuna scorciatoia integrata nel codice. `provider: "openrouter"` in un job senza una corrispondente voce `credentials:` in `general.yaml` fallirà con un errore chiaro al momento della chiamata reale (indicando l'esatta variabile d'ambiente mancante), non un default silenzioso.
2. Il flusso consigliato: apri `config/general.yaml` → aggiungi una voce sotto `credentials:` (nome a scelta, `provider` uno tra `deepseek`/`openrouter`/`google`/`openai_compatible`, `env_var` il nome della variabile che imposterai in `.env`) → imposta quella variabile in `.env` → in uno o più file `config/<job>.yaml`, imposta `provider`/`model` (e opzionalmente `credential:` col nome scelto, se hai più credenziali per lo stesso provider).
3. **Comportamento del default automatico per provider**: se dichiari una sola credenziale per un dato `provider`, diventa automaticamente quella di default — puoi ometterla dal campo `credential:` nei job che la usano. Se ne dichiari più di una per lo stesso provider (es. due chiavi Google per distribuire il carico), devi specificare esplicitamente `credential:` nel job per scegliere quale usare.
4. Esempio completo di duplicazione per due chiavi Google indipendenti:
```yaml
credentials:
  - name: "google_1"
    provider: "google"
    env_var: "GOOGLE_API_KEY_1"
  - name: "google_2"
    provider: "google"
    env_var: "GOOGLE_API_KEY_2"
```
5. Esempio per un modello locale senza API key (es. Ollama/vLLM): `provider: "openai_compatible"`, `base_url: "http://localhost:11434/v1"` (o l'endpoint locale usato), senza dichiarare alcuna `credentials:` per esso — se il server locale non richiede autenticazione, la chiamata funziona comunque (l'header `Authorization` verrà comunque inviato con una chiave placeholder, ignorata dai server locali senza auth).

Aggiungere anche una sezione "Route opzionali aggiuntive" con gli esempi di `fallback:` (le 5 chiavi: timeout/rate_limit/safety/auth/generic) e `secondary:`/`round_robin: true` per il round-robin dual-key, dato che sono stati rimossi dal template di `config.example/` per tenerlo minimale.

Aggiornare anche la sezione 1 (`general.yaml`) e la sezione "Note specifiche per job" per riflettere che i file per-job ora hanno solo `primary:` con provider/model a `null` di default, senza più menzionare gli esempi hardcoded (`openrouter/free`, dual-key Google) come se fossero preconfigurati.

---

## F. `README.md` — aggiornare il blurb su `.env`

Riga con `# Inserisci le tue API key in .env (OPENROUTER_API_KEY o DEEPSEEK_API_KEY)`: questa frase presume ancora le due scorciatoie rimosse. Sostituire con qualcosa che rifletta il nuovo flusso, es.:
```
# Le chiavi che inserirai qui devono corrispondere ai nomi 'env_var' che dichiari
# in config/general.yaml sotto 'credentials:' (vedi docs/CONFIGURATION_REFERENCE.md)
```

---

## G. Suite di test — strategia per non rompere ~9 file esistenti

**Analisi già fatta**: numerosi test esistenti (`tests/test_free_tier_guard.py`, `test_llm_router.py`, `test_llm_timeout_retry.py`, `test_reasoning_required_retry.py`, `test_monitor_ux_and_abort.py`, `test_pricing_sync.py`, `test_telemetry.py`, tra gli altri) costruiscono `RouteConfig(credential="openrouter", ...)` o route con `provider="deepseek"/"google"` senza specificare `credential`, assumendo che le scorciatoie built-in le rendano valide. Riscrivere individualmente ognuno di questi test è inutile lavoro ripetitivo estraneo allo scopo di quei test (che verificano altro: retry, routing, telemetria, ecc.), non la gestione delle credenziali.

**Soluzione**: creare `tests/conftest.py` (non esiste ancora) con una fixture di sessione che ri-registra, **solo nella suite di test**, esattamente le stesse credenziali che oggi sono built-in in produzione:
```python
"""
tests/conftest.py
Fixture condivise per l'intera suite di test.
"""
import pytest
from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRef


@pytest.fixture(autouse=True, scope="session")
def _register_standard_test_credentials():
    """Molti test esistenti costruiscono route con credential='openrouter'/'deepseek'/
    'google_1'/'google_2' assumendo che siano risolvibili, comportamento che prima di
    questo task era garantito da un default hardcoded in produzione (rt/llm/credentials.py).
    Quel default è stato rimosso deliberatamente (ogni provider richiede ora una
    dichiarazione esplicita 'credentials:' da parte dell'utente finale). Per non riscrivere
    decine di test che riguardano altro (retry, routing, telemetria) e non le credenziali,
    questa fixture ricrea la stessa disponibilità SOLO per la durata della suite di test,
    mai in codice di produzione."""
    for ref in [
        CredentialRef(name="openrouter", provider="openrouter", env_var="OPENROUTER_API_KEY"),
        CredentialRef(name="deepseek", provider="deepseek", env_var="DEEPSEEK_API_KEY"),
        CredentialRef(name="google_1", provider="google", env_var="GOOGLE_API_KEY_1"),
        CredentialRef(name="google_2", provider="google", env_var="GOOGLE_API_KEY_2"),
    ]:
        GLOBAL_CREDENTIALS.register(ref)
```
Verificare che questa fixture risolva effettivamente la maggior parte dei file elencati sopra senza ulteriori modifiche (rieseguendo la suite dopo averla aggiunta, punto I).

**Test che invece VANNO aggiornati direttamente** (non risolvibili dalla fixture, perché verificano proprio l'assenza/presenza del comportamento cambiato):
1. `tests/test_llm_config.py::test_config_defaults_and_yaml_parsing` — carica `config.example/` direttamente e oggi asserisce `job_cfg.provider in ("deepseek", "openrouter", "google")` e `isinstance(job_cfg.model, str) and len(job_cfg.model) > 0`. Con il nuovo `config.example/` questi campi sono `None` per costruzione: riscrivere le asserzioni per verificare che siano effettivamente `None` (provando che il template è un guscio vuoto), mantenendo invece le asserzioni su `reasoning_effort`/`temperature` (campi di tuning, invariati).
2. Verificare (con `grep -rn` mirato, non a intuito) se altri test asseriscono esplicitamente sul contenuto di `config.example/` o su valori specifici di provider/model provenienti da lì — se ne trovi, applica la stessa correzione.

---

## H. Nuovi test di accettazione

In un nuovo file `tests/test_empty_shell_credentials.py` (o estendendo un file esistente pertinente):
1. **Nessuna scorciatoia in produzione**: istanziare una `CredentialRegistry()` (non `GLOBAL_CREDENTIALS`, che nella suite ha già le credenziali di test registrate dalla fixture del punto G) e verificare che `validate_credential("openrouter", "openrouter")`, `validate_credential("deepseek", "deepseek")`, `validate_credential("google", "google_1")` restituiscano tutti `False`, mentre `validate_credential("mock", "mock")` resti `True`.
2. **Route vuota non crasha**: `RouteConfig(provider=None, model=None)` non solleva eccezioni; `route.is_configured` è `False`.
3. **Route a metà resta un errore**: `RouteConfig(provider="openrouter", model=None)` solleva ancora `ValueError` (comportamento preesistente, non deve essere silenziosamente tollerato).
4. **Route con provider reale ma senza credenziale registrata**: usando una `CredentialRegistry()` pulita (o mockando temporaneamente `GLOBAL_CREDENTIALS` con una istanza vuota), `RouteConfig(provider="openrouter", model="x", credential="openrouter")` solleva `ValueError` ("Credenziale ... non valida").
5. **`config.example/` si carica senza eccezioni** e produce, per ciascuno dei 4 job, `job_cfg.primary.provider is None` e `job_cfg.primary.is_configured is False`.
6. **`_job_has_configured_route`**: `True` per un job con provider/model impostati, `False` per uno con `primary=None` o `primary` non configurato.
7. **CLI**: per ciascuno dei 5 comandi, con una `tmp_path` che ha `config/` con job non configurati (provider `null`), senza `--mock`: `SystemExit(1)` con il messaggio che nomina il job mancante. Per `cmd_run`, verificare che il messaggio elenchi TUTTI i job mancanti in un colpo solo (non solo il primo), usando ad esempio 2 job configurati e 2 no.
8. **Bypass mock invariato**: con `--mock`, nessuno di questi controlli blocca l'esecuzione (riusa il pattern già presente in `test_cli_commands_proceed_when_mock_without_config_dir` di `tests/test_config_split.py`).

---

## I. Verifica finale

1. Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) **prima** di considerare il task concluso. Per qualunque test che fallisce oltre a quelli già identificati al punto G, non limitarti a correggere l'asserzione: leggi il codice reale e capisci se il test si appoggiava a un'altra sfumatura della stessa scorciatoia rimossa (stesso principio già applicato nei task precedenti di questa sessione).
2. Verificare con `grep -rn "google_1\|google_2\|OPENROUTER_API_KEY\|DEEPSEEK_API_KEY" config.example/` che non restino riferimenti a provider specifici nei file di esempio per-job (devono avere solo `null`).
3. Verificare manualmente che caricare `config.example/` con `_load_config_dir` non sollevi eccezioni (comando singolo, come già fatto per i task precedenti).
