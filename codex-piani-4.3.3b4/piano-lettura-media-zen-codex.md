# Piano 2 · Lettura: graffetta e timecode sotto il titolo, tasto M, zen e lettura veloce

Richiesta di Attilio del 22/10/2026, sulla 4.3.3b3. Riguarda lo Studio (`components/study/Study.tsx`).
Due punti, un commit ciascuno.

## 2.1 Graffetta e timecode sotto il titolo dell'unità

**Oggi.** `mountDocumentImageStrips` (`components/images/imageStripDOM.ts`) aggiunge `.rt-unit-meta`
(graffetta e timecode) **dentro** il titolo. Nella lettura dello Studio compaiono grandi quanto il
titolo, sulla stessa riga. Attilio vuole tenerli, perché sono utili, ma più discreti.

**Richiesta.**

- Nello Studio, graffetta e timecode stanno in una riga sotto il titolo dell'unità: piccoli
  (`--size-meta` o meno), colore attenuato, pulsante compatto (circa 24 px), poco spazio verticale.
  Senza immagini nella sezione resta solo il timecode, se c'è.
- In modalità zen spariscono entrambi: la sezione si apre solo con **M**.
- **M** apre e chiude la sezione immagini dell'unità corrente, con zen attivo o spento. Non deve
  intercettare il tasto mentre si scrive in un campo (stessa guardia degli altri tasti dello
  Studio). Aggiungi M all'elenco delle scorciatoie dove compaiono Z, L, E, G.
- La sezione si apre anche cliccando la graffetta, come oggi.
- Le immagini nel testo continuano a vedersi nella lettura e restano ignorate dalla lettura veloce:
  oggi va bene, non cambiarlo.

La vista documento (`DocumentView.tsx`) può tenere il comportamento attuale. Se condivide la stessa
funzione, aggiungi un'opzione (per esempio `metaBelow: true` dallo Studio), senza duplicare il
codice.

Test: unità su `mountDocumentImageStrips` con l'opzione (meta fuori dal titolo e dopo di esso). Un
e2e nello Studio: M apre la sezione, M la richiude, in zen pulsante e timecode non sono visibili.

## 2.2 Da zen alla lettura veloce

**Sintomo.** Lettura normale, poi zen (Z), poi lettura veloce (L): la lettura veloce si apre rotta.
La parola resta in alto, il testo intorno sta sotto e il layout non è quello della lettura veloce.

**Causa.** `setZenLayout({ active: zenMode && ... })` e `setRsvpLayout({ active: speedReading })`
restano attivi insieme. La lettura veloce non ha una variante zen.

**Richiesta.** Aprendo la lettura veloce con zen attivo, zen si sospende e la lettura veloce si apre
normale. Chiudendo la lettura veloce si torna alla lettura in zen, se lo era.

Indicazione: non cambiare la preferenza salvata di zen (`useStudyZen`). Ricava uno stato effettivo,
per esempio `const zenActive = zenMode && !speedReading`, e usalo per il layout, per la barra zen e
per i comportamenti legati a zen (`setZenLayout`, `ZenHeader`, `notice`, `LessonJumpTab`, tasti).
Verifica che Z durante la lettura veloce non riattivi zen sotto il lettore.

Test: e2e. Studio, Z, L: lettura veloce con il layout normale (stessa geometria del test già
esistente sulla lettura veloce) e nessun elemento zen visibile. Esc: si torna in zen.
