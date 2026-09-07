Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Provider routing OpenRouter configurabile da YAML (whitelist/quantizzazioni/sort), mai hardcoded

## Contesto

OpenRouter espone nel body della richiesta un oggetto `"provider": {...}` che controlla a quali backend viene instradata la chiamata: `only`/`ignore` (whitelist/blacklist per slug), `quantizations` (filtra per qualità di quantizzazione, es. `["fp8","bf16","fp16"]` per escludere quantizzazioni scadenti), `sort` (`"price"` | `"throughput"` | `"latency"`, un solo criterio alla volta — OpenRouter non supporta sort concatenati su più criteri), `allow_fallbacks`, `require_parameters`, `max_price`, `preferred_min_throughput`/`preferred_max_latency`, `data_collection`, `zdr`. Riferimento: https://openrouter.ai/docs/guides/routing/provider-selection

**Decisione presa**: l'utente vuole restringere le chiamate OpenRouter a una whitelist di provider "buoni" (tps/quantizzazione decenti) invece di bandire i cattivi uno per uno, e vuole poterlo configurare/aggiornare da YAML **senza mai hardcodare nomi di provider o logica di routing in Python** — i provider disponibili e la loro qualità cambiano nel tempo, l'unico posto dove questa informazione deve vivere è la configurazione dell'utente.

**Correzione importante rispetto alla prima versione di questo task (l'utente l'ha fatta notare esplicitamente)**: i provider "buoni" **non sono una proprietà globale di OpenRouter, ma dipendono dal modello specifico** — un provider ottimo per servire DeepSeek può essere mediocre per servire GLM, e viceversa. Di conseguenza **non esiste alcun default globale**: il campo va impostato **esclusivamente per singola route**, esattamente dove si specifica già `model:`/`provider:` (`primary:`, `secondary:`, ogni voce di `fallback:`, ogni elemento di `primary_routes:`) — mai in `general.yaml`. Non introdurre nessun campo `openrouter_provider_routing` a livello di `RTConfig`, e non introdurre alcuna logica di fallback/priorità tra un default globale e uno per-route: qui non c'è un "default", c'è solo la scelta esplicita fatta insieme al modello.

**Scelta architetturale esplicita**: il nuovo campo (`provider_routing` su `RouteConfig`) è un **dizionario libero (pass-through)**, non un modello Pydantic tipizzato con i singoli campi (`only`, `sort`, ecc.) elencati esplicitamente. Motivo: lo schema dell'oggetto `provider` di OpenRouter può evolvere (nuovi campi, nuovi valori); un pass-through significa che l'utente scrive nel suo YAML esattamente quello che trova nella documentazione OpenRouter corrente, e il nostro codice lo inoltra così com'è nel body della richiesta senza doverlo conoscere/validare campo per campo. Non validare il contenuto di questo dizionario oltre al tipo (`Dict[str, Any]`): se l'utente scrive uno schema non valido secondo OpenRouter, sarà l'errore HTTP di OpenRouter stesso a dirlo (comportamento coerente con come oggi trattiamo già `pricing:`/`base_url` custom).

