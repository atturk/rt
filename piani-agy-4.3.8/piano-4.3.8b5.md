# Piano 4.3.8b5 — trascinamento delle immagini

Base: `claude/rt-4.3.8` (4.3.8b4). Branch: `agy/4.3.8b5`. Un commit per voce («4.3.8b5: N. …»).
Alla fine scrivi `piani-agy-4.3.8/esito-b5.md` (una riga per voce: fatta / non fatta e perché) e fai push sullo stesso branch.
Solo codice e test unitari (vitest/pytest): le verifiche visive e Playwright le fa Claude in revisione.

File principali: `frontend/src/components/lesson/panels/MediaGallery.tsx` (pannello Media/Arricchimento, drag `RT_MEDIA_DRAG_TYPE`),
`frontend/src/components/lesson/lessonImages.ts` (drop nell'editor, `removeImagesFromDocument`, `moveDocumentImage`),
`frontend/src/components/lesson/imageSections.ts` (`SectionImageDrag` con `fromUnit`/`fromText`: identifica la singola occorrenza),
la striscia degli allegati di unità (graffetta con numero e miniature sotto il titolo dell'unità).

## 1. Anteprima di trascinamento piccola e staccata dal cursore
Oggi l'anteprima è la miniatura grande sotto il cursore: copre il punto di rilascio (graffetta delle unità, titoli delle sezioni).
- Anteprima personalizzata per ogni drag di immagini (dal pannello Media e dalla striscia allegati): miniatura piccola (circa 64-72 px di larghezza, angoli arrotondati, bordo e ombra leggeri).
- Spostata in basso a destra del cursore di circa 16-20 px (`setDragImage(el, -offsetX, -offsetY)` con offset negativi, così il cursore resta libero sopra il bersaglio). Se in WebKit gli offset negativi non funzionano, usa un'anteprima trasparente (1×1) e un elemento `position: fixed; pointer-events: none` che segue `dragover`/`drag` a livello di documento; lo togli in `dragend` e `drop`.
- L'evidenziazione del bersaglio (unità/graffetta sotto il cursore) resta quella di oggi.

## 2. Togliere UNA sola occorrenza trascinandola fuori
Oggi, se la stessa immagine è due volte negli allegati di un'unità, non si può toglierne una sola.
- Ogni miniatura nella striscia allegati è trascinabile e il drag porta la sua occorrenza precisa (`SectionImageDrag` con `fromUnit` e `fromText` = posizione della riga nel documento).
- Rilasciandola sul pannello Media (la colonna di destra, tutta l'area del pannello è bersaglio, con evidenziazione e testo «Rilascia per togliere dall'unità») si rimuove SOLO quella riga del documento. Le altre occorrenze, anche della stessa immagine nella stessa unità o in altre unità, restano.
- Nuova funzione in `lessonImages.ts`, per esempio `removeImageOccurrence(view, { name, fromText })`, che toglie la sola riga che inizia in `fromText`. Prima controlla che lì ci sia davvero quell'immagine (il documento può essere cambiato); se non c'è, non fa niente. Annullabile con Cmd+Z come le altre modifiche.
- `removeImagesFromDocument` (togli tutte) resta per i comandi che lo usano oggi.
- Test vitest: due occorrenze uguali nella stessa unità più una in un'altra unità → ne resta due.

## 3. Selezione multipla nel pannello Media e trascinamento di gruppo
- Nel pannello Media si selezionano più immagini con Cmd/Ctrl+clic (aggiunge o toglie) e Maiusc+clic (intervallo). Il clic semplice fa quello che fa oggi. Esc o clic sul vuoto svuota la selezione. Le selezionate hanno il bordo evidenziato come lo stato selezionato di oggi.
- Trascinando una selezionata si trascinano tutte le selezionate, nell'ordine del pannello. Trascinando una non selezionata si trascina solo quella, e la selezione resta com'è.
- Il payload `RT_MEDIA_DRAG_TYPE` diventa una lista; il drop accetta ancora il formato singolo di oggi. Il drop nell'editor e sulla graffetta inserisce tutte le immagini nello stesso punto, nell'ordine, in una sola transazione: un solo Cmd+Z le toglie tutte.
- Anteprima di gruppo: come la voce 1, ma con 2 o 3 miniature sfalsate a mazzo e un badge con il numero (es. «5»).
- Test vitest: payload multiplo, ordine, una sola transazione, compatibilità con il payload singolo.

## Fuori piano
Nessun cambio al backend, al formato Markdown delle immagini o alla guida (`docs/guida/*.md` non si tocca).

## 4. Slide dei pptx disegnate davvero (Mac)
Caso reale: un pptx di 28 slide fatte di caselle di testo e forme (non immagini). Sul Mac `_quicklook_slides` in `rt/core/materials.py`
non ottiene 28 pagine da `qlmanage -p` (produce una cartella .qlpreview con Preview.html e allegati, non le slide) e RT ripiega sulle
immagini incollate: loghi, spunte da 15×18 px, icone, più immagini per pagina, riquadri «?». Il testo invece è corretto.
- Ordine di resa delle slide: LibreOffice se installato (come oggi su Windows/Linux) → su macOS Keynote se installato
  (`osascript`: apri il pptx, esporta in PDF in una cartella temporanea, chiudi senza salvare; timeout come oggi) → Quick Look → niente.
  Una resa vale solo se dà esattamente il numero di slide (regola di oggi).
- Ripiego sulle immagini incollate: scarta le immagini piccole (lato minore < 64 px oppure area < 2% della slide) e quelle che non si
  decodificano; al massimo una per slide, la più grande. Una slide senza immagini utili non ha immagine (niente «?»).
- Nel log del worker una riga chiara quando la resa delle slide non riesce e con quale metodo ci si è provato.
- Test pytest con `subprocess.run` simulato: ordine dei metodi, conteggio pagine, filtro delle immagini piccole. Claude prova Keynote/Quick Look sul MacBook Pro.

## 5. PDF della lezione: elenchi puntati e numerati
In `frontend/src/components/lesson/PrintLessonPage.tsx` mancano gli stili degli elenchi (il reset di Tailwind toglie pallini e numeri):
aggiungi per `.print-page ul` `list-style: disc` e per `ol` `list-style: decimal`, con rientro (`padding-left: 1.4em`) e un piccolo
spazio tra le voci; elenchi annidati con `circle`. Test vitest sullo stile o sul markup se esiste già un test della pagina.

## 6. Formule: `\mathrm` mangiato dagli escape
Caso reale nel testo rielaborato: `$athrm{Ca^{2+}}$` (doveva essere `$\mathrm{Ca^{2+}}$`). In `rt/core/encoding.py`, dentro le formule,
rimetti `\m` davanti a `athrm{`, `athbf{`, `athit{`, `athcal{`, `athbb{`, `athsf{` quando non sono preceduti da una lettera o da `\`.
Test pytest in quelli di `repair_latex_escapes`.

# Seconda tornata (dopo l'esito delle voci 1-6)
Già fatti da Claude su questo branch: il player che saltava a lato del puntatore all'inizio del trascinamento
(doppio -50% tra classe Tailwind `-translate-*` e `transform` inline) e «Rileggi l'unità» del ripasso che ora apre lo Studio
(`/studio/lezione/:id?unita=…`). Non toccarli.

## 7. Studio: cambiare unità con il player aperto
In `frontend/src/components/study/Study.tsx` (`onKeyDown`, ramo `ArrowLeft`/`ArrowRight`): con il player aperto le frecce restano
±5 s; **Option+frecce** (Alt+frecce su Windows) cambiano unità come le frecce a player chiuso (`navigateReading(±1)`), anche a player chiuso.
- La scorciatoia è personalizzabile in Impostazioni → Editor e scorciatoie, con lo stesso meccanismo delle altre (registrazione del tasto,
  conflitti, ripristino): due comandi «Unità precedente» / «Unità successiva» del gruppo Studio, predefiniti `Alt-ArrowLeft` / `Alt-ArrowRight`.
  Se il meccanismo di `editorCommands` è legato all'editor, aggiungi il gruppo Studio nella stessa sezione senza duplicare il codice di registrazione.
- Non attivarla mentre si scrive in un campo di testo o in un menu (stessa guardia delle frecce di oggi).
- Test vitest: con player aperto Alt+→ cambia unità e → sposta l'audio di 5 s; scorciatoia personalizzata rispettata.

## 8. Studio: il player segue l'unità
Quando l'unità cambia (frecce, scorciatoia, puntini, indice) e il player è aperto, l'audio va al timestamp d'inizio della nuova unità
(lo stesso usato all'apertura del player). Se stava suonando continua a suonare, se era in pausa resta in pausa.
- Impostazione «Il player segue l'unità» (attiva di predefinito) in Impostazioni → Aspetto e lettura, sezione dello Studio, salvata con
  `usePreference` come le altre preferenze dello Studio. Spenta: il player non si sposta cambiando unità.
- Unità senza timestamp: non spostare l'audio.
- Test vitest: cambio unità con preferenza attiva (seek all'inizio) e spenta (nessun seek).

# Terza tornata (dopo l'esito delle voci 7-8)
Già fatti da Claude su questo branch, non toccarli: colore degli stati personalizzati nei puntini dello Studio, tasti P (player) e L
(lettura veloce) indicati nei tooltip, nome dello stato personalizzato salvato con Invio o all'uscita dal campo (prima salvava a ogni tasto).

## 9. Impostazioni: ordine degli stati con il trascinamento
In `frontend/src/components/settings/StudyStatusesSection.tsx` togli le frecce «Sposta su/giù» e ordina le righe trascinandole
(maniglia `GripVertical` a sinistra; tutta la riga si trascina dalla maniglia, non dai campi). Stesso stile di trascinamento HTML5 già usato
in `frontend/src/components/lessons/AudioOrder.tsx`, niente librerie nuove. Linea d'inserimento visibile durante il trascinamento,
salvataggio con `persist(statuses, newOrder)` solo al rilascio. Da tastiera: maniglia focalizzabile, Alt+↑/↓ sposta la riga (accessibilità).
- Test vitest: trascinamento di una riga (dragStart/dragOver/drop) salva il nuovo ordine; Alt+↓ sulla maniglia sposta di una posizione.
