# Piano 11 · Uso Integra: la fonte entra nella scaletta e può aggiungere unità

Giro 2. Dipende dai piani 6 e 8 (già uniti: `Source.uso`, `Source.pagine`, `pages_for_use`).

## Com'è oggi

- La scaletta vede solo `segments.json` (`run_outline`, `rt/pipeline/outline.py:106-214`).
- I segmenti sono la principale (se è un materiale o appunti scelti) oppure audio e appunti
  (`segment_source_ids`, `rt/pipeline/source_update.py:81-89`). I materiali non principali non
  diventano mai segmenti: arrivano solo nelle unità, con il classificatore per pagina
  (`assign_material_pages`, `rt/pipeline/material_mapping.py:551`) e il blocco "PAGINE DEI
  MATERIALI ASSEGNATE A QUESTA UNITÀ" (`rt/llm/prompts.py:210`).
- La regola 8 (`prompts.py:160`) dice che la fonte principale comanda: le pagine approfondiscono solo
  argomenti già presenti.
- Nel piano 8 `uso=integra` si salva ma si comporta come `contesto`.

## Cosa deve succedere

Una fonte con `uso = "integra"` (materiale, DOCX/TXT, appunti o audio) **entra nei segmenti**: la
scaletta la vede e può creare unità per argomenti che la principale non ha. Il suo testo nelle unità
è contenuto da coprire, non solo contesto.

## Segmenti

- `segment_source_ids` aggiunge le fonti non rimosse con `uso == "integra"` all'insieme dei segmenti,
  qualunque sia la principale.
- `prepare_source_update` costruisce i segmenti delle fonti integra:
  - materiali e documenti: una pagina per segmento, con le pagine di `pages_for_use` (rispetta
    `pagine`, ignorate ed eliminate), come le pagine della principale materiale
    (`source_update.py:139-146`);
  - audio e appunti: come oggi.
- Ogni segmento integra ha `integra: true` e `fonte: <nome file>`.
- Ordine: dopo i segmenti della principale (e di audio e appunti), nell'ordine delle fonti. I
  segmenti senza tempo non spostano i timecode della registrazione: usa per loro la stessa
  convenzione dei segmenti `materiale`.
- Le fonti integra non passano più dal classificatore per pagina: escludile dal ciclo dei non
  principali in `assign_material_pages` (`material_mapping.py:566-640`) e da
  `material_context_parts` (`rt/core/materials.py:226-249`). Le loro immagini, con `estrai=immagini`,
  vanno nelle unità che coprono i loro segmenti, come le immagini della principale materiale.

## Prompt

- Riassunto dei segmenti per la scaletta (`outline.py:143-147`): i segmenti integra hanno il prefisso
  `[integra: <fonte>]`.
- `OUTLINE_SYSTEM_PROMPT` (`prompts.py:72-113`), una regola in più: "I segmenti marcati [integra: …]
  vengono da una fonte da integrare: coprili tutti come gli altri, anche quando trattano argomenti che
  il resto non ha, aggiungendo unità o sottounità dove servono."
- `REWRITE_SYSTEM_PROMPT`, regola 8: aggiungi che non vale per i segmenti marcati [integra: …], che
  sono contenuto della lezione da riscrivere come gli altri segmenti.
- `extend_outline` (`rt/pipeline/outline_extension.py:80-101`): stessa nota nel prompt.
  `validate_extension` permette già unità nuove per segmenti nuovi; verifica che una fonte integra
  aggiunta a una lezione esistente con "estendi" produca unità nuove senza toccare quelle fisse.

## Aggiornamento della lezione

- Aggiungere una fonte integra, o cambiare l'uso di una fonte da o verso integra, cambia i segmenti:
  la lezione risulta da aggiornare. Con "estendi" le unità esistenti restano e si aggiungono quelle
  per i segmenti nuovi; da contesto a integra o viceversa su una fonte già usata serve "ricostruisci"
  (`solo_ricostruzione` in `source_selection.py:24-41`, aggiungi questo caso).
- `record_used_selection` salva anche gli usi usati (`usi_usati: {sid: uso}`), per riconoscere il
  cambio.

## Test

- `tests/test_integra.py`:
  - una lezione audio con un PDF integra: `segments.json` contiene le sue pagine dopo l'audio, con
    `integra: true`, solo le pagine scelte e niente ignorate;
  - il riassunto per la scaletta ha il prefisso;
  - il classificatore non viene chiamato per le pagine integra (mock che conta);
  - `material_context_parts` non le include;
  - "estendi" con una fonte integra nuova aggiunge unità e lascia le vecchie;
  - cambiare contesto → integra richiede "ricostruisci";
  - una fonte contesto si comporta esattamente come prima (test esistenti verdi).
- Aggiorna `test_source_update.py`, `test_outline_extension.py`, `test_source_selection.py` dove
  serve.

## Changelog

- Uso Integra: una fonte da integrare entra davvero nella lezione. La scaletta la vede e può
  aggiungere unità per gli argomenti che la registrazione non tratta.
