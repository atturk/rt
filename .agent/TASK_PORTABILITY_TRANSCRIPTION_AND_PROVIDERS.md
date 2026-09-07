Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Portabilità per altri utenti — motori di trascrizione alternativi (solo docs) + provider LLM generico configurabile (codice)

## Contesto

In vista della distribuzione del progetto ad altri utenti (prima di iniziare il lavoro su RT 3.0), sono stati verificati due presunti "vincoli rigidi" del progetto: uno si è rivelato già risolto architetturalmente (serve solo documentarlo), l'altro è un vincolo reale che richiede un intervento di codice contenuto e ben isolato.

---

## A. Trascrizione con motori diversi da MacWhisper (SOLO documentazione, nessun codice)

### Cosa è stato verificato
- `rt/core/segments.py`, funzione `parse_segments_from_json`: accetta già 3 formati in ingresso, incluso un "Caso 3" (righe 98-100) che accetta un JSON **già nel formato interno esatto** (`id`, `index`, `start_seconds`, `end_seconds`, `start_formatted`, `end_formatted`, `text_raw`, opzionali `source_file`/`speaker`/`confidence`), senza alcuna conversione.
- `rt/pipeline/prepare.py`, `run_prepare`: cerca semplicemente uno tra 3 nomi file (`trascritto grezzo.json`, `segments_raw.json`, `transcript.json`) nella cartella lezione — non verifica mai chi/cosa ha prodotto il file.
- `rt setup --skip-transcribe <audio>` esiste già: crea la cartella lezione (con `info.yaml`, copia del file audio) senza mai invocare MacWhisper.

Un utente senza MacWhisper può quindi già oggi: trascrivere con il motore che preferisce (Whisper locale, Deepgram, GPT-transcribe, Voxtral, ecc.) → convertire l'output nel formato "Caso 3" → lanciare `rt setup --skip-transcribe <audio>` → salvare il file convertito come `trascritto grezzo.json` nella cartella creata → `rt prepare`. **Nessuna nuova funzionalità nativa per motori specifici va costruita** — sarebbe un onere di manutenzione continuo senza beneficio reale (formati di terzi che cambiano nel tempo).

### Fix: documentare questo flusso
Creare `docs/ALTERNATIVE_TRANSCRIPTION.md` con:
1. Spiegazione del principio: RT non è legato a MacWhisper, è legato solo al formato `segments.json` interno.
2. I 3 formati accettati da `parse_segments_from_json` con un esempio JSON minimo per ciascuno (in particolare il formato "Caso 3", il più semplice per chi scrive un proprio convertitore).
3. Procedura passo-passo:
   ```bash
   rt setup --skip-transcribe "percorso/audio.m4a" -d "..." -m "..." -a "..."
   # -> crea la cartella lezione con info.yaml e copia dell'audio
   # A questo punto: converti l'output del tuo motore STT nel formato Caso 3
   # e salvalo come "trascritto grezzo.json" dentro la cartella appena creata
   rt prepare "cartella_lezione"
   ```
4. Nota sui campi minimi obbligatori per ogni segmento nel formato Caso 3 (con esempio concreto di 2 segmenti).

Aggiungere un riferimento a questo nuovo file nella sezione "Documentazione Dettagliata" di `README.md` (accanto agli altri link a `docs/*.md`).

---

## B. Provider LLM generico "openai_compatible" configurabile da YAML (codice)

### Cosa è stato verificato
- `rt/llm/providers/__init__.py`: `_PROVIDERS` contiene solo 3 classi hardcoded (`deepseek`, `openrouter`, `google`).
- `rt/core/config.py`, `RouteConfig.model_post_init`: `allowed_providers = {"deepseek", "openrouter", "google"}` — qualunque altro valore solleva `ValueError`.
- `rt/llm/credentials.py`, `CredentialRegistry`: **è già progettato per essere estensibile** — il metodo pubblico `register(ref: CredentialRef, ...)` (riga 55) permette di aggiungere nuove credenziali a runtime; `get_api_key`/`validate_credential`/`sanitize_secrets` operano già genericamente sul registry, non hardcoded per nome. Manca solo un modo per un UTENTE di dichiarare nuove credenziali da `rt.config.yaml` senza scrivere Python.
- Le 3 chiamate API esistenti (DeepSeek, OpenRouter, Google) sono tutte, sotto sotto, nel formato "OpenAI Chat Completions" (`messages` in ingresso, `choices[].message.content`/`choices[].delta.content` in uscita). Le API ufficiali di **Mistral e OpenAI** usano lo stesso formato. **Claude/Anthropic nativo NO** (header di autenticazione diverso, envelope di risposta diverso) — non rientra in questo intervento; chi vuole Claude può già usarlo tramite OpenRouter (già supportato).

