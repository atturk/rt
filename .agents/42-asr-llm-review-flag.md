# Task 42 — `rt review --asr-llm`: raffinamento LLM dei candidati a rischio ASR (meno falsi positivi, costa di più)

Dipende dal Task 41 (rilevamento statistico + card `ERR_ASR_ST` + fix del bug di applicazione
decisioni): deve essere già fatto e i test devono già passare prima di iniziare questo. Nel
progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano
preliminare.

## Contesto

Il Task 41 rende `rt review` capace di flaggare deterministicamente (gratis, zero chiamate LLM)
i segmenti/unità a rischio ASR sulla base della sola confidenza acustica, con probabili falsi
positivi (nomi propri, termini rari ma corretti, rumore di fondo — statisticamente anomali ma
senza alcun rischio reale di travisamento nel testo rielaborato). Questo task aggiunge un flag
opzionale `--asr-llm` a `rt review` che, invece di trasformare direttamente ogni candidato
statistico in una issue, lo sottopone al giudizio dell'LLM che fa già la critica scientifica per
quell'unità — **non è una chiamata LLM aggiuntiva separata**, è un arricchimento del prompt che
`run_review` (`rt/pipeline/review.py`, rinominato dal Task 40) già invia per ogni unità
(`rt/pipeline/review.py` righe 262-294 al momento della stesura: un'unica chiamata
`client.call_structured` per unità di draft). Il costo aggiuntivo è solo il testo extra nel
prompt per le unità che hanno effettivamente un candidato a rischio (non per tutte le unità),
non una nuova chiamata di rete.

**Comportamento delle due modalità**:
- `rt review` (default, invariato dal Task 41): candidati statistici → issue `ERR_ASR_ST`
  direttamente, nessun coinvolgimento LLM per questa parte.
- `rt review --asr-llm`: candidati statistici NON diventano `ERR_ASR_ST` direttamente. Per ogni
  unità che ne contiene almeno uno, il prompt della normale chiamata di critica scientifica per
  quell'unità viene arricchito con il segmento raw candidato + la sua metrica di rischio,
  chiedendo esplicitamente all'LLM di giudicare se il testo rielaborato di quel punto è fedele
  o sembra fabbricato/travisato. Se l'LLM conferma il sospetto, genera una issue di tipo
  `ERR_ASR_LLM` (stesso schema/UX di `ERR_ASR_ST` nella card di revisione — vedi sotto). Se
  l'LLM non trova nulla di sospetto (es. era solo un nome proprio raro correttamente riportato),
  non genera alcuna issue per quel candidato: **il candidato scompare silenziosamente**, non
  meno true un fallback a `ERR_ASR_ST` — è esattamente il comportamento voluto (meno falsi
  positivi, l'LLM ha già validato che va bene così).

## Modifiche

### 1. Nuovo tipo di issue

In `rt/core/models.py`, aggiungi `ScienceType.ERR_ASR_LLM = "ERR_ASR_LLM"` accanto a
`ERR_ASR_ST` (già aggiunto dal Task 41).

### 2. Flag CLI

In `rt/cli.py`, sul parser del comando `review` (rinominato dal Task 40): aggiungi
`p_review.add_argument("--asr-llm", action="store_true", help="Affida all'LLM di critica
scientifica la validazione dei candidati a rischio ASR invece del solo criterio statistico
(meno falsi positivi, costa di più)")`. Propaga il flag fino a `run_review(lesson_dir, ...,
asr_llm=args.asr_llm)`.

### 3. `run_review` (`rt/pipeline/review.py`): biforcazione sul flag

Nel loop `for idx, unit in enumerate(draft.units, start=1):` (righe 262-311 al momento della
stesura):
- Calcola comunque, per ogni lezione, l'insieme di candidati a rischio raggruppati per unità
  (la stessa funzione di rilevamento statistico introdotta dal Task 41 — riusala identica, non
  duplicarla).
- Se `asr_llm` è `False` (default): comportamento del Task 41 invariato — i candidati diventano
  direttamente issue `ERR_ASR_ST`, aggiunte a `all_science_issues` PRIMA o DOPO il loop LLM
  (come già fa il Task 41).
- Se `asr_llm` è `True`: NON creare `ERR_ASR_ST` per le unità che verranno comunque processate
  dal loop LLM sottostante (evita doppia segnalazione per lo stesso punto). Per l'unità corrente
  nel loop, se ha almeno un candidato a rischio associato, costruisci un blocco di contesto
  extra (testo raw del segmento candidato + timecode + valore della metrica di rischio +
  soglia della lezione) e passalo a `build_science_review_user_prompt` (vedi punto 4) prima di
  chiamare `client.call_structured` per quell'unità. Le unità SENZA candidati vengono chiamate
  esattamente come oggi, prompt invariato (nessun costo aggiuntivo per la maggioranza delle
  unità).
- Dopo la risposta LLM per un'unità con contesto ASR iniettato, se `res.issues` include una
  issue con `type == ScienceType.ERR_ASR_LLM`, trattala come le altre issue del ciclo esistente
  (assegnazione `unit_id`, numerazione progressiva, salvataggio) — nessuna logica speciale
  necessaria oltre a permettere questo valore nell'enum.
- Se per un'unità con candidato l'LLM NON genera alcuna issue `ERR_ASR_LLM` (giudizio: nessun
  rischio reale), non fare nulla: nessuna issue di fallback, il candidato è stato validamente
  scartato.

### 4. `build_science_review_user_prompt` (`rt/llm/prompts.py`, riga 234 al momento della
stesura): parametro opzionale per il contesto a rischio ASR

