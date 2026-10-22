# Piano 1 · Immagini nell'editor: trascinamento, clic, sezione della graffetta

Richiesta di Attilio del 22/10/2026, sulla 4.3.3b3. Riguarda l'anteprima modificabile della lezione
(CodeMirror con atomic-editor). Cinque punti, un commit ciascuno.

## 1.1 Tremolio mentre si trascina un'immagine

**Sintomo.** Trascinando un'immagine sul testo, alcuni paragrafi saltano su e giù senza sosta. Nel
video, la riga della graffetta tratteggiata sotto i titoli compare e sparisce a ogni fotogramma, e la
linea blu di rilascio si sposta.

**Cause trovate** (da verificare riproducendo, poi correggere entrambe):

1. `lessonImages.ts`, gestore `dragleave`. Pulisce tutto (`clearDrag`) quando `event.relatedTarget`
   è nullo. In WebKit, cioè la finestra dell'app sul Mac, `relatedTarget` è sempre nullo nei
   `dragleave`. Così ogni passaggio fra due elementi interni toglie `rt-dragging-images`, e il
   `dragover` successivo lo rimette.
   Con la classe tolta, i pulsanti graffetta vuoti tornano `display: none` (`index.css`,
   `.rt-unit-images-button.empty`). Ogni riga titolo perde o guadagna 30 px, il testo sotto il
   puntatore cambia, e il ciclo ricomincia.
2. La linea di rilascio (`DropLineWidget`) è un widget a blocco alto 10 px (2 px più 4+4 di
   margine), ridisegnato a ogni `dragover`. Il testo si sposta sotto il puntatore, `posAtCoords`
   restituisce un'altra posizione, e la linea salta di nuovo.

**Correzione.**

- `dragleave` pulisce solo se il puntatore è davvero uscito dall'editor: coordinate fuori da
  `view.dom.getBoundingClientRect()`. In alternativa, pulizia rimandata di un frame e annullata dal
  `dragover` successivo. `drop` e `dragend` puliscono come oggi.
- La linea di rilascio non deve occupare spazio: altezza 0 nel flusso, con la riga disegnata da uno
  pseudo-elemento in posizione assoluta.
- Ridisegnare solo quando cambia il bersaglio: non spedire `setDropHighlight` se `insertAt` ed
  etichetta sono uguali a quelli correnti.

## 1.2 Rilascio sulla graffetta vuota

**Sintomo.** Se la sezione della graffetta di una sottounità è vuota, l'immagine trascinata sul
pulsante tratteggiato finisce nel testo sotto il titolo, non nella sezione. Se la sezione ha già
immagini, funziona.

**Causa probabile.** È la stessa del punto 1.1: il pulsante vuoto esiste solo mentre c'è
`rt-dragging-images`. Quando un `dragleave` toglie la classe, il pulsante sparisce proprio sotto il
puntatore e il `drop` arriva al testo. Dopo la correzione 1.1, verifica con un test e2e: trascina
un'immagine sul pulsante vuoto di una sottounità e controlla che il Markdown abbia la riga immagine
subito dopo il timecode, senza `#w=`, e che il pulsante mostri 1.

Se il test fallisce ancora, controlla `sectionDropTarget` e `formatImagesMarkdown(..., true)` per
una sezione senza immagini. La riga inserita deve essere riconosciuta da `imageSections`: dopo il
timecode, solo righe vuote prima.

## 1.3 Immagine della sezione mostrata anche in grande sotto la graffetta

**Sintomo.** Dopo la classificazione, le immagini assegnate dall'IA compaiono nella sezione della
graffetta, ma l'ultima compare anche a piena grandezza sotto. Lo stesso succede con la sezione
chiusa. Deve vedersi solo nella sezione.

**Causa.** atomic-editor disegna ogni immagine Markdown come widget a blocco subito dopo la sua riga
(`image-blocks.js`, `side: 1` su `line.to`). `lessonImageStrips` sostituisce le righe della sezione
con il proprio widget. L'immagine dell'ultima riga resta però fuori dall'intervallo sostituito e si
vede. Prima della b1 la nascondeva la regola `.cm-content > .rt-strip + .cm-atomic-image`
(`index.css`). Con la sezione nuova il widget ha la classe `rt-unit-images-section`, quindi la
regola non vale più.