Si applica **solo** quando `provider == "openrouter"` per quella specifica route — per qualunque altro provider il campo, se presente (non dovrebbe esserlo, ma non è un errore se c'è), viene semplicemente ignorato.

---

## A. `rt/core/config.py` — nuovo campo, solo su `RouteConfig`

In `RouteConfig` (accanto al campo `pricing` esistente, circa riga 49):
```python
provider_routing: Optional[Dict[str, Any]] = Field(
    default=None,
    description="Oggetto 'provider' di OpenRouter (only/ignore/quantizations/sort/allow_fallbacks/...) "
                "per questa specifica route, impostato insieme a provider/model perché la scelta dei "
                "backend affidabili dipende dal modello richiesto, non è una preferenza globale. "
                "Pass-through non validato: rispecchia esattamente lo schema documentato da OpenRouter "
                "(https://openrouter.ai/docs/guides/routing/provider-selection). Ignorato per provider diversi da 'openrouter'."
)
```

**Non aggiungere nulla a `RTConfig`**: niente `openrouter_provider_routing` globale, niente in `general.yaml`. Ogni route con `provider: "openrouter"` porta con sé, opzionalmente, il proprio `provider_routing`.

---

## B. `rt/llm/client.py` — lettura diretta dalla route, nessuna risoluzione multi-livello

Aggiungere un metodo accanto a `_resolve_custom_pricing` (circa riga 94) — qui non c'è alcuna priorità da risolvere, solo un controllo sul provider:
```python
def _resolve_provider_routing(self, route: RouteConfig, provider_name: str) -> Optional[Dict[str, Any]]:
    """Restituisce l'oggetto 'provider' da inviare a OpenRouter per questa route, se impostato.
    Non esiste un default globale: la scelta dei backend affidabili dipende dal modello specifico,
    quindi vive esclusivamente sulla singola route, insieme a provider/model. Si applica solo per
    provider_name == 'openrouter'; per qualunque altro provider restituisce sempre None."""
    if provider_name != "openrouter":
        return None
    return route.provider_routing
```

Nel punto in cui viene costruito il payload (circa riga 361, `payload = provider.build_payload(...)`), aggiungere l'argomento:
```python
payload = provider.build_payload(
    model=model_name,
    messages=list(messages),
    max_tokens=route.max_tokens,
    thinking=(route.thinking or force_thinking_override),
    reasoning_effort=route.reasoning_effort,
    temperature=route.temperature,
    response_format={"type": "json_object"},
    stream=use_stream,
    max_thinking_tokens=route.max_thinking_tokens,
    provider_routing=self._resolve_provider_routing(route, provider_name)
)
```

---

## C. Provider adapters — nuovo parametro opzionale

In `rt/llm/providers/base.py`, aggiungere il parametro alla firma astratta di `build_payload` (circa riga 54-65):
```python
def build_payload(
    self,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = None,
    thinking: bool = True,
    reasoning_effort: str = "low",
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, str]] = None,
    stream: bool = True,
    max_thinking_tokens: Optional[int] = None,
    provider_routing: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
```

In `rt/llm/providers/openrouter.py`, aggiungere lo stesso parametro alla firma di `build_payload` e, se presente, iniettarlo nel payload:
```python
def build_payload(
    self,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = None,
    thinking: bool = True,
    reasoning_effort: str = "low",
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, str]] = None,
    stream: bool = True,
    max_thinking_tokens: Optional[int] = None,
    provider_routing: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    ...  # corpo esistente invariato fino al return
    if provider_routing:
        payload["provider"] = provider_routing
    return payload
```
(Aggiungere il blocco `if provider_routing:` subito prima del `return payload` finale, dopo la costruzione del campo `reasoning` già esistente.)

In `rt/llm/providers/deepseek.py`, `rt/llm/providers/google.py`, `rt/llm/providers/openai_compatible.py`: aggiungere il parametro `provider_routing: Optional[Dict[str, Any]] = None` alla firma di `build_payload` per compatibilità con la classe base, **ma ignorarlo deliberatamente** nel corpo (stesso trattamento già riservato a `thinking`/`reasoning_effort` in `openai_compatible.py` — un commento breve tipo `# 'provider_routing' è specifico di OpenRouter, non ha equivalente per questo provider` è sufficiente, non serve altro).

---

## D. `config.example/general.yaml` — nessuna modifica

Non toccare `config.example/`. `provider_routing:` è una scelta per singola route, non un default sensato da proporre nel template — chi vuole usarla la aggiunge consapevolmente nel proprio `config/<job>.yaml`, sotto la route specifica. Documentarla solo in `docs/CONFIGURATION_REFERENCE.md` (punto E).

---

## E. `docs/CONFIGURATION_REFERENCE.md` — nuova sezione

Aggiungere una sezione (dopo la sezione 4 su `rt prices-check` già esistente) che spiega:
1. Cos'è l'oggetto `provider` di OpenRouter e a cosa serve (restringere/ordinare i backend che servono un modello).
2. **Perché è solo per-route e non esiste un default globale**: quali provider siano affidabili (tps, quantizzazione) dipende dal modello specifico — un provider ottimo per DeepSeek può essere mediocre per GLM. Va quindi impostato in `provider_routing:` accanto a `provider:`/`model:`, dentro `primary:`, `secondary:` o una voce di `fallback:` — mai in `general.yaml`.
3. Esempio pratico concreto, per una singola route (whitelist + filtro quantizzazione + sort per velocità):
   ```yaml
   primary:
     provider: "openrouter"
     model: "deepseek/deepseek-v4-flash"
     provider_routing:
       only: ["nome-provider-buono-per-deepseek-1", "nome-provider-buono-per-deepseek-2"]
       quantizations: ["fp8", "bf16", "fp16"]
       sort: "throughput"
       allow_fallbacks: true
   ```
   E un esempio che mostra whitelist diversa per un modello diverso nello stesso file/job (es. un fallback su un altro modello):
   ```yaml
   fallback:
     generic:
       provider: "openrouter"
       model: "z-ai/glm-5.3"
       provider_routing:
         only: ["nome-provider-buono-per-glm-1"]
         sort: "throughput"
   ```
4. Nota importante sul tradeoff: se nessun provider della whitelist `only` serve in quel momento il modello richiesto, la chiamata fallisce con un errore HTTP invece di degradare silenziosamente a un provider fuori whitelist — è il comportamento desiderato per chi preferisce fallire chiaramente piuttosto che ottenere una quantizzazione scadente, ma va saputo.
5. Nota su `sort`: OpenRouter applica un solo criterio alla volta (`"price"` | `"throughput"` | `"latency"`), non supporta più criteri incatenati — l'effetto "prima i buoni, poi il più veloce tra questi" si ottiene componendo `only`/`quantizations` (filtro) con un singolo `sort` (ordinamento), non con un sort multi-livello.
6. Nota su come trovare gli slug dei provider: sulla pagina di ogni modello su openrouter.ai (es. `openrouter.ai/<vendor>/<modello>`) c'è un pulsante per copiare lo slug esatto di ciascun provider che lo serve — non esiste un elenco centralizzato, e non tutti i provider servono tutti i modelli (per questo la whitelist va pensata per modello, non copiata identica da una route all'altra).

