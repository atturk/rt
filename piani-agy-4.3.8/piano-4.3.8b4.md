# Piano 4.3.8b4 (oltre a piano-condivisione.md)

Base: `agy/4.3.8-condivisione` (= v4.3.8b3 + piano condivisione). Una voce per commit, dopo le voci 1-4 di `piano-condivisione.md`. Non modificare il testo di `docs/guida/*.md`.

## 5. Studio: via il blocco «Genera», bottone domande nella barra in alto

- In Studio il player audio (voce 7 della b3) finisce sopra il blocco in basso con «Genera»/«Genera altre»/«Ripassa l'unità»: **togli tutta quella barra in basso** (anche nella lettura veloce e in zen, se c'è lo stesso blocco).
- Al suo posto un **bottone con l'icona del cervello** (la stessa già usata per le domande, `Brain` di lucide) nella barra in alto, **subito accanto al bottone cuffie** (a sinistra o a destra, coerente con gli altri). Tooltip: «Domande su questa unità».
- Il bottone apre direttamente la schermata domande **della sola unità aperta** (lo stesso ripasso per unità di oggi). Se non ci sono domande per l'unità, in quella schermata l'utente le genera da lì (il blocco «Genera» con numero e tipi che c'è già nel ripasso vuoto). Tornando indietro si torna all'unità di Studio da cui si era partiti.
- Se esisteva una scorciatoia da tastiera per «Ripassa/Genera» sull'unità, la tieni sul nuovo bottone.
- Aggiorna i test e2e/vitest che cercano i quattro pulsanti tondi o «Genera altre» in Studio (es. `study.spec.ts` «quattro pulsanti tondi…», «finite le domande dell'ultima unità…»): ora devono passare dal bottone cervello.

## 6. Player audio spostabile (in basso, a sinistra, a destra)

- Il player di Studio si può **ancorare in tre posizioni**: in basso al centro (come ora), sul **lato sinistro** o sul **lato destro**, a metà altezza della pagina. Nei lati il player è verticale/compatto (play, tempo, velocità, ±5 s) e non copre il testo (il testo resta centrato; se lo spazio laterale è troppo poco, es. finestra stretta o telefono, resta solo «in basso»).
- Si sposta **solo trascinandolo**: si afferra dai bordi/dallo sfondo del blocco (non dalla barra del tempo, che deve continuare a trascinarsi per cercare nell'audio, né dai bottoni). Durante il trascinamento compaiono i tre punti di aggancio (sagome tratteggiate in basso, a sinistra, a destra); al rilascio il player va all'aggancio più vicino con una breve animazione. **Nessun menu «Sposta».** Con la tastiera: nessun comando dedicato (resta in basso, va bene così).
- La posizione si ricorda per dispositivo (impostazione locale, come lo zoom).
- Vale anche per il player della pagina lezioni se usa lo stesso componente; se no, solo Studio.
- Test vitest: trascinamento con rilascio vicino a un lato → ancorato a quel lato; trascinare la barra del tempo non sposta il player; posizione ricordata; su schermo stretto solo «in basso».

## 7. Zoom (Ingrandisci/Riduci) che rompe il disegno della pagina

- Oggi `frontend/src/lib/zoom.ts` usa `document.documentElement.style.zoom`. Nell'app Mac (WKWebView), nella pagina lezione con zoom diverso da 100 %, scorrendo il testo viene disegnato solo nella parte alta e poi scompare (screenshot di Attilio). È il CSS `zoom` sull'intera pagina.
- Correggi così:
  - **App desktop**: usa lo zoom nativo della finestra invece del CSS. macOS: `WKWebView.setPageZoom_` (macOS 11+) via pyobjc in `rt/window.py`; Windows: `ZoomFactor` del controllo WebView2. Esponi in `DesktopApi` un metodo `set_zoom(fattore)` e fai chiamare quello da `zoom.ts` quando c'è il ponte desktop. Fattore e limiti come oggi; persistenza come oggi.
  - **Browser** (web app, iPhone): niente `zoom` sull'`<html>`; scala la dimensione del testo di base (`font-size` della radice, l'interfaccia è in rem) oppure lascia lo zoom del browser (⌘+/⌘−) e nascondi i comandi interni. Scegli la via che non rompe i layout esistenti e dillo nell'esito.
  - Aggiorna `zoomed(px)` e chi lo usa, se la scala cambia significato.
- **Non deve sparire niente**: con lo zoom nativo la finestra «diventa» più piccola in px CSS, quindi bottoni e barre fissate in basso (player, barra della lettura veloce, bottoni del ripasso, barra di selezione in Lezioni) devono restare visibili e cliccabili. Verifica con Playwright simulando lo zoom nativo (viewport ridotto di 1/fattore, `deviceScaleFactor` = fattore) a 80 %, 125 %, 150 % e 200 % su: Lezioni, pagina lezione (scorrendo fino in fondo), Studio (anche zen e lettura veloce), Ripasso, Impostazioni, Guida; desktop e 390 px. Se una pagina non regge, correggi il layout di quella pagina (non tornare al CSS `zoom`). Salva le schermate in `frontend/test-results/zoom/` (non committarle) e scrivi nell'esito cosa hai controllato.
- Test: vitest su `zoom.ts` (ponte desktop chiamato, nessuno stile `zoom` sull'html); test Python per `set_zoom` con webview finto; un e2e `zoom.spec.ts` che a 150 % e 200 % (simulati come sopra) controlla che i bottoni in basso di Studio e Ripasso siano nel viewport e cliccabili. La verifica sul Mac vero la fa Attilio sulla beta.

## 8. Studio: via il bottone ▶ dell'unità, player che ricorda se era aperto

- Togli dalla barra in alto di Studio il bottone ▶ «Audio della lezione per questa unità» (`Study.tsx`, componente che usa l'icona `Play` e i timecode dell'unità). Per ascoltare l'utente apre il player (cuffie) e preme play. Se il player, aprendolo, può partire dall'inizio dell'unità aperta (come faceva il ▶), tienilo: posizione iniziale = timecode dell'unità solo se l'audio non è già in riproduzione.
- Il player di Studio aperto/chiuso si ricorda **in modo persistente per dispositivo** (non più solo per sessione, cambia la voce 7 della b3): entrando in Studio è aperto se l'utente l'aveva lasciato aperto, chiuso altrimenti. Predefinito: chiuso.
- Aggiorna i test che cercano il bottone ▶ dell'unità.

## 9. Salto alla lezione dopo/prima dello stesso docente

- `components/shared/LessonJump.tsx` (blocco laterale con calendario → e etichetta →, usato in Studio e nella pagina lezione): aggiungi una terza riga con **la stessa icona docente già usata in Lezioni** (`User` di lucide, vedi `GROUP_ICONS.docente` in `LessonsView.tsx`; niente icone nuove per il docente) per la lezione **dello stesso docente** precedente/successiva in ordine cronologico (data della lezione, poi l'ordine già usato per lo stesso giorno). Stesso docente = **stesso nome e stessa materia** (nomi confrontati senza maiuscole e spazi ai bordi): due «Rossi» di materie diverse sono due docenti diversi, quindi dalla lezione di Fisiologia del prof. Rossi si va alla lezione successiva di Rossi in Fisiologia, mai a quella di un Rossi di un'altra materia. Lezione senza docente: riga disattivata con «nessun docente per questa lezione».
- Calcolo in `lib/lessonNeighbors` accanto a `sameDay` e `sameSubject` (`sameTeacher`). Il blocco deve esserci sia in Studio sia nella pagina lezione: se oggi manca in uno dei due, aggiungilo.
- Test vitest per `sameTeacher` (ordine, docente vuoto, maiuscole, due «Rossi» in materie diverse con lezioni alternate) e aggiorna gli e2e del salto.

## 10. (annullata) Docenti con lo stesso nome

- Nessun controllo nuovo: due docenti con lo stesso nome in materie diverse sono ammessi (nella stessa materia resta il rifiuto di oggi). Il caso dei nomi uguali è risolto dalla regola «stesso nome e stessa materia» della voce 9.

## Prima della PR

Quella di `piano-condivisione.md` più:
- `python -m pytest tests/ -q -n auto --dist loadfile -p no:cacheprovider`
- `cd frontend && npm run -s typecheck && npm run -s lint && npx vitest run`
- `npm run build` e poi `npx playwright test e2e/study.spec.ts e2e/lesson-view.spec.ts e2e/settings.spec.ts` (gli e2e usano `frontend/dist`: senza build provano la versione vecchia).
