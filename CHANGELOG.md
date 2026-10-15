# Novità di RT

## 4.2.6b5 — 2026-10-16

### Novità

- La rielaborazione e le correzioni di Verifica usano formule LaTeX, anche per le reazioni chimiche, leggibili nell’editor, nella lettura e nello Studio.

### Correzioni

- Le istruzioni ai modelli evitano pedici e apici Unicode o HTML nelle formule.

## 4.2.6b4 — 2026-10-15

### Correzioni

- Trascinando un file sulla pagina, il riquadro di import resta visibile finché non lo lasci andare, anche se muovi il file sopra altri elementi.

### Novità

- Puoi scaricare solo le fonti di una lezione (audio unito e ottimizzato, PDF, foto e altri documenti) dal menu Esporta della lezione o, per più lezioni, dalla selezione con “Solo le fonti (zip)”.
- Il pulsante Unisci è un’icona che cambia con lo stato: parti unite in un’unica registrazione o fonti separate.
- Il caricamento dei file di una nuova lezione continua anche se chiudi la finestra di import: lo segui nella pagina Job, puoi annullarlo e avviare altri import, che partono uno dopo l’altro. Finché un caricamento è in corso, chiudere o ricaricare la scheda di RT chiede conferma.

## 4.2.6b3 — 2026-10-15

### Correzioni

- Le ore segnate come seguite senza una lezione si possono scegliere nell’import e collegare a una lezione. Le ore annullate rifiutano il collegamento; eliminare una lezione libera la sua ora senza cambiare lo stato “seguita”.
- In Arricchimento puoi trascinare PDF e foto nel riquadro di caricamento, aggiungendoli ai file già scelti.
- Il caricamento di PDF e foto mostra l’avanzamento durante la lettura e la collocazione delle immagini.

### Novità

- I PDF e le foto aggiunti in Arricchimento si collocano nelle sottounità pertinenti, come i materiali importati. I PDF usano il testo della pagina; la descrizione visiva serve alle pagine senza testo e alle foto. Le immagini già presenti restano al loro posto.
- Le immagini trovate sul web per una sottounità vengono inserite direttamente in quella sottounità.

## 4.2.6b2.1 — 2026-10-15

### Correzioni

- Il player audio è di nuovo visibile nelle lezioni importate con più audio uniti (o con un audio e dei materiali): non trovava l'audio salvato fra le fonti. Le lezioni già importate tornano a funzionare da sole.

## 4.2.6b2 — 2026-10-15

### Correzioni

- Striscia di immagini nell'editor: con molte pagine non allarga più l'editor e la pagina, le miniature scorrono dentro la striscia; sotto la striscia non compare più l'ultima pagina a grandezza piena.
- Pannello Domande: tolta la frase sotto i chip del tipo ("Ogni unità riceve il tipo che Jev le ha consigliato…").
- Le novità della 4.2.6b1 sono di nuovo visibili in Impostazioni (la sezione risultava vuota).

## 4.2.6b1 — 2026-10-15

### Novità

- Domande, numero come tetto: nei popup "Quante" diventa "Fino a". Il modello genera solo le domande che trova utili; se non arriva al numero, RT riprova fino a tre passaggi sulle unità che danno ancora domande nuove. Le domande in più dell'ultimo passaggio restano.
- Domande, niente ripetizioni: il generatore vede le domande già presenti sull'unità di ogni tipo (quiz, mirate, vaste, personalizzate), non solo dello stesso tipo, e cerca altri concetti.
- Domande, varianti degli esercizi: i tipi con "Varianti verificate" riempiono il numero chiesto con varianti che cambiano dati e contesto (es. età e situazione clinica, profumi o farmaci nelle miscele), fino a 5 per chiamata, ciascuna controllata da una verifica indipendente. Non c'è più il limite di 2.
- Domande, controlli senza modello: RT scarta da sé le domande chiaramente rotte (troppo corte o enormi, segnaposto, testo ripetuto, in inglese, quiz con opzioni doppie o risposta giusta molto più lunga, fuori tema, quasi doppioni, varianti con gli stessi numeri). Le valutazioni con esito in contraddizione con le percentuali si riprovano una volta.
- Domande, avviso finale: a fine generazione dice quante ne ha create rispetto al numero e perché si è fermato, per esempio "Generate 6 su 10: il modello non ha trovato altri contenuti utili. 2 scartate dai controlli, 1 variante non ha superato la verifica."
- Regole dai voti: in Impostazioni › Domande, sezione "Regole dai voti", per ogni tipo e materia con voti ci sono al massimo 8 regole ricavate dai voti, modificabili a mano, con numero di voti, data e l'icona Aggiorna ora. Si aggiornano da sole dopo 5 voti nuovi, ma quelle modificate a mano restano finché non premi Aggiorna ora. Interruttori Voti e Controllo prima di salvare, accesi di default: con i Voti spenti spariscono i pulsanti di voto e nei prompt non entrano né esempi né regole. Gli esempi dei voti si scelgono per materia e pertinenza con l'unità.
- Fonti tolte in sicurezza: la × su una fonte in Dettagli chiede conferma (e avvisa se serve Ricostruisci). La fonte resta salvata: se era già usata compare "Hai tolto N fonti già usate" con Ricostruisci e l'icona Rimetti com'era; se non era mai usata non compare nessuna riga. Ripristinare una versione rimette le fonti di quella versione.
- Materiali per sottounità: prima della rielaborazione ogni pagina dei materiali viene confrontata con il parlato delle sottounità (parole significative, senza intercalari) e il classificatore delle immagini conferma a quali appartiene davvero (soglia 0,8, regolabile in Impostazioni › Classificatore). Ogni sottounità riceve solo le sue pagine come contesto, e la fonte principale guida: dai materiali entrano termini, valori, definizioni ed esempi di ciò che il docente tratta. Le lezioni già fatte cambiano solo con Ricostruisci.
- Immagini dei materiali: con la graffetta accesa le pagine assegnate compaiono sotto la loro sottounità (o sotto l'unità se servono a tre o più sottounità), nell'ordine del documento; le immagini aggiunte a mano o dal web restano dopo.
- Striscia di immagini: due o più immagini di fila diventano una striscia di miniature in una riga che scorre di lato, nell'editor, nella lettura e nello Studio, con la freccina per chiuderle tutte. Un clic apre il visore a schermo pieno con frecce, tastiera (← → Esc) e swipe sul telefono. Il markdown esportato resta un'immagine per riga.
- Audio leggero: ogni registrazione aggiunta (anche con i materiali o da Aggiungi fonte) si salva in m4a; il wav non si tiene.
- Unisci: più audio caricati insieme diventano una sola fonte, con l'elenco delle parti e la loro durata sotto il nome in Fonti. Il bottone Unisci (acceso di default) sta nella riga delle parti dell'import e in Aggiungi fonte; spento, restano fonti separate.
- Alleggerisci: in Impostazioni › Spazio e cache, "Alleggerisci l'audio delle lezioni" mostra quanto spazio si libera e, dopo la conferma, converte i vecchi wav e flac e cancella gli audio uniti che non servono più, senza rifare trascrizioni e senza rompere le versioni.
- Calendario: in un'ora senza lezione c'è l'icona + che apre l'import con quella data e quell'ora già scelte; a import finito la lezione è collegata.
- Import: l'ora scelta si distingue meglio (bordo pieno), le altre hanno la barretta grigia.
- Trascinamento: si possono trascinare audio, materiali o .zip su qualunque punto della finestra; compare "Rilascia per importare" e si apre l'import con i file già caricati.

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
