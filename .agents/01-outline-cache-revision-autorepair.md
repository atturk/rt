# Task 01 — Motore outline: revisione multi-turno cache-friendly + auto-repair

Indipendente — nessun file condiviso con gli altri task in `.agents/`.

Nel progetto RT (/Users/attilioturco/Desktop/trt), ristruttura la generazione/revisione
dell'outline didattica per essere cache-friendly e per auto-correggersi quando la validazione
di dominio fallisce. Implementa direttamente, senza produrre un piano preliminare:

CONTESTO: rt/pipeline/outline.py ha due funzioni, run_outline() (prima generazione) e
run_outline_revision() (quando l'utente chiede modifiche). Oggi run_outline_revision usa un
system prompt DIVERSO (OUTLINE_REVISION_SYSTEM_PROMPT = OUTLINE_SYSTEM_PROMPT + addendum) e
ricostruisce da zero un mega user-message con dentro di nuovo il sommario segmenti + l'intera
outline precedente + il feedback, in un'unica chiamata [system, user]. Questo rompe qualunque
possibilità di caching automatico dei prefissi (es. DeepSeek lo fa in modo trasparente se il
prefisso è byte-identico tra chiamate). Inoltre, quando validate_outline() rifiuta l'outline
generata (es. unità con indici di segmento fuori ordine), l'eccezione risale non gestita fino
a un traceback grezzo per l'utente finale — non esiste alcun tentativo di auto-correzione per
questo tipo di errore (esiste già un repair, ma solo per JSON strutturalmente malformato a
livello Pydantic, meccanismo diverso e da NON toccare).

1. In rt/llm/client.py, LLMClient.call_structured(...) (riga ~117): aggiungi un parametro
   opzionale `history: Optional[List[Dict[str, str]]] = None` alla firma (dopo `lesson_dir`).
   Nella costruzione dei messaggi (riga ~263-266, oggi:
   `messages = [{"role":"system","content": full_system}, {"role":"user","content": prompt}]`),
   cambia in:
   ```python
   messages = [{"role": "system", "content": full_system}]
   if history:
       messages.extend(history)
   messages.append({"role": "user", "content": prompt})
   ```
   Con `history=None` (tutti i chiamanti esistenti, invariati) il comportamento deve restare
   IDENTICO byte-per-byte a oggi. Aggiorna anche la stima approssimativa dei token in ingresso
   usata dal monitor (riga ~267, `approx_in_tok = max(1, (len(full_system) + len(prompt)) // 4)`)
   per includere la lunghezza di `history` quando presente.

2. In rt/llm/prompts.py:
   - Elimina `OUTLINE_REVISION_SYSTEM_PROMPT` (riga ~76-81) — la revisione userà lo stesso
     `OUTLINE_SYSTEM_PROMPT` della prima generazione.
   - Elimina `build_outline_revision_user_prompt` (riga ~84-101), sostituita da una funzione
     molto più corta:
     ```python
     def build_outline_revision_followup_prompt(feedback: str) -> str:
         return f"""MODALITÀ REVISIONE: l'outline che hai generato nel tuo turno precedente è
     quella attuale per questa lezione. L'utente ha fornito il seguente feedback libero su di essa:

     FEEDBACK DELL'UTENTE:
     {feedback}

     Genera una NUOVA versione COMPLETA dell'oggetto JSON conforme allo schema Outline che
     incorpori il feedback, rispettando tutti i vincoli del messaggio di sistema (fedeltà
     rigorosa a segment_id realmente esistenti, copertura completa, monotonicità cronologica).
     Non limitarti a modifiche cosmetiche se il feedback richiede una ristrutturazione
     sostanziale."""
     ```
   - Aggiungi anche:
     ```python
     def build_outline_selfrepair_followup_prompt(error_message: str) -> str:
         return f"""L'outline che hai appena generato NON supera la validazione deterministica,
     per questo motivo:

     {error_message}

     Genera una NUOVA versione COMPLETA dell'oggetto JSON conforme allo schema Outline che
     corregga esattamente questo problema, rispettando tutti i vincoli del messaggio di sistema."""
     ```
   - Rinforza la regola 4 di `OUTLINE_SYSTEM_PROMPT` (oggi: "4. Nessun segmento temporale deve
     andare all'indietro (monotonicità cronologica assoluta)."), specificando meccanicamente il
     vincolo che il validatore controlla davvero — sostituiscila con:
     ```
     4. Nessun segmento temporale deve andare all'indietro: per OGNI coppia di unità consecutive
        nell'ordine in cui compaiono nell'outline (sia all'interno dello stesso macro-capitolo,
        sia tra un macro-capitolo e il successivo), l'indice del start_segment_id dell'unità
        successiva DEVE essere maggiore o uguale all'indice del end_segment_id dell'unità
        precedente. Non sono ammesse sovrapposizioni né salti all'indietro. Prima di produrre
        l'output finale, ripercorri mentalmente la sequenza di tutte le unità e verifica che
        questo vincolo sia rispettato ovunque — è facile perdere il conto in lezioni lunghe con
        molte unità.
     ```

3. In rt/pipeline/outline.py:
   - Aggiungi un helper privato condiviso, usato sia da run_outline() sia da
     run_outline_revision(), che genera e valida con fino a 2 tentativi di auto-riparazione:
     ```python
     def _generate_validated_outline(
         client: LLMClient,
         system_prompt: str,
         base_history: List[Dict[str, str]],
         final_user_prompt: str,
         segments_data,
         lesson_dir: str,
         max_repair_attempts: int = 2,
     ):
         history = list(base_history)
         current_prompt = final_user_prompt
         last_error = None
         for attempt in range(max_repair_attempts + 1):
             outline = client.call_structured(
                 prompt=current_prompt,
                 system_prompt=system_prompt,
                 response_model=Outline,
                 job_name="outline",
                 lesson_dir=lesson_dir,
                 history=history or None,
             )
             try:
                 return outline, validate_outline(outline, segments_data)
             except ValidationError as e:
                 last_error = e
                 if attempt >= max_repair_attempts:
                     raise
                 print(f"⚠️  Outline non valida (tentativo {attempt+1}/{max_repair_attempts+1}): {e}\n"
                       f"   Richiedo correzione automatica all'LLM...")
                 outline_json = json.dumps(outline.model_dump(mode="json"), ensure_ascii=False, indent=2)
                 history = history + [
                     {"role": "user", "content": current_prompt},
                     {"role": "assistant", "content": outline_json},
                 ]
                 current_prompt = build_outline_selfrepair_followup_prompt(str(e))
         raise last_error
     ```
     (importa `ValidationError` da `rt.pipeline.validator`, che è già importata nel file).
   - In run_outline() (riga ~98-110): sostituisci la chiamata diretta a `client.call_structured`
     + `validate_outline` separata con una chiamata a
     `_generate_validated_outline(client, OUTLINE_SYSTEM_PROMPT, [], prompt, segments_data, lesson_dir)`,
     che ritorna `(outline, validation_report)`. Il resto della funzione (save_outline,
     fingerprint, manifest, transition) resta invariato.
   - In run_outline_revision() (riga ~150-215): ricostruisci `original_user_prompt` con la
     STESSA `build_outline_user_prompt(date_val, subject_val, topics_val, segments_summary)`
     già usata da run_outline (input deterministici → risultato byte-identico se info.yaml/
     segments.json non sono cambiati dalla generazione originale). Poi chiama:
     ```python
     history = [
         {"role": "user", "content": original_user_prompt},
         {"role": "assistant", "content": previous_outline_json},
     ]
     followup_prompt = build_outline_revision_followup_prompt(feedback)
     outline, validation_report = _generate_validated_outline(
         client, OUTLINE_SYSTEM_PROMPT, history, followup_prompt, segments_data, lesson_dir
     )
     ```
     (rimuovi l'uso di `OUTLINE_REVISION_SYSTEM_PROMPT`/`build_outline_revision_user_prompt`).
     Il resto della funzione (save_outline, fingerprint, manifest, transition) resta invariato.
   - Aggiorna l'import block in cima al file per riflettere le funzioni rimosse/aggiunte da
     rt.llm.prompts.

4. Esegui la test suite (pytest tests/ -q). Verifica in particolare tests/test_setup.py (testa
   build_outline_user_prompt, invariata) e qualunque test su run_outline_revision — se un test
   asserisce sul numero di chiamate a call_structured o sul suo system_prompt, aggiornalo per
   riflettere che ora usa OUTLINE_SYSTEM_PROMPT (non più OUTLINE_REVISION_SYSTEM_PROMPT) e che
   passa un `history` di 2 messaggi.