---

## F. Test di accettazione (`pytest tests/`)

In `tests/test_llm_router.py` o un nuovo file dedicato (`tests/test_openrouter_provider_routing.py`):
1. `RouteConfig(provider="openrouter", model="x", provider_routing={"only": ["a"], "sort": "throughput"})` si costruisce senza errori, il campo è accessibile così com'è (nessuna validazione del contenuto).
2. Due route diverse nello stesso `JobRoutingConfig` (es. `primary` con modello DeepSeek e `fallback.generic` con modello GLM) hanno ciascuna il proprio `provider_routing` indipendente — verificare che non ci sia alcuna condivisione/contaminazione tra le due (ogni `RouteConfig` è un'istanza separata, ma vale la pena un test esplicito che lo dimostri dato che è proprio il punto di questa correzione).
3. `LLMClient._resolve_provider_routing`:
   - route con `provider_routing` impostato + provider `"openrouter"` → restituisce esattamente il dizionario della route.
   - route senza `provider_routing` → `None`.
   - provider `"deepseek"` (o qualunque non-openrouter) con `provider_routing` comunque impostato sulla route → restituisce sempre `None` (il campo è ignorato per provider diversi da openrouter).
4. `OpenRouterProvider().build_payload(..., provider_routing={"sort": "throughput"})` → il payload risultante contiene `payload["provider"] == {"sort": "throughput"}`. Con `provider_routing=None` (default) → `"provider"` non è una chiave presente nel payload (comportamento identico a oggi, nessuna regressione).
5. Un test end-to-end simile a `test_end_to_end_route_pricing_telemetry` già esistente in `tests/test_config_split.py`: costruire un `LLMClient` con una route OpenRouter che ha `provider_routing` impostato, mockare `requests.post`, eseguire una chiamata, e verificare che il body JSON effettivamente inviato (`requests.post.call_args`) contenga la chiave `"provider"` con il valore atteso.
6. Verificare che gli altri 3 provider adapter (`deepseek`, `google`, `openai_compatible`) accettino il nuovo parametro `provider_routing` senza sollevare `TypeError` e senza che il payload risultante cambi rispetto a prima di questo task (nessuna chiave `"provider"` aggiunta per loro).

## Verifica finale
`python3 -m pytest tests/ -q` deve passare per intero. Verificare inoltre che il campo `provider_routing` non compaia in nessun punto di `config.example/` (deve restare solo documentato, non nel template di default, per la decisione del punto D) e che `RTConfig` non abbia acquisito alcun nuovo campo relativo al provider routing.