Aggiungi un parametro opzionale, es. `asr_risk_context: Optional[str] = None` (verifica
l'import di `Optional` in cima al file). Quando presente, appendi al prompt un blocco tipo:

```
---
SEGMENTO A RISCHIO ASR RILEVATO STATISTICAMENTE IN QUESTA UNITÀ:
Trascrizione raw (confidenza parole nel percentile-10: {metrica}, soglia lezione: {soglia}):
"{testo_raw_segmento}"

ECCEZIONE PER QUESTO PUNTO SPECIFICO: la tua istruzione generale è di ignorare artefatti ASR
isolati — per QUESTO segmento specifico, invece, valuta se il testo rielaborato corrispondente
riflette fedelmente questa trascrizione raw o se sembra un'invenzione/allucinazione introdotta
durante la riscrittura (puoi non avere abbastanza informazione per saperlo con certezza dalla
sola trascrizione raw, che potrebbe essere essa stessa poco chiara: usa il tuo giudizio). Se
sospetti fabbricazione o travisamento, genera una issue con "type": "ERR_ASR_LLM",
"segment_id": l'ID di questo segmento, "claim": il testo raw sopra, "reason": la tua
motivazione, "suggested_fix": null (non proporre una correzione, serve solo segnalare il
sospetto per revisione umana con ascolto audio). Se non sospetti nulla, non generare alcuna
issue per questo punto.
---
```

Non modificare `SCIENCE_REVIEW_SYSTEM_PROMPT` (`rt/llm/prompts.py`, la sua istruzione generale
di ignorare artefatti ASR isolati resta corretta e utile per la modalità di default senza
`--asr-llm`, dove il rilevamento statistico del Task 41 già copre quel caso senza bisogno
dell'LLM) — l'eccezione va comunicata SOLO nel prompt utente della singola unità interessata,
non globalmente.

## Test

- Test che verifica che senza `--asr-llm` il comportamento sia identico al Task 41 (nessuna
  regressione).
- Test che, mockando `LLMClient.call_structured`, verifica che per un'unità CON candidato a
  rischio e `asr_llm=True` il prompt costruito contenga il blocco di contesto ASR (assert sulla
  stringa passata), mentre per un'unità SENZA candidato il prompt resti quello standard
  (nessuna menzione di rischio ASR).
- Test che verifica che, quando la risposta mockata dell'LLM include una issue `ERR_ASR_LLM`,
  questa venga salvata correttamente in `science_issues.json` con `unit_id` assegnato.
- Test che verifica che, quando la risposta mockata dell'LLM per un'unità con candidato NON
  include alcuna issue ASR, non venga generata alcuna issue di fallback per quel candidato.
- Test sul flag CLI: `rt review --asr-llm` propaga correttamente `asr_llm=True` a `run_review`
  (mocka `run_review` e verifica l'argomento ricevuto).
- Riusa/adatta la card TUI del Task 41 (`_build_science_panel`, azioni Accetta/Modifica senza
  Applica) anche per `ERR_ASR_LLM` — stesso trattamento di `ERR_ASR_ST` in tutti i punti dove il
  Task 41 ha aggiunto una condizione su `iss.type in (ERR_ASR_ST, ...)`: estendi quelle
  condizioni per includere anche `ERR_ASR_LLM` (il Task 41 ti ha già chiesto di strutturare il
  codice pensando a questa estensione futura — verificalo). Aggiungi un test che copre
  esplicitamente `ERR_ASR_LLM` in `apply_decisions_to_draft` (stesso test del Task 41 per
  `ERR_ASR_ST`, ripetuto per questo tipo).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non duplicare la funzione di rilevamento statistico del Task 41: questo task la RIUSA per sapere
quali unità hanno candidati, cambia solo cosa succede dopo (issue diretta vs contesto per
l'LLM).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai una lezione di test con almeno un segmento volutamente degradato disponibile
   nell'ambiente Antigravity: esegui `rt review <lezione> --mock` (default) e verifica che
   produca `ERR_ASR_ST`; poi (su una copia pulita della stessa lezione, per non sporcare i
   checkpoint) `rt review <lezione> --asr-llm` e verifica che il prompt per l'unità coinvolta
   riceva il contesto extra e che l'esito (issue `ERR_ASR_LLM` o nessuna issue) dipenda dalla
   risposta del modello mock/reale usato nel test.