**Correzione.** Nascondi `.cm-atomic-image` che segue `.rt-unit-images-section`, aperta o chiusa.
Fallo anche per `.cm-line.rt-strip-editing-line`. Togli le regole `.rt-strip` dell'editor rimaste
senza effetto.

Test: unità con due immagini di sezione, sezione chiusa e aperta. Nell'editor nessuna
`.cm-atomic-image` visibile per quei file.

Verifica anche il backend della classificazione: le immagini assegnate devono essere scritte una
sola volta, come righe di sezione (dopo il timecode, senza `#w=`), mai anche nel testo.

## 1.4 Clic, doppio clic e tenere premuto sulle immagini nel testo

Comportamento richiesto, per le immagini nel testo (con `#w=`) dell'anteprima modificabile:

| Gesto | Effetto |
|---|---|
| Un clic | Pannello arricchimento chiuso: si apre il visore a galleria (`rt-image-viewer-open`, come `handleImageClick`). Pannello aperto: l'immagine viene portata al centro del pannello con l'animazione del punto 1.5 (`rt-media-select`). |
| Doppio clic | Si mostra il Markdown della riga: il cursore va sulla riga sorgente, come fa oggi il clic semplice. |
| Tenere premuto e spostare | Trascinamento: l'immagine si sposta in un altro punto del testo o nella sezione della graffetta, anche di un'altra sottounità (`RT_SECTION_IMAGE_DRAG_TYPE` con `fromText`). |

Oggi le immagini sono disegnate da atomic-editor (`.cm-atomic-image`). Il suo `mousedown` sposta
il cursore sulla riga sorgente, e un clic accanto all'immagine mostra il Markdown.
`LessonImageWidget` (`lessonUnits.ts`) copre solo le didascalie con parentesi quadre.

Indicazioni:

- Un gestore `mousedown` sull'immagine, a priorità alta (`Prec.highest(EditorView.domEventHandlers)`
  oppure in cattura su `view.dom`), con `preventDefault`. Così il cursore non si sposta e il Markdown
  non compare al primo clic, e il trascinamento nativo resta possibile (`img.draggable = true`, come
  in `attachResizeHandles`).
- Clic singolo rimandato di circa 250 ms e annullato da un `dblclick`. Il doppio clic mette il
  cursore sulla riga sorgente: stessa logica di atomic-editor, `posAtDOM(wrap) - 1`.
- Un trascinamento non deve aprire il visore.
- Le maniglie di ridimensionamento restano come sono.
- Su touch: tocco singolo uguale al clic. Il doppio tocco può restare al comportamento attuale.
- Le immagini nella sezione della graffetta hanno già clic e trascinamento (`imageStripDOM.ts`):
  allinea il clic singolo alla stessa regola sul pannello, se non lo fa già.

Test: unità per i tre gesti. Un e2e per il clic con pannello chiuso (si apre il visore) e per il
doppio clic (compare il testo `![` nella riga).

## 1.5 Animazione di selezione nel pannello arricchimento

**Oggi.** `rt-media-flash` (`index.css`, `@keyframes rt-media-pulse`) anima un `box-shadow` verde
attorno alla cella. Il riquadro resta dietro la cella vicina ed è un rettangolo poco bello.

**Richiesta.** L'immagine si ingrandisce leggermente e torna alla misura normale, con un effetto
molla ma senza rimbalzo:

- `transform: scale(1)` → `scale(1.06)` → `scale(1)`, circa 450 ms;
- curva morbida (per esempio `cubic-bezier(.2,.8,.2,1)`) e nessun valore sotto 1;
- niente `box-shadow` né contorni;
- con `prefers-reduced-motion: reduce`, nessuna animazione.

Lo scorrimento porta la cella al centro **del pannello**: scorri il contenitore del pannello, non la
pagina. `scrollIntoView` su un elemento annidato può far scorrere anche il documento: verifica e, se
serve, calcola lo `scrollTop` del contenitore.

L'animazione va applicata all'immagine o alla cella senza essere tagliata dall'`overflow` dei
contenitori: se viene tagliata, anima l'`img` dentro la cella.

Test: unità su `flashAndScroll`, che aggiunge e poi toglie la classe senza toccare lo scroll della
finestra.
