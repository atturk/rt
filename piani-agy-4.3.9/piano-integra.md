# Piano: fonti "Integra" che non duplicano la lezione

Caso reale: lezione PGSS 2026-11-11 (audio 1 h 12 min in due parti + PDF 15 pagine, uso **Integra**, affidabilità alta).
Risultato sbagliato: unità 3.4 "Inquadramento degli algoritmi genetici e sintesi…" costruita solo dalle 15 pagine,
timestamp 1:12:26 (fine audio), sottotitoli `###` non numerati, tutte le 15 immagini del PDF in 3.4,
argomenti già spiegati dal docente in 2.3-2.4 e 3.1-3.3 ripetuti.

## Causa (codice attuale)

1. `rt/pipeline/source_update.py` (~r. 288-300): le pagine Integra diventano segmenti **accodati dopo l'audio**,
   tutti con `start_seconds` = durata dell'audio (offset). Nel caso reale `seg_000235…249` hanno tutti 1:12:26.
2. `rt/llm/prompts.py` `INTEGRA_OUTLINE_RULE`: chiede di coprire **tutti** i segmenti integra. Con la regola
   dei segmenti contigui e non all'indietro, il modello può solo metterli in una o più unità finali:
   non può fonderli con le unità dell'audio che trattano lo stesso argomento. Da qui la duplicazione.
3. `rt/pipeline/build.py` (~r. 85 e 186): il timestamp dell'unità è quello del primo segmento → 1:12:26 inventato.
4. `rt/pipeline/material_mapping.py` (~r. 617-650): per le fonti Integra le immagini vanno all'unità che contiene
   il segmento della pagina, **senza classificatore** → tutte in 3.4.
5. La riscrittura riceve 15 pagine in una sola unità e inventa sottotitoli `###` non numerati.

## Comportamento voluto (Attilio)

- La fonte principale (registrazione) guida sempre la scaletta.
- Una fonte Integra si comporta come **Contesto** per le pagine che il docente ha trattato
  (testo e immagini vanno alle unità dell'audio che ne parlano).
- Solo le pagine su argomenti **non trattati** possono creare unità o sottounità nuove.
- Le unità nate dal documento **non hanno timestamp**: al suo posto un'icona documento con tooltip
  ("Dal documento <nome>, pag. X-Y").

## Implementazione proposta

### 1. Scaletta solo dalla principale
`segment_source_ids` (`source_update.py:138`): le fonti Integra **non** entrano più nei segmenti della scaletta
iniziale. La scaletta si genera come per Contesto. Togliere `INTEGRA_OUTLINE_RULE` dal prompt iniziale.

### 2. Smistamento pagine Integra (dopo la scaletta)
Per ogni pagina della fonte Integra usare il percorso esistente del materiale non principale
(`find_candidate_subunits_for_page` + `classify_material_page`, `material_mapping.py:653` ss.):
- pagina assegnata a una o più unità → contesto di quelle unità (testo + immagini), come una fonte Contesto;
- pagina **non assegnata** (nessuna candidata o classificatore dice "nessuna") → "pagina scoperta".
Salvare l'esito in `integra_coverage.json` (`{source_id: {"coperte": {pagina: [unit]}, "scoperte": [pagine]}}`).

### 3. Unità nuove solo dalle pagine scoperte
Se ci sono pagine scoperte: una chiamata LLM (riusare `outline_extension.py` / `_generate_validated_outline`)
con la scaletta esistente **fissa** e le sole pagine scoperte raggruppate. Il modello decide per ogni gruppo:
- nuova sottounità dentro una macro esistente (dopo l'unità più affine), oppure
- nuova macro/unità, oppure
- scartare (argomento già coperto) → la pagina diventa contesto dell'unità più affine.
Le unità nuove hanno `origine: "documento"`, `fonte`, `pagine` e **nessun segmento audio**.
Il validatore (`validator.py`) esenta queste unità dalla regola "segmenti non all'indietro"
(non hanno tempo) e ID/numerazione seguono la posizione nella scaletta.

### 4. Timestamp e interfaccia
- `build.py`: se l'unità ha `origine == "documento"` (o il primo segmento è `integra`) non scrivere il timestamp;
  esporre `origine/fonte/pagine` nell'API dell'unità.
- Frontend (dove oggi c'è la pillola del timestamp): icona `FileText` con tooltip
  "Dal documento <fonte>, pag. X-Y"; niente salto nell'audio al clic.

### 5. Riscrittura
- Unità da documento: prompt "riscrivi da queste pagine", stessa struttura delle altre unità,
  **niente sottotitoli `###`/`####` propri** (regola valida per tutte le unità: i titoli li dà la scaletta).
- Affidabilità della fonte rispettata come oggi.

### 6. Compatibilità
- Lezioni esistenti con unità Integra in coda: restano come sono; "Ricostruisci" applica la nuova logica.
- Aggiungere una fonte Integra a lezione già fatta (`extend_outline`, `source_update.py:461`):
  stessa pipeline 2-3 sulla scaletta esistente.

### Test
- Unit: segmenti scaletta senza Integra; pagina coperta → contesto e immagini all'unità giusta;
  pagina scoperta → unità `origine=documento` senza timestamp; validatore accetta unità documento in mezzo.
- Fixture: questa lezione PGSS (zip senza audio) con segmenti dell'audio + PDF:
  attesi zero unità duplicate sugli algoritmi genetici e immagini distribuite in 2.3/2.4/3.x.
