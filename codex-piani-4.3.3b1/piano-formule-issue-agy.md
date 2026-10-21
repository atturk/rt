# Piano 7 · Revisione: formule leggibili nelle issue

Agente: **agy**. Nel pannello della revisione le issue mostrano il LaTeX grezzo
(`$\lambda(0{,}01\,\mathrm{m})=…$`) sia nella "Correzione proposta" sia nella spiegazione.

## Cosa fare

1. In `frontend/src/components/lesson/panels/ReviewPanel.tsx` (card dell'issue, ~righe 240-280)
   usa `MathText` (`frontend/src/components/MathText.tsx`, già usato per le domande) per:
   correzione proposta / testo corretto / `issue.claim` (anche barrato), `issue.reason`,
   `issue.source_quote`, il blocco "Nel testo" (`item.context?.unit_content ?? issue.claim`).
2. In modifica (doppio clic → `Textarea`) resta il testo grezzo: le formule si scrivono in LaTeX.
3. Stessa cosa negli altri punti che mostrano testo delle issue o delle note:
   `panels/StudyNotesPanel.tsx`, `study/StudyNotePopup.tsx`, `panels/ReviewUnits.tsx` (titoli e
   anteprime) se mostrano `claim`, `reason` o `suggested_fix`.
4. Il suggerimento "Doppio clic per modificare" e il doppio clic devono continuare a funzionare
   anche cliccando su una formula resa.

## Test

vitest `ReviewPanel`: una issue con `$x^2$` nella correzione e nella spiegazione rende MathML
(`math` nel DOM, nessun `$` visibile); il doppio clic apre il `Textarea` con il testo grezzo.
