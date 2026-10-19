# Piano per Codex · 4.3.2b1 · Il suggerimento dei pulsanti a icona compare anche quando sono disattivati

Base: `claude/rt-4.3.2-beta`. File: `frontend/src/components/ui/icon-button.tsx`, `frontend/src/components/lessons/NewLessonDialog.tsx`, test.

## Richiesta (Attilio)
In Nuova lezione il suggerimento "Allega documenti alle unità" compare solo quando il pulsante è attivo. Deve comparire sempre.

## Causa
`NewLessonDialog.tsx` (righe ~970–1000) passa a `IconButton` la prop nativa `disabled` (`disabled={busy || solo || materialFiles.length === 0}`). Un `<button disabled>` non riceve passaggio del mouse né focus, quindi il `Tooltip` non si apre. `IconButton` ha già il modo giusto, la prop `unavailable` (aria-disabled, focus e suggerimento con il motivo), ma qui non viene usata. Lo stesso problema c'è in altri punti che passano `disabled` a `IconButton`: `EditorToolbar`, `LessonUpdateBar`, `EnrichmentPanel`, `QuestionsPanel`, `ReviewPanel`, `SourcesSection`, e i pulsanti Revisione, Arricchimento e Solo trascrizione di Nuova lezione.

## Cosa fare
1. **In `IconButton` (correzione generale):** togliere `disabled` dalle props passate al `<button>`. Se `disabled` è vero e non c'è `unavailable`, comportarsi come `unavailable`:
   - `aria-disabled="true"`, stesso stile attenuato;
   - `onClick` bloccato;
   - il suggerimento mostra solo l'etichetta, senza ": motivo".
   Così tutti i pulsanti a icona disattivati mostrano il nome al passaggio e al focus, ovunque. Controllare che `aria-pressed` resti, e che un `type="submit"` disattivato non invii il form: con `aria-disabled` il clic va bloccato con `preventDefault`, già fatto nell'`onClick`. Aggiungere il blocco anche per Invio e Spazio se il pulsante è di tipo submit.
2. **In Nuova lezione, il motivo:** usare `unavailable` con un testo che spiega perché il pulsante non si può usare:
   - "Allega documenti alle unità": "aggiungi almeno un documento" se non ci sono materiali; "non con Solo trascrizione" se Solo è attivo; "importazione in corso" se `busy`.
   - "Revisione" e "Arricchimento": "non con Solo trascrizione" oppure "importazione in corso".
   - "Solo trascrizione": "importazione in corso".
   Il suggerimento diventa per esempio "Allega documenti alle unità: aggiungi almeno un documento".
3. Nessun'altra modifica visiva.

## Test (vitest)
- `IconButton` con `disabled`: niente attributo `disabled`, `aria-disabled="true"`, il clic non chiama `onClick`, il suggerimento compare al passaggio e al focus.
- Nuova lezione senza materiali: il pulsante "Allega documenti alle unità" mostra "Allega documenti alle unità: aggiungi almeno un documento" e il clic non cambia lo stato. Con un documento il clic lo attiva come oggi.
- I test esistenti che cercano `toBeDisabled()` su un `IconButton` vanno aggiornati a `toHaveAttribute('aria-disabled', 'true')`.

Comandi: `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`.

## Changelog
Sezione 4.3.2b1, Correzioni: "I pulsanti a icona disattivati mostrano comunque il loro nome al passaggio del mouse, e in Nuova lezione anche il motivo."
