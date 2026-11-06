# Esito Piano Condivisione e 4.3.8b4

1. Fatta: eliminati link invisibili `<a download>`, centralizzato il salvataggio in `saveFile` e `fetchExport` in `fileExport.ts` con revoca ritardata del blob URL.
2. Fatta: barra di stato `FileStatusBar` durante la preparazione ("Preparo…", bottone "Salva" o errore in rosso) con esclusione mutua da altre barre fisse.
3. Fatta: `shareFile` in `fileExport.ts` (Web Share API, fallback zip per `.rt` su iOS, gestione `AbortError`/`NotAllowedError`) e ponte nativo macOS `DesktopApi.condividi` in `rt/window.py` (verificato che WKWebView pywebview non supporta `navigator.canShare` con file).
4. Fatta: voci menu Esporta aggiornate a «Lezione (.rt)», «Solo le fonti (zip)», «Condividi PDF», «Condividi lezione», e sostituiti i riferimenti visibili all'utente da zip a lezione.
5. Fatta: rimossa la barra in basso «Genera» in Studio; inserito il bottone `Brain` nella barra in alto («Domande su questa unità · D») che apre direttamente il ripasso dell'unità corrente.
6. Fatta: player audio ancorabile in tre posizioni (basso, sinistra, destra) tramite trascinamento dai bordi con sagome tratteggiate di aggancio, layout verticale compatto sui lati e preferenza dispositivo in `rt-device:audio-pos`.
7. Fatta: eliminato CSS `zoom` sull'html; su desktop bridge nativo `DesktopApi.set_zoom` (`WKWebView.setPageZoom_` su macOS, `ZoomFactor` WebView2 su Windows), su browser scala la font di base (`fontSize` della radice); barre fisse protette.
8. Fatta: rimosso il pulsante ▶ dell'unità nella barra di Studio; stato aperto/chiuso del player memorizzato per dispositivo in `rt-device:study-audio-open` e all'apertura parte dall'inizio dell'unità se non già in riproduzione.
9. Fatta: calcolato `sameTeacher` in `lessonNeighbors.ts` (stesso docente = stesso nome e stessa materia, minuscole e spazi ignorati, ordine cronologico; disattivato senza docente) e aggiunta riga con icona `User` nel salto lezione in Studio e pagina lezione.
10. Annullata: da piano non richiede modifiche al codice; docenti con lo stesso nome in materie diverse sono gestiti naturalmente dalla regola di corrispondenza per materia della voce 9.
