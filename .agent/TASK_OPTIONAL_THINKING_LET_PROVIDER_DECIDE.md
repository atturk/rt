Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: `thinking` opzionale (a tre stati) — mai forzare `reasoning.enabled: false` su OpenRouter

## Contesto

L'utente ha già reso `reasoning_effort` opzionale (nullable, "lascia decidere al provider quale sforzo usare"). Ha chiesto di verificare se lo stesso si può fare per `thinking` (oggi `bool` obbligatorio, default `True`, sempre forzato esplicitamente a `true`/`false` in ogni chiamata). Ho verificato con ricerca reale (non per ipotesi) e la risposta non è solo "sì, possiamo": **oggi il codice ha un rischio concreto**.

**Evidenza trovata**: `reasoning: {"enabled": false}` su OpenRouter causa un **errore HTTP 400 esplicito** ("Reasoning is mandatory for this endpoint and cannot be disabled") sui modelli con reasoning obbligatorio — confermato per **DeepSeek V3.1 Terminus su OpenRouter**, la stessa famiglia usata oggi per review scientifica. Il pattern di fix adottato da progetti reali che hanno incontrato lo stesso problema (es. claude-code-router) è sempre lo stesso: **se non si vuole forzare il reasoning, si omette del tutto la chiave `reasoning` dal payload**, mai mandare `enabled: false` esplicito — così OpenRouter usa il comportamento nativo del modello, che può essere "sempre acceso, non disattivabile" senza che questo generi un errore.

**Decisione presa**: `thinking` diventa un campo a **tre stati** (`Optional[bool]`, default `None`):
- `None` → non tocchiamo la dimensione "thinking" per questa chiamata: **nessuna chiave relativa inviata**, il provider/modello usa il proprio comportamento nativo.
- `True` → forziamo esplicitamente il reasoning acceso (comportamento identico a oggi quando `thinking=True`).
- `False` → l'utente vuole disattivarlo esplicitamente. **Per OpenRouter, per la ragione sopra, il modo sicuro di "provarci" è comunque omettere la chiave `reasoning`** (mai `enabled: false`) — quindi su OpenRouter `False` e `None` producono lo stesso payload sul campo `reasoning`. Per DeepSeek diretto, invece, la loro API supporta esplicitamente `{"type": "disabled"}` senza il problema riscontrato su OpenRouter (verificato dalla documentazione ufficiale DeepSeek): lì `False` continua a mandare `{"type": "disabled"}` come oggi.

**Fuori scope**: non modificare `config.example/*.yaml`. I template continuano a impostare `thinking: true`/`false` esplicito per ciascun job (sono scelte di tuning deliberate, es. `review_asr.yaml` ha `thinking: false` perché il rilevamento errori fonetici non beneficia di reasoning esteso) — questa funzionalità è per chi, nel proprio `config/` reale, vuole esplicitamente lasciar decidere al modello.

---

## A. `rt/core/config.py`

In `RouteConfig` (riga 39):
```python
thinking: Optional[bool] = Field(default=None, description="True = forza il reasoning acceso, False = tenta di disattivarlo (su OpenRouter, per sicurezza, produce comunque l'omissione del campo — vedi rt/llm/providers/openrouter.py), None = non specificato, il provider/modello decide da sé")
```

---

## B. `rt/llm/client.py` — preservare la distinzione a 3 stati nel punto di chiamata

