# Task 08 — Recall: invalida le domande generate su contenuto ormai superato

Indipendente dagli altri task in questa cartella tranne una piccola sovrapposizione col Task 09
su `rt/pipeline/recall.py` (funzioni diverse — se entrambi i task sono in esecuzione, eseguili
in ordine numerico 08 prima di 09, come da convenzione in `.agents/00-README.md`).

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

CONTESTO: oggi una `RecallQuestion` (schema in `rt/core/models.py:224-233`) non ha alcun
legame verificabile col contenuto del draft da cui è stata generata (solo `unit_ids`, nessun
fingerprint/hash). Se l'utente modifica il trascritto finale a mano, o accetta una correzione
nella review scientifica che cambia il testo effettivo di un'unità (le decisioni della review
non riscrivono `draft.json` direttamente, ma vengono applicate "a runtime" da
`rt.pipeline.ledger.load_resolved_draft(lesson_dir)`, la stessa funzione già usata da
`generate_recall_batch` e `evaluate_recall_answer` in `rt/pipeline/recall.py` per leggere il
contenuto "vero" di un'unità), una domanda quiz/vasta già generata (il cui testo o le cui
opzioni sono "congelati" in `pregenerated_material`/`question_text` al momento della
generazione) può riferirsi a un contenuto che non esiste più, senza che nulla se ne accorga.

APPROCCIO SCELTO (deliberatamente semplice: un controllo pigro al momento della lettura,
non un sistema di invalidazione a cascata come quello della pipeline principale in
`rt/core/idempotency.py` — qui non serve quella complessità, basta ricalcolare un hash quando
serve davvero, cioè quando una domanda pendente sta per essere effettivamente proposta):

1. In `rt/core/models.py`, aggiungi a `RecallQuestion` (riga ~224-233) un campo:
   ```python
   content_fingerprint: Optional[str] = None
   ```
   (opzionale per retro-compatibilità: le domande già esistenti in bank generate prima di
   questo fix avranno `None` e NON devono essere considerate stale solo per questo — vedi
   punto 3).

2. In `rt/pipeline/recall.py`, aggiungi un helper:
   ```python
   def _compute_units_fingerprint(lesson_dir: str, unit_ids: list) -> Optional[str]:
       from rt.pipeline.ledger import load_resolved_draft
       from rt.core.idempotency import compute_string_sha256
       try:
           draft = load_resolved_draft(lesson_dir)
       except Exception:
           return None
       contents = []
       for uid in unit_ids:
           unit = next((u for u in draft.units if u.unit_id == uid), None)
           if unit is None:
               return None
           contents.append(unit.content)
       return compute_string_sha256("|".join(contents))
   ```
   Chiamalo in `generate_recall_batch` (riga ~280) subito dopo aver determinato gli
   `unit_ids` di ogni nuova `RecallQuestion` creata, e valorizza `content_fingerprint` con il
   risultato.

3. In `get_next_pending_question` (`rt/pipeline/recall.py:68-127`), subito dopo aver costruito
   la lista `pending` (riga ~89, prima di applicare `exclude_id`/l'ordinamento), ricalcola il
   fingerprint corrente per ciascuna domanda pendente e rimuovi dal bank quelle il cui
   `content_fingerprint` è impostato (non `None`) e NON coincide più con quello corrente:
   ```python
   fresh_pending = []
   stale_ids = set()
   for q in pending:
       if q.content_fingerprint is None:
           fresh_pending.append(q)
           continue
       current_fp = _compute_units_fingerprint(lesson_dir, q.unit_ids)
       if current_fp is not None and current_fp != q.content_fingerprint:
           stale_ids.add(q.id)
       else:
           fresh_pending.append(q)
   if stale_ids:
       bank.questions = [q for q in bank.questions if q.id not in stale_ids]
       save_recall_bank(bank, lesson_dir)
   pending = fresh_pending
   ```
   Adatta i nomi di variabile locale al codice reale della funzione (leggi la funzione per
   intero prima di modificarla). Le domande rimosse così sono SOLO quelle ancora `PENDING`
   (mai proposte): domande già `ASKED`/`ANSWERED` non vengono mai toccate da questo
   meccanismo (sono uno storico, e una domanda "asked" potrebbe essere in corso di risposta
   proprio ora — non farla sparire sotto l'utente). Non serve rigenerare nulla esplicitamente
   qui: se dopo la rimozione `pending` risulta vuoto, il flusso esistente che gestisce "nessuna
   domanda pendente" (verifica dove viene chiamato `generate_recall_batch` per rifornire il
   pool, in `rt/pipeline/recall_session.py`) si occupa già di generarne di nuove come fa oggi
   quando il pool si esaurisce naturalmente — non modificare quella parte, limitati a
   verificare che il percorso esista e funzioni ancora con la lista `pending` ridotta.

## Test

Aggiungi test in un file esistente pertinente (es. `tests/test_recall*.py` — cercalo) che
coprano: una domanda pendente con fingerprint corrispondente al draft corrente viene
restituita normalmente; una domanda pendente con fingerprint NON corrispondente viene rimossa
dal bank e NON restituita; una domanda con `content_fingerprint=None` (retro-compatibilità)
viene trattata come valida; una domanda `ASKED`/`ANSWERED` con fingerprint non corrispondente
NON viene toccata. Esegui `python3 -m pytest tests/ -q` e correggi eventuali fallimenti tu
stesso prima di considerare il task concluso.
