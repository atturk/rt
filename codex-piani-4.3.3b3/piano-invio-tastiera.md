# Piano 3 · Invio della risposta scritta con ⌘/Ctrl + Invio

Agente: **agy**. Richiesta di Attilio (22/10/2026): nelle domande con il campo
di testo, **⌘ + Invio** (Mac) o **Ctrl + Invio** (Windows) invia la risposta; **Invio** da solo continua
ad andare a capo.

## Dove

`frontend/src/components/recall/LightweightSession.tsx`, il `<textarea aria-label="Risposta scritta">`
delle risposte aperte (oggi solo `onChange`). Il pulsante **Rispondi** chiama `handleWrittenAnswer`
ed è disattivato con risposta vuota o `busy`.

## Cosa fare

1. `onKeyDown` sul textarea: se `event.key === 'Enter'` e `event.metaKey || event.ctrlKey`, e
   `!event.nativeEvent.isComposing`, allora `preventDefault()` e, solo se il pulsante Rispondi sarebbe
   attivo (`writtenAnswer.trim() && !busy`), `handleWrittenAnswer()`. Invio senza modificatori: nessun
   cambiamento. Stesso schema già usato in `ReviewPanel.tsx` e `DocumentMenu.tsx`.
2. Stessa scorciatoia sul textarea del commento "Cosa non va" (`comment-textarea`) per **Invia e
   rigenera**, con le stesse condizioni del suo pulsante.
3. Il suggerimento (title/tooltip) del pulsante Rispondi dice `⌘ Invio` su Mac e `Ctrl Invio` altrove,
   con l'helper per la piattaforma già usato nel progetto se c'è. Nessun testo nuovo sotto il campo.
4. Se la sessione ha già scorciatoie globali da tastiera, verificare che ⌘/Ctrl + Invio nel textarea
   non le attivi due volte (stopPropagation se serve).

## Test

Vitest su `LightweightSession`: ⌘+Invio e Ctrl+Invio inviano una volta; Invio da solo non invia e
lascia il testo; con campo vuoto ⌘+Invio non invia; idem per il commento.
