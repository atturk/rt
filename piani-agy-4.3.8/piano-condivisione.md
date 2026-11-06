# Piano: salvataggi che funzionano su iPhone + «Condividi PDF» / «Condividi lezione»

Base: `claude/rt-4.3.8`. Branch: `agy/4.3.8-condivisione`. Un commit per voce («Condivisione: <n>. <titolo>»).

## Diagnosi (fatta da Claude, 2026-11-06)

Test di Attilio su iPhone (RT aperto dall'icona nella schermata Home, quindi come web app, via Tailscale):
- «Tutti i dati (zip)» non fa nulla di visibile.
- «PDF» dopo molto tempo apre il PDF nel visore di iOS; nel frattempo nessun segnale.

Cause nel codice:
1. Markdown, «Tutti i dati (zip)», «Solo le fonti (zip)» sono `<a href download>` verso un URL con `Content-Disposition: attachment` (`LinkMenuButton` in `components/ui/menu.tsx`, voci in `routes/lessons.tsx` `LessonHeaderActions`). Nella web app di iOS un link così non mostra niente. Il PDF invece passa da `fetch` + blob + `link.click()` e infatti arriva (nel visore).
2. Nessun feedback: lo stato del PDF (`pdf.busy`) si vede solo come voce disabilitata «Preparo il PDF» dentro il menu, che si è già chiuso. Lo zip non ha nemmeno quello.
3. `URL.revokeObjectURL` subito dopo `link.click()` (lessons.tsx, DetailsPanel, ImportConflicts, LessonEditor, CalendarScheduleSettings): su Safari può annullare il download. Va revocato dopo (es. 60 s).
4. Esporta di gruppo (`LessonsView.tsx`): a job finito fa `click()` su un `<a download>` da codice, senza gesto dell'utente: su iOS non parte.

## 1. Un solo modo di salvare un file

Nuovo `frontend/src/lib/fileExport.ts`:
- `fetchExport(url): Promise<File>`: `fetch` con `credentials: 'same-origin'`; se `!ok` legge `error.message` dal JSON (come fa oggi `exportPdf`); nome dal `filename*=UTF-8''` di Content-Disposition (fallback `filename="..."`); tipo dal `Content-Type`.
- `saveFile(file: File)`: `<a>` con `href = URL.createObjectURL(file)`, `download = file.name`, aggiunto al `document.body`, `click()`, poi rimosso; `revokeObjectURL` dopo 60 s (`setTimeout`).

Usarlo ovunque oggi c'è blob + click o `<a download>` verso l'API: voci Esporta della lezione (Markdown, PDF, lezione, fonti), `LessonsView` (esporta di gruppo: niente più click automatico da codice; a job finito il messaggio di stato ha il bottone «Salva»), `DetailsPanel.downloadAndRestore`, `ImportConflicts.downloadLessonCopy`, `LessonEditor.downloadAndRestore`, `CalendarScheduleSettings`. Le voci del menu diventano `onSelect` (non più `href`).

## 2. Stato visibile durante la preparazione

Nuovo componente `components/ui/file-status.tsx` + piccolo store (modulo con `useSyncExternalStore`, come `lib/phone.ts`; niente librerie nuove), montato una volta nel layout dell'app. Barra fissa in basso (sul telefono sopra la barra a schede), `role="status"` `aria-live="polite"`:
- «Preparo il PDF…» / «Preparo la lezione…» / «Preparo le fonti…» con spinner, dal momento del tocco;
- a file pronto: «PDF pronto» con il nome, si chiude da sola dopo 4 s;
- errore: messaggio in rosso, resta finché non si tocca la ×.
Se la preparazione dura più di 1,5 s o si è su iPhone (vedi voce 3), il salvataggio non parte da solo: la barra mostra il bottone «Salva» (e «Condividi» se è una condivisione). Motivo: iOS accetta il salvataggio/la condivisione solo subito dopo un tocco; dopo un'attesa lunga serve un tocco nuovo.
L'avviso sotto il menu (`pdf.error` in `LessonHeaderActions`) si toglie: lo fa la barra.

## 3. Condividi PDF / Condividi lezione (menu di sistema)

Solo due voci nuove nel menu Esporta della lezione, sotto quelle di salvataggio: «Condividi PDF» e «Condividi lezione» (file `.rt`, stesso URL di «Lezione», con lo stato di studio se la spunta è attiva). Niente sottomenu, niente bottoni per singole app: si apre il menu di condivisione del sistema.

`shareFile(file)` in `fileExport.ts`:
1. Web Share API: se `navigator.canShare?.({ files: [file] })` → `navigator.share({ files: [file], title: <titolo lezione> })`. `AbortError` (l'utente chiude il menu) = nessun messaggio. `NotAllowedError` (gesto scaduto) = la barra mostra «Condividi» e il tocco richiama `navigator.share`. Copre iPhone/iPad (Safari e web app), Android, Chrome/Edge su Windows e Mac, quindi anche la finestra Windows (WebView2).
2. App per Mac (pywebview, WKWebView): se `navigator.canShare` non c'è o rifiuta i file, e c'è `window.pywebview?.api?.condividi`, chiama `condividi(percorso_api)` (vedi sotto).
3. Altrimenti le due voci non compaiono (funzione `canShareFiles()` controllata al montaggio, con un `File` vuoto del tipo giusto).

Per «Condividi lezione» su iOS il tipo `.rt` potrebbe non essere accettato da `canShare`: se rifiuta, ritenta con lo stesso file e `type: 'application/zip'` (il nome resta `.rt`). Se rifiuta anche così, la voce non compare.

### Ponte nativo sul Mac (`rt/window.py`, `DesktopApi`)

`condividi(self, percorso_api: str) -> dict`:
- accetta solo percorsi che iniziano con `/api/v1/lessons/` e contengono `/export?`;
- scarica `self._base_url + percorso_api` con `Authorization: Bearer <token>` (token da `secrets_service.store().get(auth.TOKEN_SECRET)`, come «Copia token»), in una cartella temporanea `tempfile.mkdtemp(prefix="rt-condividi-")`, con il nome da Content-Disposition;
- sul thread principale (`AppHelper.callAfter`) apre `NSSharingServicePicker.alloc().initWithItems_([NSURL.fileURLWithPath_(path)])` e `showRelativeToRect_ofView_preferredEdge_` sulla `contentView` della finestra, in alto a destra (dove sta il bottone Esporta);
- la cartella temporanea si cancella alla chiusura dell'app (o la più vecchia di 1 giorno all'avvio);
- errori → `{"errore": "..."}`, mostrati dalla barra.
Il JS, prima di chiamarlo, mostra comunque «Preparo…» nella barra (la preparazione la fa Python, la barra si chiude quando la promessa torna).
Prima di scrivere il ponte, verifica nella smoke della finestra (`rt/_window_smoke.py`) se `navigator.canShare({files:[new File(['x'],'a.pdf',{type:'application/pdf'})]})` è `true` in WKWebView: se lo è, il ponte non serve e la voce 3.2 si salta (scriverlo nell'esito).

## 4. Nomi nel menu Esporta

`routes/lessons.tsx`, `LessonHeaderActions`:
- «Markdown» resta;
- «PDF» resta;
- «Tutti i dati (zip)» → «Lezione (.rt)»;
- «Solo le fonti (zip)» resta;
- «Condividi PDF», «Condividi lezione» (voce 3);
- «Includi lo stato di studio» resta in fondo (vale per «Lezione» e «Condividi lezione»).
Stessa sostituzione di «zip» → «lezione» nei testi per l'utente dove si parla del file `.rt` di una lezione (grep `zip` in `frontend/src` e `docs/guida/`, solo testi visibili; i nomi tecnici e l'archivio delle fonti restano).

## Prima della PR

- `cd frontend && npx vitest run` (aggiungere test per `fileExport.ts`: nome da Content-Disposition, errore JSON, revoke ritardato, `shareFile` con `canShare` falso/vero, `AbortError` silenzioso, `NotAllowedError` → bottone; e per le voci del menu).
- `npx playwright test e2e/lesson-view.spec.ts e2e/lessons-view.spec.ts --trace off` (aggiornare i test che cercano «Tutti i dati (zip)» o un `<a download>`).
- `pytest tests/test_desktop_window.py -q` (+ test di `condividi`: percorso non ammesso rifiutato, nome dal Content-Disposition, picker chiamato con il file giusto, con `webview` e AppKit finti).
- Niente test reali su iPhone: li fa Attilio sulla beta.
