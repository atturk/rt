# Task 15 — `rt add-images`: job LLM giudice (assegna immagini alle macro-sezioni)

Terzo di 5 task sequenziali (13→17). **Richiede che i Task 13 e 14 siano già completati**
(usa `descriptions.json` popolato dal Task 14 — se `rt/pipeline/add_images.py` non ha ancora
`describe_new_images`/`load_image_descriptions`, fermati e segnala che le precondizioni non
sono soddisfatte). Non eseguire in parallelo con gli altri task di questa serie.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Contesto

Dopo il Task 14 abbiamo, per ogni immagine, una descrizione strutturata in
`assets/images/descriptions.json`. Questo task decide QUALI immagini vanno sotto QUALE
macro-sezione del documento finale. Regole esplicite dell'utente:
- Il livello di assegnazione è la **macro-sezione** (es. "3", il titolo dell'`OutlineMacro`),
  MAI le sotto-unità (es. "3.1", "3.2") — un'unica slide può coprire più punti fatti dal
  docente in sotto-unità diverse della stessa macro-sezione.
- Un'unità (macro-sezione) può avere più immagini assegnate.
- La STESSA immagine può essere assegnata a PIÙ macro-sezioni, se l'LLM lo ritiene
  appropriato — quindi NON serve (anzi va evitata) qualunque logica di esclusività globale:
  ogni macro-sezione decide in modo indipendente quali immagini le appartengono, senza sapere
  cosa hanno deciso le altre.
- Complessità N×M concettuale (N macro-sezioni, M immagini) ma **N chiamate LLM** (una per
  macro-sezione), ciascuna con l'intero set di M descrizioni passato come contesto — non M×N
  chiamate.

**Ottimizzazione cache-friendly, stesso principio già applicato con successo alla revisione
outline** (leggi `rt/pipeline/outline.py::_generate_validated_outline`/`run_outline_revision`
come precedente diretto da imitare, e `rt/llm/client.py::call_structured`'s parametro
`history` che già esiste per questo scopo esatto): dato che tutte le N chiamate per la stessa
lezione condividono lo STESSO set di descrizioni immagine, costruisci la conversazione come:
```
[system(IMAGE_UNIT_JUDGE_SYSTEM_PROMPT),
 user(descriptions.json COMPLETO, serializzato IDENTICO a ogni chiamata per questa lezione),
 assistant("Ho letto tutte le descrizioni delle immagini disponibili."),
 user(titolo + key_concepts + testo completo delle unità di QUESTA specifica macro-sezione)]
```
passando i primi 3 messaggi come `history` (byte-identici tra le N chiamate di questa lezione)
e il quarto come `prompt` (variabile per macro-sezione) a `call_structured`. Questo massimizza
la possibilità di hit di caching automatico dei provider che lo supportano (es. DeepSeek fa
caching automatico e trasparente di prefissi ripetuti byte-identici, nessun parametro speciale
richiesto).

## Parte 1 — Nuovo job di routing `image_unit_judge`

In `rt/core/config.py::_build_default_jobs()`, aggiungi un job `image_unit_judge` con
`max_tokens` alto (riceve l'intero `descriptions.json` come prefisso, potenzialmente grande
con molte immagini — es. `max_tokens=8192`) e `timeout_seconds` adeguato (es. 180). Crea
`config.example/rt/image_unit_judge.yaml` con la stessa struttura shell degli altri file in
quella cartella.

## Parte 2 — Modello Pydantic e prompt

In `rt/llm/prompts.py`, stessa convenzione del Task 14:
```python
class ImageUnitJudgeResult(BaseModel):
    image_hashes: List[str] = Field(default_factory=list, description="Chiavi sha256 (da descriptions.json) delle immagini pertinenti a questa macro-sezione, lista vuota se nessuna")


IMAGE_UNIT_JUDGE_SYSTEM_PROMPT = """Sei un assistente che decide quali immagini tra quelle
disponibili sono pertinenti al contenuto di una specifica sezione di una lezione universitaria.
Riceverai prima l'elenco completo delle immagini disponibili con le loro descrizioni, poi il
contenuto della sezione da valutare. Per ogni immagine, valuta se il suo contenuto (titolo,
testo OCR, elementi visivi, parole chiave) è concettualmente pertinente al contenuto della
sezione. Una sezione può avere più immagini pertinenti, o nessuna. La stessa immagine, in
chiamate separate per sezioni diverse, può essere ritenuta pertinente a più di una sezione:
valuta ogni sezione in modo indipendente, senza preoccuparti di eventuali assegnazioni ad
altre sezioni. Sii selettivo: assegna un'immagine solo se il collegamento tematico è chiaro,
non genericamente plausibile."""


def build_image_descriptions_context_message(descriptions: dict) -> str:
    """Serializza l'intero descriptions.json (hash -> {slide_title, ocr_text, visual_elements,
    summary_keywords, alt_text} — ometti 'filename'/'source', non rilevanti per il giudizio)
    in una stringa JSON compatta e leggibile, da passare come primo messaggio 'user' della
    history. DEVE produrre output byte-identico a parità di input, per la cache-friendliness
    descritta sopra (usa json.dumps con sort_keys=True)."""


def build_image_unit_judge_user_prompt(macro_title: str, units_text: str) -> str:
    return f"""Valuta questa sezione della lezione:

TITOLO SEZIONE: {macro_title}

CONTENUTO DELLE UNITÀ DIDATTICHE DI QUESTA SEZIONE:
{units_text}

Restituisci l'oggetto JSON conforme a ImageUnitJudgeResult con gli hash delle immagini
pertinenti a questa sezione (lista vuota se nessuna)."""
```
Adatta i dettagli minori mantenendo lo stile italiano del resto del file.

## Parte 3 — Wiring in `rt/pipeline/add_images.py`

```python
def judge_images_by_macro(lesson_dir: str, outline, force_mock: bool = False) -> Dict[str, List[str]]:
    """Per ogni macro-sezione di 'outline' (Outline caricata da rt.pipeline.outline.load_outline),
    esegue UNA chiamata a call_structured con la history condivisa (messaggio 1: descriptions.json
    completo, messaggio 2: ack dell'assistant) e il prompt specifico della macro-sezione (titolo +
    concatenazione di titolo+key_concepts di ogni sua unità). Ritorna {macro_id: [hash, ...]}.
    Se descriptions.json è vuoto (nessuna immagine), ritorna {} senza fare alcuna chiamata LLM."""
```
Costruisci `units_text` per una macro-sezione concatenando, per ciascuna delle sue
`OutlineUnit`, titolo e `key_concepts` (non serve il testo completo del draft qui — il giudizio
si basa sul contenuto tematico dell'outline, non sulla prosa rielaborata integrale, per tenere
il prompt compatto; se in fase di test la qualità del giudizio risultasse insufficiente con
solo titolo+key_concepts, puoi arricchire con il contenuto di `DraftUnit.content` — usa il tuo
giudizio, ma parti dall'opzione più leggera).

## Test

Aggiungi test per: `build_image_descriptions_context_message` produce output deterministico
(stesso input → stesso output, verifica `sort_keys=True` o equivalente); `judge_images_by_macro`
con un `descriptions.json` di test e un `Outline` con 2-3 macro-sezioni (mock del client LLM,
verifica che venga fatta UNA chiamata per macro-sezione — non una per immagine — e che i primi
2 messaggi della `history` passata a `call_structured` siano IDENTICI tra le chiamate per
macro-sezioni diverse della stessa lezione); caso `descriptions.json` vuoto → nessuna chiamata
LLM, ritorna `{}`. Esegui `python3 -m pytest tests/ -q` e correggi eventuali fallimenti tu
stesso prima di considerare il task concluso.

## Attenzione — bug di portabilità ricorrente in questo progetto

Più round di task precedenti hanno usato `Optional[...]`/`List[...]`/`Dict[...]` come
annotazione di tipo senza il corrispondente `from typing import ...` in cima al file — funziona
per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo differito di
default, PEP 649) ma darebbe `NameError` su Python <3.14. Verifica sempre che ogni nome da
`typing` che usi sia importato esplicitamente nel file che lo usa.
