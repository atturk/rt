# Piano 5 · Formule in LaTeX nelle domande

Agente: **agy**. Segnalazione di Attilio (22/10/2026): nella domanda «Come si
definisce la densità superficiale di carica ρ_s…» la formula appare come testo «ρ_s».

## Causa

La SPA rende già le formule fra `$…$` nelle domande (`MathText` in `LightweightSession.tsx`). Il
problema è a monte: i prompt di generazione e valutazione delle domande non hanno la regola LaTeX
(`LATEX_WRITING_RULE` in `rt/llm/prompts.py`) che usano rielaborazione e Verifica, quindi il modello
scrive i simboli in chiaro.

## Cosa fare

1. Aggiungere `+ "\n" + LATEX_WRITING_RULE` in coda ai prompt di sistema `RECALL_QUIZ`,
   `RECALL_MIRATA`, `RECALL_VASTA`, `RECALL_EVAL_MIRATA`, `RECALL_EVAL_VASTA`, `RECALL_VARIANT`,
   `RECALL_TEXT_VARIANT`, `RECALL_EVAL_RAGIONAMENTO`, `RECALL_EVAL_TEXT` (`*_SYSTEM_PROMPT`).
2. Tipi personalizzati: in `rt/pipeline/recall_special.py:system_for` aggiungere la stessa regola in
   coda al prompt.
3. Il prompt fa parte dell'impronta della generazione: i gruppi già esauriti potranno generare domande
   nuove, quelle esistenti non si toccano. Va bene così.

## Test

`tests/test_latex_prompts.py`: parametrizzare il test esistente anche sui prompt sopra e aggiungere un
test che `system_for(...)` contenga `LATEX_WRITING_RULE`.

Implementazione pronta come riferimento sul ramo `claude/formule-domande` (PR #121 chiusa, non unita).
