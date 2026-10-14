# Novità di RT

## 4.2.6b1 — 2026-10-14

- Togliere una fonte chiede conferma e conserva il file e il registro. Le fonti già usate tolte richiedono Ricostruisci e si possono rimettere com’erano; quelle mai usate non risultano più come fonti nuove.

## 4.2.5 — 2026-10-14

### Novità

- Nuova pagina Calendario con l'orario delle lezioni: settimana tipo modificabile, stato e nota di ogni ora, riepilogo con le ore da recuperare. Una lezione registrata si collega da sola alla sua ora; in modifica un clic su un'ora ne cambia i dati, e il docente compare nel blocco.
- Import in un solo riquadro: audio, PDF, foto e PowerPoint insieme, separati da RT; le ore del calendario del giorno compaiono come scelte rapide.
- Lezioni che crescono nel tempo: in Dettagli › Fonti si aggiungono parti di registrazione, appunti o materiali anche giorni dopo, poi Estendi o Ricostruisci. Le ultime cinque versioni si ripristinano, e anche il ripristino si annulla.
- I materiali aiutano la rielaborazione come contesto e, con la graffetta, le loro pagine vengono allegate alle unità. Si può creare una lezione solo dai materiali.
- La rielaborazione tiene il filo delle unità già scritte, con le parti ripetute del prompt in cache.
- Chip Consigliato nel pannello Domande, sezione Materie in Impostazioni, ricerca web con fonti nella verifica contestuale (spenta di default).
- Linea sottile che segue l'audio accanto al testo, pannelli laterali staccati dal bordo con apertura animata.
- Accesso di sola lettura per assistenti come Open WebUI, con chiave separata.
- Sul computer le frecce mandano avanti e indietro la registrazione di 5 secondi.
- Verifica con LLM: avviso a tempo con Annulla, "Accetta tutte" e Annulla nell'intestazione, Ascolta a icona.

### Correzioni

- Il pannello aperto non copre più il testo con la finestra stretta; opzioni lunghe e menu non escono più dai pannelli.
- Le Fonti non si svuotano più aprendo Dettagli durante la trascrizione.
- Il Calendario si apre anche se le sue tabelle erano state create da una versione di prova.

## 4.2.5b2.2 — 2026-10-13

### Correzioni
- Aprendo Dettagli mentre una lezione nuova veniva trascritta, le registrazioni sparivano dalle Fonti e compariva "la lezione va ricostruita" anche senza aver cambiato niente. Ora le Fonti mostrano sempre l'audio, e le lezioni già colpite si sistemano da sole.

## 4.2.5b2.1 — 2026-10-13

### Novità
- Calendario: in modalità modifica un clic su un'ora apre i suoi dati (materia, inizio, fine, docente) e li salva, solo per questa settimana o per la settimana tipo da questa settimana in poi.
- Nei blocchi del calendario il docente compare in piccolo sotto l'orario.
- Pagina della lezione sul computer: le frecce mandano avanti e indietro la registrazione di 5 secondi ovunque nella pagina (non mentre scrivi). Per cambiare lezione si passa col mouse accanto al titolo; sul telefono resta lo swipe.
- Verifica con LLM: dopo una decisione compare per 5 secondi un avviso dal basso con Annulla; l'ultima decisione si annulla anche dopo, dall'icona in cima al pannello. "Ascolta da" è diventato un pulsante a icona accanto ad accetta e mantieni.
- Verifica con LLM: nuova icona "Accetta tutte" in cima al pannello per accettare con una conferma tutte le correzioni da decidere; l'icona Annulla le riporta tutte da decidere.

### Correzioni
- Con la finestra più stretta il pannello aperto non copre più il testo della lezione: il testo si stringe accanto al pannello, e anche il lettore audio.
- "Riesegui con opzioni" in Dettagli e "Cerca immagini sul web" in Arricchimento si aprono in un popup: i titoli lunghi delle unità non escono più dal pannello.
- I menu ⋯ delle fasi e delle domande e "Aggiungi fonte" non vengono più tagliati in fondo al pannello.
- Errori, correzioni e nomi lunghi vanno a capo invece di allargare il pannello.

## 4.2.5b2 — 2026-10-13

### Novità
- Import in un solo riquadro: trascini insieme audio, PDF, foto e PowerPoint e RT li separa da solo. Le parti audio si riordinano trascinandole; senza audio la stellina sceglie il materiale che fa da filo della lezione.
- Le ore del calendario del giorno compaiono nell'import come scelte rapide: un clic compila materia, docente e ora e collega la lezione a quell'ora.
- I materiali aiutano la rielaborazione come contesto; con la graffetta accesa le pagine più legate a un'unità vengono allegate come immagini. Si può anche creare una lezione solo dai materiali.
- In Dettagli la nuova sezione Fonti: aggiungi parti di registrazione, appunti o materiali anche giorni dopo, poi scegli Estendi o Ricostruisci. Spostare parti già usate o cambiare la fonte principale chiede conferma e si può rimettere com'era.
- Versioni della lezione: le ultime cinque si ripristinano da Dettagli, e anche il ripristino si annulla. Evidenziazioni, note e domande non vengono mai cancellate; quelle nate prima di un cambiamento dell'unità hanno una piccola icona.
- Nel pannello Domande il chip Consigliato genera per ogni unità il tipo che Jev le ha consigliato.
- Nuova sezione Materie in Impostazioni: si aggiungono anche materie senza lezioni, che compaiono in import, calendario e tipi di domanda.
- La verifica contestuale può cercare sul web con SearXNG e mostrare le fonti con i link (interruttore in Impostazioni › Lavorazione, spento di default).
- Mentre ascolti l'audio, una linea sottile accanto al testo segue il parlato dell'unità.
- Pannelli laterali staccati dal bordo, con angoli arrotondati e apertura animata; il contenuto resta lo stesso.
- Accesso di sola lettura per assistenti come Open WebUI: chiave separata in Impostazioni › Accesso, ricerca nel testo delle lezioni e guida per collegarlo.

### Correzioni
- In Dettagli i pulsanti Classificatore e Verifiche e domande non escono più dal pannello.

## 4.2.5b1.1 — 2026-10-12

### Correzioni
- Il Calendario non si apriva ("Errore interno del server") se le sue tabelle erano già state create da una versione di prova: ora il database viene completato all'avvio.

## 4.2.5b1 — 2026-10-12

### Novità
- Nuova pagina Calendario, nella barra laterale sotto Lezioni (che ha una nuova icona) e nella barra in basso sull'iPhone. Mostra la settimana sul Mac e il giorno sull'iPhone, con l'orario delle lezioni colorato per materia.
- L'orario si scrive una volta come settimana tipo e si modifica con la matita: solo questa settimana, oppure la settimana tipo da questa settimana in poi. Le settimane passate restano come erano.
- Ogni ora ha uno stato (da seguire, seguita, non seguita, da saltare, annullata) e una nota; il menu del giorno segna tutto il giorno in un colpo. Il riepilogo della settimana è nel bottone ⓘ, con le ore da recuperare.
- Una lezione registrata con la stessa data, ora e materia si collega da sola alla sua ora e la segna come seguita; dal popup dell'ora si può collegarne o scollegarne una a mano.
- La rielaborazione tiene il filo delle unità già scritte prima di quella in corso, anche quando rigeneri una sola unità, senza passare al modello il trascritto delle unità successive. Le parti ripetute del prompt restano in cache, così le unità successive costano meno.
- Prime basi per le lezioni che crescono nel tempo (aggiungere audio o appunti a una lezione esistente): i comandi arrivano nella prossima beta.

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
