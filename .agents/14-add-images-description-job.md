# Task 14 — `rt add-images`: job LLM di descrizione immagine (vision)

Secondo di 5 task sequenziali (13→17). **Richiede che il Task 13 sia già completato**
(usa `rt/core/image_extract.py` e `rt/pipeline/add_images.py` che quel task crea — se non
esistono ancora, fermati e segnala che la precondizione non è soddisfatta). Non eseguire in
parallelo con gli altri task di questa serie.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Contesto

Questo task aggiunge la prima chiamata LLM della feature: per ogni immagine nuova (non ancora
in `descriptions.json`, vedi Task 13), un'unica chiamata a un modello con capacità vision che
genera una descrizione strutturata. Lo script di riferimento
`/Users/attilioturco/comandi-personali/analisi_immagini.py` fa qualcosa di simile ma con
`requests` grezzo e uno schema imposto solo dal prompt (regex per estrarre il JSON, nessuna
validazione) — leggilo (righe ~68-198) per lo schema campi e il formato del payload vision,
ma qui va implementato usando l'infrastruttura di RT già esistente
(`rt/llm/client.py::LLMClient.call_structured`, che valida con Pydantic e ha già un
meccanismo di auto-repair), non re-implementando da zero il parsing regex del riferimento.

**Decisione di design importante, presa con l'utente**: esistono DUE varianti del prompt di
descrizione, scelte in base alla sorgente dell'immagine:
- **Sorgente curata** (`source_label` che inizia per `"pdf:"` o `"folder:"`, dal Task 13):
  l'utente ha scelto/fotografato personalmente questa immagine, quindi è per costruzione
  pertinente alla lezione. Il prompt include il contesto (materia, titolo lezione) — produce
  descrizioni più ricche e accurate (il contesto aiuta a disambiguare diagrammi/strutture
  ambigue).
- **Sorgente web** (`source_label` che inizia per `"websearch:"` — verrà popolata dal Task
  17, ma la funzione va scritta ORA per accettarla): NON è curata (una ricerca web può
  restituire risultati fuori tema). Dare lo stesso contesto forte rischierebbe di far
  allucinare il modello, forzando una connessione inesistente (es. descrivere una barca come
  "una cellula tumorale nel flusso sanguigno" solo perché gli è stato detto che l'ambito è
  oncologico). Per queste, IL PROMPT NON DEVE CONTENERE ALCUN CONTESTO sulla lezione — solo
  l'istruzione di descrivere esattamente e unicamente ciò che è visibile, senza assumere
  alcuna pertinenza tematica. Questo permette anche di filtrare la rilevanza "gratis" più
  avanti (Task 15): un'immagine web davvero non pertinente riceve una descrizione onesta e
  neutra, che il job giudice semplicemente non assegnerà a nessuna macro-sezione.

## Parte 1 — Nuovo job di routing `image_description`

In `rt/core/config.py`, dentro `_build_default_jobs()`: leggi come sono definiti gli altri job
tramite `empty_shell(...)` (stesso file) e aggiungi un job `image_description` con
`max_tokens`/`timeout_seconds` adeguati a una singola risposta JSON breve per immagine (es.
`max_tokens=2048`, `timeout_seconds=120` — valori ragionevoli, non critici).

Crea `config.example/rt/image_description.yaml` con la stessa identica struttura shell degli
altri file in `config.example/rt/` (es. `config.example/rt/outline.yaml` — leggilo e ricalcalo
esattamente, `provider`/`model`/`credential` a `null`, gli altri campi con default sensati).

Nel commento/descrizione del campo `provider` in `RouteConfig` (`rt/core/config.py`, NON
modificare lo schema, solo capirlo) nota che i provider vision-capable sono un sottoinsieme
di quelli supportati (`openrouter` con modelli multimodali, `google`/Gemini, `openai_compatible`
con un endpoint vision) — `deepseek` testuale non supporta vision. Aggiungi una nota su questo
in `docs/CONFIGURATION_REFERENCE.md` vicino alla documentazione del nuovo job (quale
provider/modello scegliere per `image_description`).

## Parte 2 — Estensione di `call_structured` per contenuto immagine

In `rt/llm/client.py::LLMClient.call_structured`: oggi costruisce sempre
`messages = [{"role":"system","content": full_system}, ...history..., {"role":"user","content": prompt}]`
con `content` sempre stringa semplice (righe ~264-267, leggile per il contesto esatto prima di
modificare). Nessun provider (`rt/llm/providers/*.py`) fa assunzioni sul tipo di `content` a
livello di trasporto — passa dritto a `json.dumps`, quindi estendere il tipo è sicuro e non
rompe nulla di esistente.