### Fix 1: nuovo provider generico `rt/llm/providers/openai_compatible.py`
```python
"""
rt.llm.providers.openai_compatible
Adapter generico per qualunque endpoint compatibile con l'API OpenAI Chat Completions
(es. Mistral AI ufficiale, OpenAI ufficiale, Groq, Together.ai, server locali vLLM/Ollama/LM Studio).
Nessuna estensione proprietaria di vendor: niente campi 'thinking'/'reasoning' (specifici di DeepSeek/OpenRouter).
"""

import json
from typing import Optional, Dict, Any, List
from rt.llm.providers.base import BaseLLMProvider, NormalizedResponse, StreamChunk


class OpenAICompatibleProvider(BaseLLMProvider):
    @property
    def name(self) -> str:
        return "openai_compatible"

    def get_endpoint(self, base_url: Optional[str] = None) -> str:
        if not base_url:
            raise ValueError(
                "Il provider 'openai_compatible' richiede un 'base_url' esplicito in rt.config.yaml "
                "(non esiste un endpoint di default per questo tipo di provider)."
            )
        base = base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def get_headers(self, api_key: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
        }

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
        max_thinking_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        # 'thinking'/'reasoning_effort'/'max_thinking_tokens' sono ignorati volutamente:
        # non fanno parte della Chat Completions API standard OpenAI.
        payload: Dict[str, Any] = {
            "model": model.strip(),
            "messages": messages,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if response_format:
            payload["response_format"] = response_format
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    def parse_stream_line(self, line: str) -> Optional[StreamChunk]:
        clean_line = line.strip()
        if not clean_line or not clean_line.startswith("data:"):
            return None
        raw_data = clean_line[5:].strip()
        if raw_data == "[DONE]":
            return None
        try:
            chunk_dict = json.loads(raw_data)
        except json.JSONDecodeError:
            return None

        content_delta = None
        finish_reason = None
        req_id = chunk_dict.get("id")
        usage = chunk_dict.get("usage")

        choices = chunk_dict.get("choices", [])
        if choices:
            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            delta = choice.get("delta", {})
            content_delta = delta.get("content")

        return StreamChunk(
            content_delta=content_delta,
            reasoning_delta=None,
            usage=usage,
            finish_reason=finish_reason,
            request_id=req_id,
            resolved_model=chunk_dict.get("model")
        )

    def normalize_response(
        self,
        raw_json: Dict[str, Any],
        model_name: str,
        request_id: Optional[str] = None
    ) -> NormalizedResponse:
        choices = raw_json.get("choices", [])
        content = ""
        finish_reason = None
        if choices:
            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            content = choice.get("message", {}).get("content") or ""

        return NormalizedResponse(
            content=content,
            reasoning=None,
            usage=raw_json.get("usage"),
            finish_reason=finish_reason,
            provider=self.name,
            model=model_name,
            resolved_model=raw_json.get("model"),
            request_id=request_id or raw_json.get("id")
        )
```

Registrare in `rt/llm/providers/__init__.py`:
```python
from rt.llm.providers.openai_compatible import OpenAICompatibleProvider

_PROVIDERS: Dict[str, Type[BaseLLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
    "google": GoogleProvider,
    "openai_compatible": OpenAICompatibleProvider,
}
```

