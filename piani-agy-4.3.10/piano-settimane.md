# Piano agy: selezione di più settimane nel calendario (P13)

Base: main (104f9d1). Prima di tutto: `git pull` di questo branch. Solo codice e test vitest, niente Playwright.
Wireframe: tavola «Calendario · selettore settimane» in https://claude.ai/artifact/MSSWwtvcprkVENUsUYiCMr.

File: `frontend/src/components/calendar/WeekRangePopup.tsx`, `WeekYearGrid.tsx`, `weekRange.ts` (+ test), `frontend/src/routes/calendar.tsx` (~465, `rangeEdit`).

## Oggi
Nel popup «Intervallo di settimane» si clicca la prima e poi l'ultima settimana: solo un intervallo continuo, e
non si capisce che servono due clic.

## Da fare

1. Selezione come nelle app di foto (solo in modalità intervallo, non in `navigate`):
   - **clic** su una settimana: seleziona solo quella (azzera le altre);
   - **clic e trascina** (pointerdown → pointerenter sulle celle → pointerup): seleziona tutte le settimane tra quella di partenza e quella sotto il
     puntatore, aggiornando dal vivo; `setPointerCapture`/`touch-action:none` perché funzioni anche col trackpad e su iPad;
   - **⌘+clic** (Ctrl+clic su Windows, `event.metaKey || event.ctrlKey`): aggiunge o toglie una sola settimana senza perdere le altre;
   - **⇧+clic**: seleziona l'intervallo dall'ultima settimana scelta (àncora) a quella cliccata, aggiungendolo alla selezione;
   - tastiera: frecce spostano il focus, Spazio/Invio = clic, con ⇧/⌘ come sopra.
2. Stato: `selected: Set<string>` (lunedì ISO) + `anchor`. Helper in `weekRange.ts`: `toggleWeek`, `rangeBetween(a, b)`,
   `contiguousRuns(selected) -> WeekRange[]` (ordinate, `to` esclusivo come oggi).
3. Aspetto: settimane selezionate in verde pieno (colore primario, testo bianco); sotto la griglia il conteggio
   «N settimane selezionate» (singolare «1 settimana selezionata»), anche nell'`aria-live` che c'è già.
4. Accanto a X e spunta un pulsante «?» con tooltip (stesso componente tooltip del resto dell'app):
   «Clic: una settimana · Trascina: più settimane di seguito · ⌘+clic: aggiungi o togli una settimana · ⇧+clic: dall'ultima scelta a questa»
   (su Windows «Ctrl+clic»; usare l'helper di piattaforma esistente per ⌘/Ctrl, se c'è).
5. Conferma: `onConfirm` riceve `WeekRange[]` (le corse continue). In `routes/calendar.tsx` la modifica «intervallo» si applica a ogni corsa
   (stesse chiamate di oggi, una per corsa, in sequenza) e il testo di conferma/riepilogo usa `weekRangeLabel` di ognuna unito da «, ».
   `initial` (WeekRange singolo) resta accettato e diventa la selezione iniziale. La modalità `navigate` resta identica (un clic = vai).
6. Test vitest: clic singolo, trascinamento 49→52, ⌘+clic aggiunge e toglie, ⇧+clic dall'àncora, contiguousRuns con buchi,
   conteggio, tooltip «?», onConfirm con due corse, navigate invariato.

## Sovrapposizioni
Il thread della beta fa da sé P14/P15/P16 sulla barra di modifica del calendario (ordine icone, matita→X, settimana vuota già in modifica):
probabile piccolo conflitto in `routes/calendar.tsx`, nessuno in `WeekRangePopup`/`WeekYearGrid`.