Aggiungi un parametro opzionale `image_data_url: Optional[str] = None` alla firma di
`call_structured` (dopo `history`). Quando presente, il messaggio utente finale (quello con
`prompt`) va costruito in forma multi-block invece che stringa semplice:
```python
if image_data_url:
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ],
    })
else:
    messages.append({"role": "user", "content": prompt})
```
(sostituisce l'attuale `messages.append({"role": "user", "content": prompt})` incondizionato).
Con `image_data_url=None` (tutti i chiamanti esistenti, invariati) il comportamento resta
IDENTICO byte-per-byte a oggi. Aggiorna anche la stima approssimativa dei token in ingresso
(usata dal monitor, vicino alla costruzione dei messaggi) per non contare il payload immagine
come se fosse testo (o semplicemente ignoralo nella stima, è solo una stima indicativa).

## Parte 3 — Modello Pydantic e prompt

In `rt/llm/prompts.py`, segui la convenzione esatta già usata nel file (una classe Pydantic
del risultato, poi `<JOB>_SYSTEM_PROMPT`, poi `build_<job>_user_prompt(...)` — guarda
`RecallEvalMirataResult`/`RECALL_EVAL_MIRATA_SYSTEM_PROMPT`/`build_recall_eval_mirata_user_prompt`
come esempio diretto da imitare):

```python
class ImageDescription(BaseModel):
    slide_title: str = Field(..., description="Titolo principale della slide/immagine, o 'N/A' se assente")
    ocr_text: str = Field(default="", description="Testo leggibile trascritto fedelmente dall'immagine")
    visual_elements: List[Dict[str, str]] = Field(default_factory=list, description="Lista di {type, description} per ogni elemento visivo (diagramma, grafico, foto, tabella, schema, altro)")
    summary_keywords: List[str] = Field(default_factory=list, description="3-6 parole chiave del contenuto")
    alt_text: str = Field(..., description="Descrizione sintetica in una frase, pronta per l'attributo alt del markdown")


IMAGE_DESCRIPTION_SYSTEM_PROMPT = """Sei un assistente specializzato nell'analisi di slide e immagini didattiche universitarie.
Analizza l'immagine fornita e restituisci una descrizione strutturata accurata e fedele di ciò che è effettivamente visibile."""

IMAGE_DESCRIPTION_SYSTEM_PROMPT_NO_CONTEXT = IMAGE_DESCRIPTION_SYSTEM_PROMPT + """

IMPORTANTE: questa immagine proviene da una ricerca web automatica e potrebbe NON essere
pertinente all'argomento di alcuna lezione. Descrivi ESCLUSIVAMENTE ciò che è oggettivamente
visibile nell'immagine, senza assumere o inventare alcuna pertinenza tematica, medica o
accademica. Se l'immagine è generica o non correlata a un contesto didattico, descrivila
comunque in modo neutro e letterale."""


def build_image_description_user_prompt(context: Optional[str] = None) -> str:
    header = f"Contesto della lezione: {context}\n\n" if context else ""
    return f"""{header}Analizza l'immagine allegata e genera l'oggetto JSON conforme allo schema ImageDescription
(slide_title, ocr_text, visual_elements, summary_keywords, alt_text)."""
```
Adatta i dettagli minori (wording) mantenendo lo stile italiano del resto del file. Nota che
`context` (quando fornito) deve derivare da materia+titolo lezione — verifica come queste
informazioni sono già recuperate altrove nel progetto (es. `info.yaml` via `read_info_yaml`,
già usato ovunque nella pipeline) invece di re-inventare l'accesso.

## Parte 4 — Wiring in `rt/pipeline/add_images.py`

Aggiungi una funzione che, per ogni immagine nuova (dall'output di
`partition_new_vs_cached_images` del Task 13), la descrive e salva il risultato:
```python
def describe_new_images(lesson_dir: str, new_images, lesson_context: Optional[str], force_mock: bool = False) -> None:
    """new_images: lista di (ExtractedImage, hash) dal Task 13. Per ciascuna, converte
    image_bytes in un data URL base64 (mime type PNG o quello reale dell'immagine — deducilo
    dall'estensione/contenuto), sceglie il prompt con o senza contesto in base a
    img.source_label (curata: 'pdf:'/'folder:' -> WITH context; 'websearch:' -> NO context,
    vedi Parte 3), chiama LLMClient().call_structured(..., image_data_url=..., response_model=ImageDescription,
    job_name='image_description'), salva l'immagine grezza con save_raw_image() e la entry
    risultante in descriptions.json (load_image_descriptions + aggiorna + save_image_descriptions)."""
```
Determina il formato del data URL: `f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"`
(assumi PNG per le pagine PDF; per le foto da cartella deduci il mime type dall'estensione del
file originale, es. `.jpg`→`image/jpeg`).

## Test

Aggiungi test per: `call_structured` con `image_data_url` costruisce il messaggio multi-block
atteso (mocka il provider HTTP per catturare il payload); senza `image_data_url` il
comportamento resta identico a prima (nessuna regressione); `build_image_description_user_prompt`
con e senza `context`; `describe_new_images` (mock del client LLM) sceglie il prompt giusto in
base al prefisso di `source_label` e salva correttamente in `descriptions.json`. Esegui
`python3 -m pytest tests/ -q` e correggi eventuali fallimenti tu stesso prima di considerare il
task concluso.

## Attenzione — bug di portabilità ricorrente in questo progetto

Più round di task precedenti hanno usato `Optional[...]`/`List[...]`/`Dict[...]` come
annotazione di tipo senza il corrispondente `from typing import ...` in cima al file — funziona
per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo differito di
default, PEP 649) ma darebbe `NameError` su Python <3.14. Verifica sempre che ogni nome da
`typing` che usi sia importato esplicitamente nel file che lo usa.
