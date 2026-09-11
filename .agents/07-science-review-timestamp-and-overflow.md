# Task 07 — Review scienza: timestamp della claim errato + testo troncato nel pannello

Indipendente dagli altri task in questa cartella (nessun file condiviso).

Nel progetto RT (/Users/attilioturco/Desktop/trt), correggi due bug confermati nella review
scientifica da terminale. Implementa direttamente, senza produrre un piano preliminare.

## Bug A — il timecode mostrato è sempre l'inizio dell'unità, mai il punto reale della claim

Diagnosi confermata sui dati reali (log LLM e science_issues.json di una lezione vera): la
causa è `rt/pipeline/review_science.py:279-281`:
```python
if not iss.segment_id and unit.source_segment_ids:
    iss.segment_id = unit.source_segment_ids[0]
```
Il modello non riceve MAI i segment_id dei segmenti sorgente nel prompt (deliberatamente, per
non confonderlo con artefatti ASR grezzi — scelta corretta, non toccare `build_science_review_
user_prompt` per aggiungere segment_id al prompt), quindi `iss.segment_id` è sempre `None` in
uscita dal modello, e questo fallback sostituisce sempre e comunque con il PRIMO segmento
dell'unità — che può essere anche minuti prima del punto in cui la claim è realmente espressa,
dato che un'unità può coprire diversi minuti di lezione.

Il prompt istruisce esplicitamente il modello a citare `claim` letteralmente da una frase
intera del testo rielaborato (`rt/llm/prompts.py:227`: "deve corrispondere letteralmente a una
frase intera o proposizione autonoma del testo") — quindi `iss.claim` è quasi sempre una
sottostringa esatta di `unit.content`. Sfrutta questo per localizzare la claim in modo
deterministico (nessuna chiamata LLM aggiuntiva), stimando su quale segmento sorgente cade in
base alla posizione del carattere nel testo rielaborato, proporzionata sulla durata cumulativa
dei segmenti sorgente dell'unità (non esiste una provenance a grana più fine di
`unit.source_segment_ids`, quindi questa è una stima onesta, non un mapping esatto — comunque
enormemente più vicina alla realtà di "sempre il primo segmento").

Aggiungi in `rt/pipeline/review_science.py` (o in un punto sensato dello stesso file):
```python
def _localize_claim_segment(claim: str, unit, seg_by_id: dict) -> Optional[str]:
    """Stima il segment_id più vicino al punto in cui 'claim' compare nel testo rielaborato
    dell'unità, mappando proporzionalmente la posizione del carattere sulla durata cumulativa
    dei segmenti sorgente. Approssimazione: non esiste provenance a grana fine tra singole
    frasi rielaborate e segmenti sorgente. Ritorna None se la claim non è rintracciabile
    (nessuna corrispondenza testuale) o se l'unità non ha segmenti sorgente risolvibili."""
    offset = unit.content.find(claim.strip())
    if offset < 0:
        return None
    segs = [seg_by_id[sid] for sid in unit.source_segment_ids if sid in seg_by_id]
    if not segs:
        return None
    ratio = offset / max(1, len(unit.content))
    total_duration = sum(max(0.01, s.end_seconds - s.start_seconds) for s in segs)
    target = ratio * total_duration
    cumulative = 0.0
    for s in segs:
        cumulative += max(0.01, s.end_seconds - s.start_seconds)
        if cumulative >= target:
            return s.id
    return segs[-1].id
```
e sostituisci il fallback attuale con:
```python
if not iss.segment_id:
    iss.segment_id = _localize_claim_segment(iss.claim, unit, seg_by_id)
```
Verifica se `seg_by_id: Dict[str, Segment] = {s.id: s for s in segments_data.segments}` è già
costruito in questa funzione (pattern già usato altrove nel progetto, es. `rt/pipeline/
outline.py`, `rt/pipeline/build.py`) — se non lo è, costruiscilo dove serve, riusando i
`segments_data` già caricati per la review.

Quando `_localize_claim_segment` ritorna `None` (claim non trovata verbatim, o segmenti non
risolvibili), lascia `iss.segment_id` a `None`: `rt/pipeline/issue_review.py` (riga ~716-717,
`tc = seg.start_formatted if seg else "N/D"`) già gestisce correttamente questo caso mostrando
"N/D" — NON serve toccare quella riga per questo bug, il fallback silenzioso e sbagliato era
solo in review_science.py.

Dato che il timecode ora è sempre una stima (mai una posizione esatta fornita dal modello),
in `rt/pipeline/issue_review.py::_build_science_panel` cambia l'etichetta da
`"⏱ Timecode:"` a `"⏱ Timecode (stima):"` per essere onesti con l'utente su cosa sta vedendo.

## Bug B — il testo del pannello viene troncato con "…" non scrollabile

Diagnosi confermata: `_build_science_panel`/`_build_asr_panel` non applicano alcun limite di
lunghezza al contenuto — il troncamento visibile è il comportamento di default di
`rich.live.Live` quando il contenuto supera l'altezza del terminale
(`vertical_overflow="ellipsis"` di default), NON un vero scroll interattivo. Fix minimo: in
`rt/pipeline/issue_review.py`, dove viene istanziato `Live(console=console,
auto_refresh=False, transient=False)` (riga ~497), aggiungi `vertical_overflow="visible"`:
```python
Live(console=console, auto_refresh=False, transient=False, vertical_overflow="visible")
```
Così il contenuto completo viene sempre stampato (il terminale scorre normalmente se serve),
invece di essere tagliato con un finto "…" che non porta a nessuna interazione reale.

## Test

Aggiungi un test per `_localize_claim_segment` (claim trovata verso la fine di un'unità lunga
→ segmento vicino alla fine, non il primo; claim non trovata → `None`; unità con un solo
segmento sorgente → quello stesso segmento). Esegui `python3 -m pytest tests/ -q` e correggi
eventuali fallimenti tu stesso prima di considerare il task concluso.
