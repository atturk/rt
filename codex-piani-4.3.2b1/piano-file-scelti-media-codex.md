# Piano per Codex · 4.3.2b1 · File scelti in "Aggiungi PDF o foto"

Base: branch della beta 4.3.2 (creato dalla 4.3.1 stabile). File: `frontend/src/components/lesson/panels/EnrichmentPanel.tsx` e il suo test `EnrichmentPanel.test.tsx`.

## Il bug (segnalato da Attilio)
In Arricchimento › Media della lezione › "Aggiungi PDF o foto", dopo aver scelto un file il pulsante dice "Carica (1)" ma il campo mostra "Choose Files / no files selected" e il file non compare da nessuna parte.

## Cause
1. Il campo è un `<Input type="file">` nativo. Nell'`onChange` il codice chiama `chooseUploadFiles(...)` e poi `e.target.value = ''` (serve per poter riscegliere lo stesso file e per sommare scelte successive). Così il campo nativo torna subito a "no files selected", e la lista vera (`uploadFiles`) non viene mostrata da nessuna parte. Anche i file trascinati sul riquadro o sul pannello (evento media-drop) finiscono solo in `uploadFiles`, invisibili.
2. Annulla e la X chiudono la scheda (`setOpenUpload(false)`) ma non svuotano `uploadFiles` né `uploadError`: riaprendo la scheda il pulsante dice ancora "Carica (N)" con file scelti in precedenza, e caricandoli si mandano file che l'utente credeva scartati.

## Cosa fare
Seguire lo stesso schema di `NewLessonDialog.tsx` (input file `hidden` + interfaccia propria):

1. Sostituire l'`<Input type="file">` visibile con un `<input type="file" hidden multiple accept={ACCEPT} aria-label="PDF o foto">` tenuto in un `useRef`, con lo stesso `onChange` di oggi (incluso `value = ''`).
2. Al suo posto mostrare un pulsante `Button size="sm" variant="outline" type="button"` con icona `Upload` e testo "Scegli file" (se `uploadFiles` è vuoto) oppure "Aggiungi altri" (se non è vuoto), che chiama `ref.current?.click()`. Accanto, se la lista è vuota, un testo `text-meta text-muted-foreground`: "oppure trascinali qui".
3. Sotto il pulsante, quando `uploadFiles.length > 0`, una lista (`<ul aria-label="File scelti">`) con una riga per file: icona (`FileText` per PDF, `Image` per immagini, da lucide-react), nome troncato (`truncate`, `title` col nome intero), dimensione leggibile (KB/MB, una cifra decimale) e una `IconButton` "Rimuovi <nome>" con icona `X` che toglie quel file da `uploadFiles` (per indice). Stile coerente con il resto della scheda: `rounded-md border border-border/60 bg-muted/30 px-2 py-1 text-meta`, `max-h-40 overflow-y-auto` per molte pagine.
4. Creare una funzione `closeUpload()` che fa `setOpenUpload(false)`, `setUploadFiles([])`, `setUploadError(null)`, e usarla per Annulla e per la X della scheda. Anche il pulsante `Upload` nell'intestazione, quando chiude la scheda (cioè `openUpload` era true), deve svuotare allo stesso modo. Aprire la ricerca web chiude la scheda: anche lì svuotare.
5. Non cambiare `chooseUploadFiles`, il drop, l'invio (`handleUploadSubmit` svuota già dopo il successo) né il testo del pulsante "Carica (N)".

## Test (vitest, in EnrichmentPanel.test.tsx)
- Scegliendo un file con `fireEvent.change` sull'input "PDF o foto", il nome del file compare nella lista "File scelti" e il pulsante dice "Carica (1)".
- "Rimuovi <nome>" toglie il file e il pulsante torna a "Carica" disabilitato.
- Un file trascinato sulla scheda (`fireEvent.drop` con `dataTransfer.files`) compare nella lista.
- Scegliere un file, premere Annulla, riaprire la scheda: lista vuota, "Carica" disabilitato.
- Il test esistente "apre la scheda di caricamento e di ricerca web" deve restare verde.

Comandi: `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run src/components/lesson/panels/EnrichmentPanel.test.tsx`.

## Changelog
Voce nella sezione 4.3.2b1 di `CHANGELOG.md`, in italiano semplice: "Aggiungi PDF o foto mostra i file scelti, uno per riga, e si possono togliere prima di caricare. Annulla ora scarta i file scelti."