Riga 374, oggi:
```python
thinking=(route.thinking or force_thinking_override),
```
Questo collassa già oggi `None` e `False` nello stesso risultato "falsy" (bug preesistente, invisibile finché `thinking` era sempre `bool`). Va sostituito con una forma che preservi i 3 stati e mantenga intatta la semantica di `force_thinking_override` (escalation automatica dopo risposte sospette/a basso sforzo, vedi righe 995-1007: quando l'escalation scatta, il reasoning DEVE essere forzato acceso a prescindere da cosa dice la route):
```python
thinking=(True if force_thinking_override else route.thinking),
```

---

## C. Firme dei provider adapter

In `rt/llm/providers/base.py` (firma astratta), `rt/llm/providers/openrouter.py`, `rt/llm/providers/deepseek.py`, `rt/llm/providers/google.py`, `rt/llm/providers/openai_compatible.py`: cambiare in tutti e 5 i punti
```python
thinking: bool = True,
```
in
```python
thinking: Optional[bool] = None,
```
(Solo la firma. Per `google.py` e `openai_compatible.py` il corpo resta invariato: nessuno dei due usa mai `thinking` nella costruzione del payload — `google.py` non ha mai inviato nulla di relativo al reasoning, `openai_compatible.py` lo ignora deliberatamente già oggi, commento esistente da mantenere.)

---

## D. `rt/llm/providers/openrouter.py` — corpo con branch a 3 stati

Sostituire il blocco attuale:
```python
if thinking:
    if max_thinking_tokens is not None and max_thinking_tokens > 0:
        payload["reasoning"] = {"max_tokens": int(max_thinking_tokens)}
    elif reasoning_effort and str(reasoning_effort).strip():
        payload["reasoning"] = {"enabled": True, "effort": str(reasoning_effort).lower().strip()}
    else:
        payload["reasoning"] = {"enabled": True}
else:
    payload["reasoning"] = {"enabled": False}
```
con:
```python
if thinking is True:
    if max_thinking_tokens is not None and max_thinking_tokens > 0:
        payload["reasoning"] = {"max_tokens": int(max_thinking_tokens)}
    elif reasoning_effort and str(reasoning_effort).strip():
        payload["reasoning"] = {"enabled": True, "effort": str(reasoning_effort).lower().strip()}
    else:
        payload["reasoning"] = {"enabled": True}
# thinking is False o None: non includere affatto la chiave 'reasoning'. Non mandare mai
# {"enabled": False} esplicito: alcuni modelli con reasoning obbligatorio (es. DeepSeek V3.1
# Terminus su OpenRouter, confermato) rispondono con HTTP 400 "Reasoning is mandatory for this
# endpoint and cannot be disabled". Omettere la chiave lascia decidere il comportamento nativo
# del modello, che è l'unico modo sicuro di "non forzare" il reasoning su OpenRouter.
```
(Rimuovere interamente il vecchio `else: payload["reasoning"] = {"enabled": False}` — non deve più esistere un ramo che produce `enabled: false`.)

Non toccare la gestione di `max_thinking_tokens`/`reasoning_effort` quando `thinking is True`: comportamento invariato.

---

## E. `rt/llm/providers/deepseek.py` — corpo con branch a 3 stati

Sostituire il blocco attuale:
```python
caps = get_capabilities(self.name, thinking_mode=thinking)
if thinking:
    payload["thinking"] = {"type": "enabled"}
    if reasoning_effort and str(reasoning_effort).strip():
        payload["reasoning_effort"] = str(reasoning_effort).lower().strip()
else:
    payload["thinking"] = {"type": "disabled"}

if temperature is not None and caps.supports_temperature:
    payload["temperature"] = temperature
```
con:
```python
caps = get_capabilities(self.name, thinking_mode=bool(thinking))
if thinking is True:
    payload["thinking"] = {"type": "enabled"}
    if reasoning_effort and str(reasoning_effort).strip():
        payload["reasoning_effort"] = str(reasoning_effort).lower().strip()
elif thinking is False:
    payload["thinking"] = {"type": "disabled"}
# thinking is None: non includere affatto la chiave 'thinking' né 'reasoning_effort'. La
# documentazione ufficiale DeepSeek conferma che il thinking mode è comunque enabled di
# default lato loro, quindi omettere è coerente col comportamento nativo, non un downgrade.
# A differenza di OpenRouter, l'API diretta DeepSeek non risulta avere il problema del punto D
# con {"type": "disabled"} esplicito: per questo qui il ramo False resta invariato.

if temperature is not None and caps.supports_temperature:
    payload["temperature"] = temperature
```
Nota: `get_capabilities(self.name, thinking_mode=bool(thinking))` — `bool(None)` è `False`, quindi con `thinking=None` le capabilities vengono calcolate come se il thinking mode fosse spento (`supports_temperature=True`), scelta corretta dato che non stiamo forzando alcuna modalità.

---

## F. Test di accettazione (`pytest tests/`)

Estendere `tests/test_llm_config.py` (o un file dedicato) con:
1. `RouteConfig(provider="openrouter", model="x")` senza specificare `thinking` → `route.thinking is None`.
2. In `rt/llm/client.py`, verificare (con una chiamata reale mockata via `requests.post`, stesso pattern già usato nei test esistenti di questo file) che la logica del punto B preservi i 3 stati:
   - `route.thinking = None`, nessuna escalation attiva → il payload finale non contiene la chiave `reasoning` (per OpenRouter) né `thinking` (per DeepSeek).
   - `route.thinking = False`, nessuna escalation attiva → stesso risultato del caso precedente (nessuna chiave `reasoning` su OpenRouter — non deve MAI comparire `{"enabled": false}`).
   - `route.thinking = False` ma `force_thinking_override = True` (simulare l'escalation, es. patchando lo stato interno o innescandola con lo stesso meccanismo già testato in `tests/test_reasoning_required_retry.py`) → il payload finale forza comunque il reasoning acceso, a conferma che l'escalation vince sempre sulla preferenza della route.
3. `OpenRouterProvider().build_payload(..., thinking=None)` e `build_payload(..., thinking=False)` → in entrambi i casi `"reasoning" not in payload`. `build_payload(..., thinking=True)` → comportamento invariato rispetto a oggi (nessuna regressione sui test già esistenti che lo verificano).
4. `DeepSeekProvider().build_payload(..., thinking=None)` → `"thinking" not in payload` e `"reasoning_effort" not in payload`. `build_payload(..., thinking=True)`/`build_payload(..., thinking=False)` → comportamento invariato rispetto a oggi.
5. Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e, per qualunque test che smette di passare, capire la causa reale prima di correggerlo (stesso principio applicato in tutti i task precedenti di questa sessione) — non limitarsi a modificare l'asserzione per farla tornare verde. In particolare, cercare con `grep -rn "RouteConfig(" tests/` ogni costruzione che NON specifica `thinking` esplicitamente e verificare se il test in questione si aspettava implicitamente il vecchio default `True`.

## Verifica finale
`python3 -m pytest tests/ -q` deve passare per intero. Verificare con `grep -rn '"enabled": False\|"enabled":False' rt/llm/providers/openrouter.py` che non resti alcun punto del codice in grado di produrre quel valore nel payload.
