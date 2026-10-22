# Piano 4 · Campi di testo senza bordo nero di focus

Agente: da assegnare all'avvio della b3. Richiesta di Attilio (22/10/2026): nei campi di testo (risposta
scritta alle domande, richiesta di Chiedi e Verifica, e gli altri) col cursore dentro compare un bordo
nero spesso. Va tolto: il cursore che lampeggia basta a far capire dove si scrive.

## Da dove viene

- `frontend/src/index.css`, `@layer base`: `:focus-visible { outline: 2px solid var(--fg) }` per tutto.
- Molti campi aggiungono `focus-visible:outline-2 focus-visible:outline-ring`: `ui/textarea.tsx`,
  `ui/input.tsx`, `LightweightSession.tsx` (risposta e commento), `StudyNotePopup.tsx` (richiesta di
  Chiedi/Verifica), `Study.tsx`, `DocumentMenu.tsx`, `NewLessonDialog.tsx`, `settings/questions.tsx`,
  `panels/QuestionsPanel.tsx`, `panels/QuestionEditModal.tsx`, `panels/SourcesSection.tsx`.
- `calendar/CalendarPopups.tsx` usa `focus:ring-1 focus:ring-primary` sui suoi campi.

## Cosa fare

1. In `index.css`, **fuori** da `@layer base` (così vince sulle utility di Tailwind), una regola sola:
   ```css
   :is(textarea, input:not([type="checkbox"], [type="radio"], [type="range"], [type="button"],
       [type="submit"], [type="reset"], [type="file"], [type="color"])):focus-visible { outline: none; }
   ```
2. Togliere `focus:ring-1 focus:ring-primary` dai campi di `CalendarPopups.tsx`.
3. Le classi `focus-visible:outline-*` sui campi di testo si possono lasciare (la regola le annulla)
   o togliere dove è semplice; **non** toccare il focus di pulsanti, link, checkbox, select e maniglie:
   lì serve a chi usa la tastiera.
4. Controllo a vista: risposta scritta in Studio/Domande, richiesta di Chiedi e Verifica, popup Genera,
   Nuova lezione, Impostazioni, calendario. Nessun bordo nero col cursore dentro; il bordo grigio
   normale del campo resta.

## Test

Un e2e Playwright: focus nel campo "Risposta scritta" e nel campo di Chiedi →
`getComputedStyle(el).outlineStyle === 'none'`; focus da tastiera su un pulsante → outline presente.