### Fix 2: `rt/core/config.py` — accettare il nuovo provider e richiedere `base_url` obbligatorio per esso
In `RouteConfig.model_post_init` (righe ~48-55):
```python
allowed_providers = {"deepseek", "openrouter", "google", "openai_compatible"}
if clean_p not in allowed_providers:
    raise ValueError(f"Provider LLM non supportato: '{self.provider}'. Provider ammessi: {sorted(allowed_providers)}")
if not self.model or not str(self.model).strip():
    raise ValueError(f"Il modello per il provider '{self.provider}' non può essere vuoto.")
if clean_p == "openai_compatible" and not self.base_url:
    raise ValueError(
        "Il provider 'openai_compatible' richiede 'base_url' esplicito nella route "
        "(non esiste un endpoint di default per questo tipo di provider)."
    )
```
**Non aggiungere** una entry per `openai_compatible` in `KNOWN_PROVIDER_DEFAULT_BASE_URLS` — quel dizionario serve solo a rilevare mismatch di copia-incolla tra i 3 provider con endpoint fisso noto; per `openai_compatible` l'utente specifica sempre un URL arbitrario, non c'è nulla da controllare lì.

### Fix 3: credenziali custom dichiarabili da YAML
In `rt/core/config.py`, estendere il `model_validator(mode="before")` esistente `normalize_llm_and_jobs_config` (che già gira PRIMA che le singole `RouteConfig` vengano costruite/validate, garantendo l'ordine corretto), aggiungendo in testa:
```python
@model_validator(mode="before")
@classmethod
def normalize_llm_and_jobs_config(cls, data: Any) -> Any:
    if not isinstance(data, dict):
        return data

    # 0. Registrazione delle credenziali custom dichiarate in YAML (es. per 'openai_compatible'),
    #    PRIMA che le RouteConfig vengano validate più sotto (altrimenti la validazione fallirebbe
    #    perché il nome della credenziale non sarebbe ancora noto al registry).
    raw_credentials = data.get("credentials")
    if isinstance(raw_credentials, list):
        from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRef
        for entry in raw_credentials:
            if isinstance(entry, dict):
                cred_name = entry.get("name")
                cred_provider = entry.get("provider")
                cred_env_var = entry.get("env_var")
                if cred_name and cred_provider and cred_env_var:
                    GLOBAL_CREDENTIALS.register(CredentialRef(name=cred_name, provider=cred_provider, env_var=cred_env_var))

    # 1. Estrazione retry da llm.retry se collocato lì in configurazioni legacy
    ... (resto della funzione INVARIATO)
```
Non serve aggiungere un campo `credentials`/`custom_credentials` a `RTConfig` stesso: la chiave `credentials:` nel YAML grezzo viene letta e consumata qui, prima della validazione — se `RTConfig` non dichiara quel campo, Pydantic la ignora silenziosamente nel resto della validazione (comportamento di default, nessun errore "campo sconosciuto").

### Fix 4: generalizzare il messaggio di errore in `rt/llm/client.py` (rimuovere l'ultimo hardcoding per-provider)
In `rt/llm/credentials.py`, aggiungere un metodo pubblico a `CredentialRegistry`:
```python
def get_env_var_name(self, credential_name: str) -> Optional[str]:
    """Restituisce il nome della variabile d'ambiente associata a una credenziale registrata, se esiste."""
    ref = self._credentials.get(credential_name.lower().strip())
    return ref.env_var if ref else None
```
In `rt/llm/client.py`, righe 242-246, sostituire:
```python
env_var = "OPENROUTER_API_KEY" if provider_name == "openrouter" else (
    "GOOGLE_API_KEY_1" if credential_ref == "google_1" else (
        "GOOGLE_API_KEY_2" if credential_ref == "google_2" else f"{provider_name.upper()}_API_KEY"
    )
)
```
con:
```python
env_var = GLOBAL_CREDENTIALS.get_env_var_name(credential_ref) or f"{provider_name.upper()}_API_KEY"
```
(Nota: questo è puramente il testo del messaggio d'errore quando manca una API key — verificato che non incide sulla logica di lookup effettiva, già gestita interamente da `GLOBAL_CREDENTIALS.get_api_key()`.)

### Fix 5: documentazione ed esempio
In `rt.config.yaml.example`, aggiungere un blocco commentato (non attivo di default, per non alterare il comportamento per chi usa già openrouter/deepseek/google) che mostra come aggiungere un provider custom, es.:
```yaml
# Esempio: aggiungere un provider generico OpenAI-compatible (es. Mistral AI ufficiale).
# Decommentare e adattare per usarlo in un job (provider: "openai_compatible").
# credentials:
#   - name: "mistral_official"
#     provider: "openai_compatible"
#     env_var: "MISTRAL_API_KEY"
#
# jobs:
#   outline:
#     primary:
#       provider: "openai_compatible"
#       credential: "mistral_official"
#       model: "mistral-large-latest"
#       base_url: "https://api.mistral.ai/v1"
#       thinking: false
#       timeout_seconds: 180
```
Aggiornare `docs/ARCHITECTURE.md`, sezione 4 (LLM Routing Engine), con una riga che menzioni il provider `openai_compatible` come punto di estensione per provider aggiuntivi compatibili con l'API OpenAI Chat Completions, e la possibilità di dichiarare credenziali custom via la chiave `credentials:` in `rt.config.yaml`.

---

## Edge case e invarianti da rispettare

1. **Nessun impatto sui 3 provider esistenti**: `deepseek`, `openrouter`, `google` devono continuare a funzionare esattamente come oggi, nessuna modifica al loro comportamento o ai relativi test.
2. **`base_url` obbligatorio solo per `openai_compatible`**: gli altri 3 provider continuano ad avere il loro comportamento di default (base_url opzionale/implicito) invariato.
3. **Ordine di registrazione delle credenziali custom**: deve avvenire PRIMA che qualunque `RouteConfig` che le referenzia venga costruita/validata nello stesso caricamento di config — verificato che il punto di aggancio scelto (inizio del `model_validator(mode="before")` esistente) rispetti questo vincolo.
4. **Nessuna nuova dipendenza esterna**: il nuovo provider usa solo `requests`/`json`, già presenti.
5. **`GLOBAL_CREDENTIALS` è un singleton globale condiviso**: la registrazione di una credenziale custom in un test non deve "sporcare" altri test — nei test aggiunti, usare nomi di credenziali chiaramente identificabili come test (es. `test_openai_compat_cred`) per evitare collisioni con nomi reali, e considerare che il registro persiste tra i test nello stesso processo pytest (stesso pattern già presente in altri test della suite che chiamano `GLOBAL_CREDENTIALS.register`/`reload_from_env`).

## Test di accettazione (`pytest tests/`)

In un nuovo file `tests/test_openai_compatible_provider.py`:
1. `OpenAICompatibleProvider.build_payload(...)` produce un payload che NON contiene mai le chiavi `thinking`/`reasoning`/`reasoning_effort`, e contiene correttamente `model`/`messages`/`stream`/eventuali `max_tokens`/`temperature`/`response_format`.
2. `OpenAICompatibleProvider.get_endpoint(None)` solleva `ValueError` con messaggio chiaro; `get_endpoint("https://api.mistral.ai/v1")` restituisce `"https://api.mistral.ai/v1/chat/completions"`.
3. `RouteConfig(provider="openai_compatible", model="mistral-large-latest")` (senza `base_url`) solleva `ValueError`; con `base_url="https://api.mistral.ai/v1"` e una credenziale precedentemente registrata via `GLOBAL_CREDENTIALS.register(...)`, la costruzione riesce.
4. Test end-to-end: registrare una credenziale custom (`GLOBAL_CREDENTIALS.register(CredentialRef(name="test_openai_compat_cred", provider="openai_compatible", env_var="TEST_OPENAI_COMPAT_KEY"))`), impostare `monkeypatch.setenv("TEST_OPENAI_COMPAT_KEY", ...)`, configurare un job con quella route, e verificare che `LLMClient.call_structured` con `requests.post` mockato produca la URL/headers/payload attesi e restituisca un risultato valido.
5. Test che una config YAML (scritta su `tmp_path`) con una sezione `credentials:` E un job che referenzia quella credenziale venga caricata correttamente da `load_config(path)` senza sollevare eccezioni (verifica diretta dell'ordine di registrazione corretto).
6. Test per `GLOBAL_CREDENTIALS.get_env_var_name(...)`: restituisce il nome corretto per una credenziale nota (es. `"deepseek"` → `"DEEPSEEK_API_KEY"`) e `None` per una sconosciuta.
7. Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e confermare zero regressioni sui test esistenti (172 attuali + i nuovi).

## Verifica finale
Rieseguire `python3 -m pytest tests/ -q` e confermare l'esito. Assicurarsi che la CI (`.github/workflows/tests.yml`, già presente) passi su entrambe le versioni Python della matrice per il commit di questo task.
