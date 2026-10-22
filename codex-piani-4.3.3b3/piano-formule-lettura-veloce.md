# Piano 6 · Formule lunghe nella lettura veloce: adattate e centrate

Agente: da assegnare all'avvio della b3. Segnalazione di Attilio (22/10/2026): nella lettura veloce una
formula lunga (es. $Q = 10^{-6}\int_{-3}^{3}\int_{-3}^{3} 4y^2\,dx\,dy = \dots$) esce dallo schermo a
sinistra. Va ridotta e centrata **in base alla sua dimensione reale**, non con una riduzione fissa per
tutte le formule.

## Cosa c'è oggi

`frontend/src/components/study/SpeedReader.tsx`, `FormulaWord`: misura
`scale = min(1, container.clientWidth / rendered.scrollWidth)` e applica `transform: scale(...)`.
CSS in `frontend/src/index.css`: `.rt-rsvp-formula { display: grid; place-items: center; width: 100% }`,
`.rt-rsvp-math { white-space: nowrap; transform-origin: center }`; il genitore `.rt-rsvp-word` è
`display: flex` con `white-space: pre`, dentro un'area `flex-col items-center`.

## Causa probabile (da verificare per prima cosa)

La formula `nowrap` fissa la larghezza minima della griglia: `.rt-rsvp-formula` e `.rt-rsvp-word`
(elementi flex con `min-width: auto`) si allargano quanto la formula. Così `container.clientWidth`
è già largo quanto la formula, la scala resta 1 e il blocco più largo dello schermo, centrato,
sborda a sinistra. Riprodurre con un e2e (formula molto lunga, finestra 1280 e 390 px) prima di
correggere.

## Cosa fare

1. **Misurare contro lo spazio vero**: la larghezza disponibile è quella dell'area di lettura
   (`readingArea`, già un ref nel componente) meno un margine (es. 32 px per lato, 16 su telefono),
   non quella del contenitore della formula. Il contenitore non deve crescere con la formula:
   `min-width: 0` su `.rt-rsvp-word` quando c'è una formula, `grid-template-columns: minmax(0, 1fr)`
   e `overflow: visible` controllato sulla griglia.
2. **Larghezza naturale**: misurare la formula senza trasformazioni (`getBoundingClientRect` dello
   span con `transform` tolto, oppure `scrollWidth`/`offsetWidth`, che ignorano la trasformazione) e
   ricalcolare con `ResizeObserver` sull'area e sulla formula, dopo il caricamento dei font
   (`document.fonts.ready`).
3. **Anche l'altezza**: formule alte (integrali, frazioni impilate, matrici) non devono superare
   circa metà dell'altezza dell'area di lettura.
   `scale = min(1, larghezzaDisponibile / larghezza, altezzaDisponibile / altezza)`, con un minimo
   leggibile (es. 0,35): sotto il minimo si tiene il minimo e si permette lo scorrimento
   orizzontale **centrato** sull'inizio della formula, invece di tagliarla.
4. **Centratura**: la scala con `transform` non cambia lo spazio occupato. Dare al contenitore la
   larghezza e l'altezza già scalate (`width = larghezza × scala`, `height = altezza × scala`) con
   `transform-origin: top left` sullo span, così il box esterno coincide con quello visibile e il
   flex lo centra davvero. Niente scala per le formule che già entrano: restano alla dimensione del
   testo.
5. Stessa misura per le formule nel contesto prima/dopo (`speed-reader-before/after`) e nel riquadro
   del contesto: lì basta `max-width: 100%` con scorrimento orizzontale, senza scala.
6. Funzione pura testabile, per esempio `fitFormula({ width, height }, { width, height }, min)`, che
   restituisce la scala e la dimensione del box, usata da `FormulaWord`.

## Test

- Vitest sulla funzione di adattamento: una formula stretta resta a 1; una larga scala fino a
  entrare; una alta scala in altezza; sotto il minimo restituisce il minimo e chiede lo scorrimento.
- E2e Playwright a 1280 e 390 px con una formula lunga nella lettura veloce: il box della formula
  sta dentro l'area di lettura (`left >= area.left` e `right <= area.right`) ed è centrato
  (differenza fra i margini sinistro e destro di pochi px). Una formula corta mantiene
  `data-scale`/scala 1.
