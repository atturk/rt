# Piano arricchimento generato (4.3.8)

Base: `agy/4.3.8b5` + PR #166 (questo branch: `agy/4.3.8-arricchimento`). Un commit per voce («Arricchimento: N. …»).
Alla fine scrivi `piani-agy-4.3.8/esito-arricchimento.md` (una riga per voce: fatta / non fatta e perché) e fai push sullo stesso branch.
Solo codice e test unitari (vitest/pytest): verifiche visive, Playwright e giudice LLM li fa Claude in revisione.

File principali: `rt/services/enrichment_service.py` (idee, prompt del regista, stato degli elementi),
`rt/llm/enrichment_media.py` (generatore HTML, cattura PNG, Images API), `frontend/src/components/lesson/Enrichment.tsx`
(`GeneratedElement`, `InteractiveElement`), `frontend/src/components/lesson/panels/EnrichmentPanel.tsx` (pannello Media:
gli elementi dell'arricchimento entrano come `source: 'enrichment'`), `frontend/src/components/study/Study.tsx` (Studio).

Casi reali del 2026-11-07: «Vie dell'apoptosi» (visualizzazione interattiva) vista solo come PNG nel pannello;
«Potenziale» (infografica dal modello di immagini) con V ≈ 1/r² invece di 1/r; «Distanza euclidea» (visualizzazione) con
etichette «undefined»; lezione sulla normalizzazione con 0 idee su 14 unità.

## 1. «i» sui media dell'arricchimento
Oggi la «i» chiama `/media/info` con il nome del PNG e riceve 404 «Immagine non trovata».
Per gli elementi con `source === 'enrichment'` il pannello non chiama l'API: mostra nella stessa finestra delle info
tipo (`kindLabel`), unità, titolo, descrizione, modalità (statica/interattiva) e il prompt usato (comprimibile).
Test vitest: nessuna chiamata a `/media/info` per un elemento dell'arricchimento, campi mostrati.

## 2. Le visualizzazioni interattive si aprono interattive
Nel pannello e nell'anteprima a tutto schermo (lightbox) oggi si vede solo il PNG catturato: i pulsanti sembrano cliccabili e non lo sono.
- Se l'elemento ha `asset_html` e modalità `interactive`, la lightbox mostra `InteractiveElement` (iframe sandbox, stesso URL di oggi) al posto del PNG.
- Sulla miniatura un piccolo badge «Interattiva».
- Test vitest: lightbox con iframe per un elemento interattivo, img per uno statico.

## 3. Elementi generati anche in Studio
In Studio (`Study.tsx`, testo dell'unità da `unit.html`) gli elementi pronti non compaiono. Dopo il testo dell'unità mostra,
per gli elementi con `asset_image` e stato diverso da `dismissed`/`deleted` di quell'unità, `GeneratedElement` (titolo sopra,
niente pulsanti di gestione). Non devono entrare nel testo usato da lettura veloce, evidenziazioni e note.
Test vitest: un elemento pronto della 4.3 compare nella 4.3, uno ignorato no.

## 4. Infografiche fedeli: niente formule inventate dal modello di immagini
I modelli di immagini sbagliano testo, numeri e formule (caso «Potenziale»). Le infografiche (`kind == "infographic"`)
si generano come le visualizzazioni ma in modalità `static`: `VISUALIZER_SYSTEM` + `INFOGRAPHIC_INSTRUCTIONS`, HTML/SVG
con testo vero, poi `snapshot()` per il PNG; si salva anche l'HTML. Il modello di immagini (`enrichment_image`) resta solo per
`kind == "image"` (illustrazioni, dove il testo è minimo). Aggiorna l'etichetta in `connections_service.py`
(«Generazione infografiche» → «Generazione immagini IA») e il messaggio d'errore in `generate_image`.
Test pytest (mock): infographic chiama il visualizzatore e la cattura, non `generate_image`.

## 5. Controllo automatico delle visualizzazioni prima di pubblicarle
In `snapshot()` (o subito dopo, nella stessa pagina) leggi il testo visibile del frame: se contiene `undefined`, `NaN`,
`null`, `[object Object]` oppure un elemento di testo esce dai bordi di `#rt-visualization-root`, la generazione fallisce con
un motivo preciso. `generate_media` riprova UNA volta passando al visualizzatore il motivo («Nel tentativo precedente:
etichette "undefined" …, correggi»); se fallisce ancora l'elemento va in errore con quel motivo, senza pubblicare.
Le chiamate e i costi dei due tentativi restano nella telemetria come oggi.
Test pytest con HTML finti: uno con «undefined» → riprova e poi errore; uno pulito → pubblicato.

## 6. Domanda di utilità più concreta
Oggi le due domande `UTILITY` danno punteggi poco distinti (lezione di 14 unità su un metodo numerico: 0 idee).
Riscrivile chiedendo cose verificabili nel testo dell'unità: «Il testo descrive un processo a passaggi, un confronto tra
due o più elementi, una struttura con parti, una formula con variabili o dati numerici che si possono rappresentare senza
aggiungere informazioni?» (visualizzazione) e l'analogo per l'infografica (relazioni/sequenze/confronti riassumibili in poche
etichette). Lascia invariata la soglia (`utility_threshold`). Il cambio delle domande cambia `analysis_policy`: le unità
vengono rivalutate alla prossima analisi, va bene così.
Test pytest: le domande nuove sono quelle passate a `decision` (mock).

## Fuori piano
Niente cambi al formato del manifest o ai blocchi `rt-enrichment` del documento; la guida (`docs/guida/*.md`) non si tocca.
