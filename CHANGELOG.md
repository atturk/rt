# Novità di RT

## 4.2.4b3 — 2026-10-11

### Correzioni

- L’icona dell’ordine della verifica mostra un orologio per l’ordine cronologico e un triangolo per la gravità. Nelle Novità puoi spuntare e barrare le voci già lette, con memoria nel browser. Le motivazioni delle correzioni sono richieste in frasi complete.
- Riesegui subito la verifica dal menu, oppure invia le unità al revisore senza il classificatore preventivo. Puoi verificare anche una singola unità esclusa; le verifiche della lezione continuano a escluderla.
- Le issue indicano “Testo cambiato” dal passaggio effettivamente salvato sul server: puoi chiuderle o verificare di nuovo l’unità. Le modifiche altrove nell’unità lasciano applicabile la correzione.
- Qualità ASR mostra tutti i tratti incerti, con confidenza, parole sottolineate e ascolto limitato al tratto. “Ho controllato” chiude l’avviso senza cambiare il testo.
- I menu a icona escono dai pannelli e restano interamente nello schermo, anche sul telefono.

## 4.2.4b2 — 2026-10-11

### Novità

- Pannello Verifica nuovo: un solo elenco di unità con la gravità delle issue, le issue dentro la loro unità, ✓ per accettare e ✗ per mantenere, Annulla nel messaggio in basso e "Mostra decise" per rivederle.
- Mentre la verifica lavora, le unità già finite si possono decidere subito; fino a quattro unità vengono verificate in parallelo.
- Il documento finale e gli Errori concettuali si aggiornano da soli dopo ogni decisione, annullamento o modifica a mano: non serve più "Ricostruisci il documento".
- "Verifica questa parte" nel menu contestuale dell'editor: verifica solo il testo selezionato e un avviso in basso porta all'unità nel pannello.
- La verifica riceve il contesto della lezione (titolo, materia, docente, argomenti e scaletta) e propone sempre la sostituzione esatta del passaggio.
- Nei costi delle chiamate si vedono i token letti dalla cache del prompt, al loro prezzo quando è noto.

### Correzioni

- Una decisione non fa più ripetere la verifica dell'unità.
- Le correzioni si applicano solo al passaggio giusto della propria unità, anche quando la stessa frase compare più volte; quelle che non si ritrovano più restano "da riconfermare".
- Un rifiuto resta valido anche se una verifica successiva cita lo stesso passaggio con parole diverse.
- Verifiche e decisioni contemporanee non si sovrascrivono più a vicenda.
- Le decisioni si vedono subito nel pannello, senza ricaricare tutta la lezione.
- Colori Irlen leggibili anche nel tema scuro, in zen e nella lettura veloce.
- Colori del pannello Classificatore più saturi e bordo della selezione non più tagliato.

### Cambiamenti

- Le lezioni esistenti vengono aggiornate al nuovo formato alla prima apertura, senza chiamate al modello e senza cambiare il testo.
- Le issue senza citazione ritrovabile nel testo si possono solo rifiutare.
- La build non rinomina e non sposta più la cartella della lezione; `rt build` resta disponibile.
- "Verifica e Chiedi" nello Studio arriva nella prossima beta.

## 4.2.4b1 — 2026-10-09

### Novità

- Modalità zen nello Studio, con barra a scomparsa e filtro Irlen condiviso con la lettura veloce.
- Linguetta per passare alla lezione precedente o successiva dello stesso giorno o della stessa materia.
- Cambio lezione dai lati del titolo e con swipe su iPhone, anche per le lezioni non ancora rielaborate.
- Classificatore unico nelle Impostazioni, con modalità e modello personalizzabili per ciascun job.
- Pannello Classificatore a griglia, con correzioni manuali e classificazione delle unità cambiate.
- Novità delle versioni consultabili in Impostazioni › Info.

### Correzioni

- Le scorciatoie dello Studio conservano la posizione nel testo, anche tornando dal ripasso.
- Le frecce per cambiare lezione rispettano editor, campi, menu, selezioni e player audio.
- Ridotte le letture ripetute e le chiamate del classificatore; cache per prefiltro e deriva.

### Cambiamenti

- Tasti dello Studio: Z per la zen, D per le domande, E per l'evidenziatore, G per la gomma e ⇧E per il colore.
- Le impostazioni esistenti del classificatore vengono migrate automaticamente.
- Le note delle release GitHub provengono da questo changelog, incluso negli aggiornamenti con rt -u.

Per le versioni precedenti: [release di GitHub](https://github.com/atturk/rt/releases).
