# Novità di RT

## 4.2.5b1

- Le lezioni conservano un elenco ordinato delle fonti originali, senza spostare i file delle lezioni esistenti.

## 4.2.4 — 2026-10-12

### Novità

- Nello Studio arrivano Verifica (V) e Chiedi (C): selezioni un passaggio e chiedi se è corretto o di spiegartelo; le correzioni si applicano con un clic e si annullano. In Dettagli il pannello "Verifiche e domande" raccoglie risposte e passaggi per unità.
- Tipi di domanda personalizzati per materia, creati in Impostazioni › Domande o copiati dalla galleria (Caso clinico, Esercizio, Query SQL), da provare su un'unità e scambiare come file JSON.
- Pannello Verifica nuovo: un solo elenco di unità con la gravità delle issue, ✓ e ✗ per decidere, Annulla e "Mostra decise". Le unità già verificate si decidono mentre la verifica continua.
- Il documento finale e gli Errori concettuali si aggiornano da soli dopo ogni decisione o modifica a mano.
- "Verifica questa parte" nel menu contestuale dell'editor verifica solo il testo selezionato.
- Modalità zen nello Studio, linguetta e frecce per passare alla lezione vicina, swipe su iPhone.
- Classificatore unico nelle Impostazioni, con modalità e modello per ciascun job, e pannello Classificatore a griglia con una riga per tipo di domanda.
- Novità delle versioni in Impostazioni › Info, con le voci da spuntare.

### Correzioni

- Una decisione non fa più ripetere la verifica dell'unità e le correzioni si applicano solo al passaggio giusto.
- Il ripasso riprende per prime le domande senza risposta.
- Qualità ASR mostra tutti i tratti incerti, con ascolto del solo tratto e "Ho controllato".
- Menu a icona interi nello schermo anche sul telefono; colori Irlen leggibili nel tema scuro.

### Cambiamenti

- Caso ed esercizio diventano tipi personalizzati modificabili: le vecchie domande di questi tipi vengono tolte.
- Le lezioni esistenti passano al nuovo formato della verifica alla prima apertura, senza chiamate al modello.
- Tasti dello Studio: Z zen, D domande, E evidenziatore, G gomma, ⇧E colore.

## 4.2.4b3 — 2026-10-12

### Novità

- Nello Studio arrivano Verifica (V) e Chiedi (C): selezioni un passaggio e chiedi se è corretto o di spiegartelo. Se la verifica trova un errore puoi applicare la correzione con un clic e annullarla dal messaggio in basso.
- I passaggi verificati o chiesti restano sottolineati nello Studio e nell'editor. In Dettagli il pannello "Verifiche e domande" li raccoglie per unità, con le risposte, "Vai all'unità" ed Elimina.
- Tipi di domanda personalizzati: in Impostazioni › Domande crei tipi per materia (o li copi dalla galleria, per esempio Caso clinico, Esercizio, Query SQL), li provi su un'unità senza salvare niente e li scambi come file JSON.
- Il Classificatore mostra una riga per ogni tipo della materia, con "Presente" o "Nessuno". Il tipo consigliato, Genera e il ripasso propongono i tipi personalizzati trovati nell'unità.

### Cambiamenti

- Caso ed esercizio non sono più tipi fissi: le vecchie domande di questi tipi vengono tolte e, nelle materie dove c'erano, Caso clinico ed Esercizio diventano tipi personalizzati modificabili.
- Le domande dei tipi eliminati restano consultabili nello storico sotto "Tipo eliminato".

### Correzioni

- Il ripasso riprende per prime le domande lasciate senza risposta; una domanda conta come risposta quando vedi la soluzione o la valutazione. I due pulsanti in fondo rimettono in gioco tutte le risposte oppure solo le sbagliate.
- I menu a icona escono dai pannelli e restano interi nello schermo, anche sul telefono.
- Qualità ASR mostra tutti i tratti incerti, con confidenza, parole sottolineate e ascolto del solo tratto; "Ho controllato" chiude l'avviso senza cambiare il testo.
- "Testo cambiato" ora lo decide il server sul testo salvato: puoi chiudere l'issue o verificare di nuovo l'unità.
- "Riesegui" parte subito, senza conferma. "Esegui senza classificatore" verifica una lezione o un'unità, anche esclusa.
- L'icona dell'ordine della verifica cambia: orologio per l'ordine cronologico, triangolo per la gravità.
- Nelle Novità puoi spuntare le voci già lette.
- Le motivazioni delle correzioni sono chieste in frasi complete.

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
