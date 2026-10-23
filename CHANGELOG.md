# Novità di RT

## 4.3.3b4 — 2026-10-23

### Novità

- **Job in parallelo**: sempre 8, l'impostazione non c'è più. La trascrizione locale resta una alla volta.
- **Esercizi**: la traccia dà solo i dati, non il metodo. Il template generale si aggiorna da solo se non l'hai modificato.
- **Immagini nel testo**: un clic apre il visore, o la porta al centro del pannello se è aperto; doppio clic mostra il markdown; tenendo premuto la sposti. Nel pannello l'immagine scelta si evidenzia con un piccolo rimbalzo.
- **Studio**: graffetta e timecode piccoli sotto il titolo dell'unità, nascosti in zen. **M** apre e chiude le immagini.
- **Calendario**: nel riepilogo della settimana ogni ora da recuperare porta al suo blocco.
- **Stato di studio** istantaneo: con S o il pulsante si cicla fra gli stati senza attese; si salva l'ultimo appena ti fermi.
- **Lezioni**: l'anello di studio sta sul bordo destro; sotto il titolo compaiono «Verificato» e il numero di media, se ci sono. Tornando da una lezione, la sua riga è al centro ed evidenziata per 2 s.
- **Lezioni mancanti**: l'avviso compare in ogni raggruppamento (materia, giorno, mese, docente) e l'elenco si apre al passaggio del mouse. Serve l'«Inizio del periodo» nel riepilogo della settimana.
- **Strumenti dello Studio** (evidenziatore, gomma, Verifica, Chiedi, cestino) in un solo gruppo che si apre al passaggio del mouse; chiuso mostra lo strumento attivo.
- **Gruppi che si aprono al passaggio del mouse** (Aggiorna, matita del calendario, strumenti dello Studio, lezioni mancanti) restano aperti 3 s dopo l'uscita; un clic altrove o Esc li chiude subito.

### Correzioni

- Sul Mac il worker ignorava il numero di job in parallelo.
- Niente più sfarfallio trascinando un'immagine nel testo; si può lasciare anche sulla graffetta vuota.
- Dopo la classificazione l'immagine non compare più anche grande sotto la sezione.
- Passando da zen alla lettura veloce lo zen si sospende e torna all'uscita.

## 4.3.3b3 — 2026-10-22

### Novità

- **Lezioni mancanti**: dalle info di una settimana la imposti come inizio del periodo accademico. Se una materia ha meno lezioni elaborate di quelle svolte (contando cambi d'orario, annullate e da saltare), accanto al nome compare un piccolo avviso; il popup elenca le lezioni mancanti e la data porta al blocco nel calendario. Si nasconde dalle impostazioni.
- **Esporta e importa**: dal menu dell'app esporti tutto in un file e lo importi su un altro PC. Le chiavi API non escono mai dal computer: all'importazione restano quelle locali.
- **Lezione già esistente**: se i metadati sono già usati da un'altra lezione, RT dice quale e permette di cambiarli.
- **Anello e scudo**: quando ogni unità ha uno stato diverso da «da apprendere» l'anello mostra una spunta; lo scudo compare solo sulle lezioni verificate.
- **Lettura veloce**: conto alla rovescia prima di partire (0–10 s, predefinito 3), saltato se riprendi entro 5 s dalla pausa. Il rumore di fondo entra ed esce in 1 s. Le formule lunghe si adattano allo spazio reale e restano centrate.
- **⌘/Ctrl + Invio** invia la risposta scritta; Invio va a capo.

### Correzioni

- Le formule nelle domande generate sono scritte in LaTeX e quindi rese correttamente.
- Niente più bordo nero attorno ai campi di testo attivi.

## 4.3.3b2 — 2026-10-22

### Correzioni

- **Aggiornamenti dall'app**: il popup non interroga più GitHub in loop (HTTP 429, download non riuscito). Come nella 4.3.2.2.

## 4.3.2.2 — 2026-10-22

### Correzioni

- **Aggiornamenti dall'app**: il popup controllava gli aggiornamenti senza fermarsi, finché GitHub smetteva di rispondere (HTTP 429) e il download falliva. Ora controlla una volta sola, «Controlla ora» va su GitHub al massimo una volta al minuto e, se GitHub non risponde, resta valido l'ultimo controllo riuscito.

## 4.3.3b1 — 2026-10-21

### Novità

- **Immagini della sottounità**: una graffetta con il numero accanto al timer apre le immagini in riga sotto il titolo. Trascinando un'immagine sulla graffetta finisce nella sezione, nel testo resta dove la lasci e si ridimensiona. Le miniature si spostano tra sezioni e testo. L'impostazione «Dove le lascio» non c'è più.
- **Pannello arricchimento**: si allarga trascinando il bordo sinistro. Cliccando un'immagine nella lezione, il pannello la porta al centro.
- **Archivio** più veloce ad aprirsi, con un'anteprima animata mentre carica. Le pagine dei PDF non compaiono più come immagini singole.
- **Selezione multipla**: dai dettagli puoi rielaborare o rigenerare tutte le lezioni scelte insieme.
- **Genera domande**: il popup si chiude e la generazione continua in background.
- Verifiche: le formule nelle issue sono rese come nel testo.

Contiene anche la correzione della 4.3.2.1.

## 4.3.2.1 — 2026-10-21

### Correzioni

- **Nuova lezione con più audio da unire**: l'import non si ferma più con «Impossibile unire i file audio». Se qualcosa va storto non resta una lezione a metà, e il nuovo tentativo non risponde più «Esiste già una lezione con questi metadati».

## 4.3.2 — 2026-10-21

Raccoglie le beta 4.3.2b1, b2 e b3 (dettagli sotto).

### Novità

- **Archivio delle fonti**: PDF, audio e immagini già usati non si rielaborano più. Nuova pagina **Archivio** per ignorare, ritagliare o riusare le pagine in altre lezioni; **Aggiungi fonte** accetta anche Word e testo e sceglie cosa estrarre e come usarlo (Guida, Contesto, Integra).
- **Esporta PDF**: la lezione in A4, con le immagini sotto il titolo due per riga e quelle nel testo dove le hai messe.
- Calendario: vista annuale, **Vai alla settimana**, copia e incolla di settimane, esportazione e importazione dell'orario (`.rtcal`), docenti per materia.
- Lezioni: vista fissabile con la puntina, elenco senza raggruppamenti e ordine **(Ri)create di recente**.
- Studio e lettura: lettura veloce con scorciatoie, zoom dell'interfaccia e del testo, evidenziatore che si spegne dopo l'ultimo colore.
- Domande: ogni risposta resta nello storico, con la pagina **Risposte**.
- App: aggiornamenti in un popup con **Installa e riavvia**, notifiche a fine lavoro, apertura di audio e PDF dal Finder, registrazione vocale con permesso del microfono, firma ad-hoc e istruzioni nel DMG.
- Copia con formattazione scelta in Impostazioni › Copia, job tutti con un nome leggibile, backup con avanzamento.

### Correzioni

- Verifiche: le issue di un'unità sparita dopo una rielaborazione si chiudono da sole.
- Audio che si interrompeva al primo ascolto, formule nelle domande, risposte vocali senza parlato, import di archivi in anteprima e varie correzioni su Windows.
- Il browser che prepara il PDF lavora nascosto: niente più "Chrome for Testing" nel Dock.

## 4.3.2b3 — 2026-10-21

### Novità

- **Esporta PDF**: la lezione in A4, leggibile anche ingrandendo. Le immagini sotto il titolo vanno due per riga a mezza pagina; quelle nel testo restano dove le hai messe, con la larghezza che hai scelto.
- Lezioni: si possono spegnere tutti i raggruppamenti per avere un elenco unico, e c'è l'ordine **(Ri)create di recente**, per l'ultima volta in cui la lezione è passata da scaletta, rielaborazione o documento.
- I job hanno tutti un nome leggibile (prima alcuni comparivano come `enrichment_generate` o `review_unit`). Il popolamento iniziale dell'archivio si chiama "Archivio delle fonti" e mostra l'avanzamento lezione per lezione.
- Studio: dopo l'ultimo colore l'evidenziatore si spegne, e la volta dopo riparte dal giallo.

### Correzioni

- Verifiche: dopo una nuova rielaborazione le issue di un'unità che non c'è più si chiudono da sole, invece di restare "Da riconfermare" e rimbalzare l'una sull'altra.

## 4.3.2b2 — 2026-10-20

### Novità

- **Archivio delle fonti**: un PDF, un audio o un'immagine già usati in una lezione non si rielaborano più quando tornano in un'altra (niente nuove trascrizioni né descrizioni).
- Nuova pagina **Archivio**, dal pannello Arricchimento: tutti i file mai aggiunti, con le pagine usate da ogni lezione. Le pagine si possono ignorare (l'AI non le legge più), ritagliare o eliminare, e un file o alcune sue pagine si aggiungono a un'altra lezione senza rielaborarli.
- **Aggiungi fonte** riconosce i file già nell'archivio e propone le pagine da dove ci si era fermati; per ogni fonte si sceglie cosa estrarre (solo testo o anche immagini) e come usarla (Guida, Contesto, Integra). Si possono aggiungere documenti Word (.docx) e file di testo (.txt).
- Uso **Integra**: una fonte da integrare entra davvero nella lezione. La scaletta la vede e può aggiungere unità per gli argomenti che la registrazione non tratta.
- Pannello Arricchimento: pulsante Archivio in cima, filtro **Da descrivere** e una barra della selezione nuova con Descrivi, Posiziona, Inserisci, Ritaglia, Togli dal testo ed Elimina dalla lezione.
- Un'immagine trascinata nel testo va sotto il titolo della sottounità su cui la lasci, evidenziata mentre trascini. In Impostazioni › Editor si può scegliere "Dove le lascio", e allora le immagini si ridimensionano dagli angoli. Con il pannello Arricchimento aperto, un clic su un'immagine del testo la seleziona fra i media.
- Le domande riposte si possono rispondere davvero: la vecchia risposta e la correzione non compaiono più subito. Ogni risposta resta nello storico, e la pagina **Risposte** (dal pannello Domande) le mostra tutte per la lezione.
- Copia: il testo copiato da RT (per esempio in Anki) tiene grassetto, corsivo ed evidenziazioni ma non il colore del testo; le formule arrivano come `\( \)` e `\[ \]`. In Impostazioni › Aspetto e lettura › **Copia** si sceglie cosa tenere.
- Nell'app gli aggiornamenti arrivano in un popup: si scaricano mentre usi RT e si installano quando vuoi con **Installa e riavvia**. Il file scaricato resta anche se chiudi RT. Chi è sul canale beta riceve anche le beta dall'app.
- Nell'app arriva una notifica quando un lavoro lungo finisce o aspetta una tua decisione, e l'icona nel Dock mostra quanti lavori sono in corso.
- Puoi aprire audio e PDF con RT dal Finder ("Apri con") o trascinandoli sull'icona nel Dock: si apre Nuova lezione con quei file.
- Il DMG spiega nello sfondo come installare RT e come aprirlo la prima volta con "Apri comunque". RT.app ha una firma ad-hoc: macOS non la dà più per danneggiata.

### Correzioni

- Un archivio completo di una lezione ancora in anteprima ("(anteprima).zip") si importa di nuovo: prima era rifiutato con "File non dichiarati nel manifesto".
- Studio: entrando in lettura nessuno strumento è selezionato; con Chiedi o Verifica aperti le scorciatoie degli strumenti funzionano di nuovo.
- Windows: aggiungere un materiale scegliendo le pagine e ritagliare una pagina dell'archivio non falliscono più; l'archivio non conta due volte la stessa lezione.
- Calendario annuale: la settimana selezionata si vede anche quando ha la barretta del cambio d'orario.

## 4.3.2b1 — 2026-10-19

### Novità

- Calendario: vista annuale, **Vai alla settimana** con la griglia delle settimane (mesi separati, settimane passate e future distinte, senza leggenda), copia e incolla di una settimana stampo dentro Modifica, anche su più settimane dalla vista annuale.
- Impostazioni › Materie: esporta l'orario del calendario e importalo da un file `.rtcal`, tutto o solo in un periodo, con avviso se sostituisce un orario esistente.
- Docenti per materia: si salvano da soli, si suggeriscono nel campo Docente e si gestiscono in Impostazioni › Materie. Nel popup del calendario Invio conferma.
- Lezioni: la puntina accanto a Cerca fissa la vista (raggruppamento, ordine, ricerca e filtri) e la ritrova al rientro; una modifica la sblocca.
- Lettura veloce: L entra ed esce dalla lettura veloce, S cambia lo stato di studio, Option/Alt+frecce e due pulsanti piccoli passano all'unità precedente o successiva; durante la lettura i controlli si attenuano.
- Zoom dell'interfaccia (Aspetto, menu dell'app e Cmd/Ctrl +/−) e zoom del solo testo nello Studio con + e −.
- Media della lezione: vista con una pagina per riga, anteprima grande tenendo premuto su una miniatura, file scelti visibili in **Aggiungi PDF o foto**, anche un'immagine sola nel testo si mostra in miniatura.
- Media: nuovo pulsante **Elimina** nella selezione. **Togli dal testo** funziona anche sugli elementi dell'arricchimento, che restano nei media.
- **Informazioni su RT** con logo, versione e build reali, anche in Impostazioni › Info.
- Backup con avanzamento e **Salva una copia…** in un file zip.
- Preparazione più veloce: pagine dei materiali lette in parallelo e insieme alla trascrizione, avanzamento più chiaro e tempi registrati.
- Nell'app la registrazione vocale funziona: RT chiede il permesso del microfono al primo uso. Il menu ha **Controlla permessi**, che lo richiede o apre l'impostazione di sistema se era stato negato.
- I pulsanti a icona disattivati mostrano comunque il suggerimento, con il motivo dove serve.

### Correzioni

- L'audio della lezione non si interrompe più dopo pochi secondi al primo ascolto: la copia riproducibile si prepara una volta sola e quelle rovinate dalle versioni precedenti vengono rifatte.
- Le formule nelle domande (testo, alternative e commento della valutazione) si vedono rese.
- Una risposta vocale senza parlato non viene più valutata: RT dice che non ha rilevato parlato e si può rispondere di nuovo. Una lezione con trascrizione vuota lo dice chiaramente.
- Nell'editor non compaiono più i commenti tecnici dei blocchi dell'arricchimento.
- Nelle visualizzazioni le frecce dei vettori non diventano più quadratini (vale per quelle generate da ora).
- La scheda **Scaletta da approvare** resta visibile durante l'aggiornamento della lezione.
- «Da capo» senza arricchimento, icone delle unità che non sfarfallano, collegamento all'ora del calendario conservato durante un import.

## 4.3.1.1 — 2026-10-19

### Correzioni

- **Rifare tutte le fasi** non si blocca più in un ciclo sulla scaletta: approvata la scaletta, la lezione passa alla rielaborazione invece di rigenerarla e chiederne di nuovo l'approvazione all'infinito.

## 4.3.1 — 2026-10-19

### Novità

- L'app apre RT nella sua finestra, già autenticata, invece che nel browser. Chiudere la finestra lascia RT acceso in background; **Esci da RT** nel menu lo spegne. Il menu raccoglie aggiornamenti, cartella dati, registri, backup, diagnostica e **Apri nel browser**.
- Su Windows sparisce la finestra nera del terminale: il server di RT gira nascosto.
- Sul Mac con Apple Silicon, `rt -u` propone di passare all'app con un sì (anche con `rt app install`): lezioni, configurazione e chiavi restano in `~/.rt`, e i comandi `rt` della vecchia cartella passano all'app.
- Studio: copiando un testo con formule si copia il LaTeX, come nella pagina della lezione. Durante la selezione le formule si mostrano in LaTeX, l'evidenziatore non le rompe più e Verifica e Chiedi ricevono la citazione esatta.
- Fasi della lezione a sole icone: esegui la pipeline, riesegui tutti i passaggi oppure ricomincia da capo rileggendo anche le fonti (trascrizione e documenti). La validazione di scaletta e bozza è uno scudo sulla riga della fase.
- Accanto all'orario di ogni unità due piccole icone portano allo Studio di quell'unità o alle sue domande; se non ci sono domande si apre la generazione. Sul computer compaiono passandoci sopra, sul telefono si vedono sempre.
- Calendario: la settimana tipo si modifica anche per un intervallo di settimane, scelto da una griglia annuale che mostra le settimane già modificate (dal 2025 al 2035). Il riepilogo della settimana mostra l'anno.
- Calendario: la nota di un'ora si legge passando sull'icona accanto all'orologio, e il riquadro di un'ora è più ordinato.

### Correzioni

- Cambiando la materia di una lezione si può scegliere qualunque materia, anche senza lezioni.
- Tolta dai dettagli della lezione la riga Cartella.
- La diagnostica dell'app trova macparakeet-cli installato con Homebrew.
- Nel pannello Verifica e Chiedi dei dettagli le formule e la formattazione si vedono correttamente, e il pulsante per espandere la citazione è allineato.
- Le evidenziazioni fatte prima dell'aggiornamento restano al loro posto anche vicino alle formule.
- Le versioni di una lezione occupano meno spazio e ripristinarle non costringe a rileggere i materiali.
- Modificare un'ora del calendario non la allunga alle settimane in cui non c'era.

## 4.3.1b1 — 2026-10-17

### Novità

- Sul Mac con Apple Silicon, `rt -u` propone di passare all'app con un sì. Puoi farlo anche con `rt app install`: lezioni, configurazione e chiavi restano in `~/.rt`.
- La vecchia cartella resta al suo posto, ma i suoi comandi `rt` passano all'app, anche per vedere la versione e aggiornare. Se l'app manca, RT avvisa e si ferma per proteggere i dati.
- Se hai ancora un `rt web` acceso nel terminale, RT ti chiede di fermarlo prima del passaggio. Se usi una beta più recente dell'app, aspetta la prossima stabile per evitare di aprire i dati con una versione vecchia.
- L'app apre RT nella sua finestra, già autenticata, invece che nel browser. Chiudere la finestra lascia RT acceso in background; **Esci da RT** nel menu lo spegne.
- Il menu dell'app raccoglie aggiornamenti, cartella dati, registri, backup, diagnostica e **Apri nel browser**.
- Su Windows sparisce la finestra nera del terminale: il server di RT gira nascosto.

## 4.3.0 — 2026-10-17

### Cambiamenti

- Tolta la mini app di Telegram: lo studio e il recall dal telefono passano dalla web app.
- Tolta la vecchia interfaccia Gradio (`rt web --legacy`), già deprecata: la web di RT è quella che si apre con `rt web`.
- Telegram serve solo alle notifiche nella tua chat personale: lezione pronta, decisione da prendere, errore. Si configura in Impostazioni › Telegram (token del bot, /start, Collega la chat). Niente più gruppi, topic, ripassi o revisione su Telegram, e niente più servizio del bot: `rt service install` (eseguito anche dall'aggiornamento) toglie quello vecchio.
- Il terminale serve per i comandi: revisione, ripasso e configurazione si fanno nella web app. Tolti `rt config` e le schermate interattive di `rt review` e `rt recall`; `rt run` si ferma su scaletta e issue da valutare e le decisioni si prendono nella web (`--auto-accept` per accettarle dal terminale).
- Meno dipendenze da installare (python-telegram-bot, Telethon, Textual, questionary).

### Novità

- Nuovo motore di trascrizione Parakeet ONNX: lo stesso modello Parakeet v3, sulla CPU, anche su Windows e Linux. Sul Mac resta consigliato macparakeet; Parakeet ONNX è la seconda scelta. Il modello si scarica alla prima trascrizione (circa 700 MB).
- ffmpeg non va più installato a parte: se manca, RT usa quello incluso.
- Su Windows funzionano i lock dei file, i nomi delle lezioni e la resa delle slide PowerPoint (con LibreOffice, se installato).
- RT si installa come un'app: un .dmg per il Mac (Apple Silicon) e un setup per Windows, con tutto incluso (niente Homebrew, Python o terminale). Si apre con un doppio clic e apre la web app nel browser.
- L'app si aggiorna da Impostazioni › Info › Aggiornamenti, solo alle versioni stabili. Le beta si scaricano a mano dalla pagina delle release.
- Se la porta 8765 è occupata da un altro programma, l'app ne sceglie una libera e la ricorda: niente più avvio fallito.

### Dalle beta 4.2.6

- Arricchimento › Media: tutte le pagine e le foto delle fonti, raggruppate per fonte, da inserire nel testo (anche a strisce), trascinare, ritagliare o collocare in automatico. "Solo pagine" divide PDF e foto senza modelli e senza costi.
- PDF e foto aggiunti in Arricchimento e immagini dal web finiscono nelle sottounità pertinenti; i materiali guidano la rielaborazione sottounità per sottounità.
- Domande: il numero diventa un tetto ("Fino a"), niente ripetizioni fra i tipi, varianti verificate degli esercizi, controlli automatici che scartano le domande rotte e un avviso finale con il riepilogo. Le "Regole dai voti" in Impostazioni › Domande si ricavano dai tuoi voti e si modificano a mano.
- Audio più leggero: le registrazioni si salvano in m4a, più audio caricati insieme diventano una sola fonte (Unisci) e "Alleggerisci l'audio delle lezioni" libera spazio sulle lezioni vecchie.
- Import più comodo: trascini i file su qualunque punto della finestra, il caricamento continua anche chiudendo l'import (lo segui nella pagina Job), e dal Calendario un'ora senza lezione apre l'import già impostato.
- Si possono scaricare solo le fonti di una o più lezioni; togliere una fonte chiede conferma e si può rimettere com'era.
- Chiedi e Verifica mostrano titoli, elenchi e formule, e sul computer i popup si spostano e si ridimensionano. Formule LaTeX anche per le reazioni chimiche.
- Varie correzioni su miniature, player delle lezioni unite, iPhone e menu del clic destro.

## 4.2.6b5 — 2026-10-16

### Novità

- In Arricchimento › Media della lezione vedi tutte le pagine e le foto delle fonti, raggruppate per fonte, con l'unità in cui compaiono o “non usata”. Puoi selezionarne una, un intervallo con Maiusc o tutte, e inserirle nel testo al punto del cursore (più pagine diventano una striscia), trascinarle nel testo, collocarle in automatico solo quelle scelte o toglierle dal testo lasciandole nei media.
- Ogni miniatura ha l'icona Ritaglia: il ritaglio si salva come nuova immagine (“Pag. N · ritaglio K”) oppure sostituisce la pagina nel testo, dopo una conferma che dice in quali unità compare.
- Aggiungendo PDF o foto puoi scegliere “Solo pagine”: il file viene diviso in pagine nei media, senza modelli e senza costi, e le collochi quando vuoi.
- Le registrazioni unite hanno una riga compatta con durata totale, chip delle parti e barra proporzionale; aprendo il chip, nomi e durate usano tutta la larghezza del pannello anche sul telefono.
- Le risposte e le correzioni di Chiedi/Verifica mostrano titoli, grassetti, elenchi e formule; il contenuto passa dallo stesso renderer sicuro dei documenti.
- Sul computer i popup Chiedi e Verifica si spostano e si ridimensionano, possono allargarsi a pannello e mantengono il campo d’invio visibile mentre la risposta scorre. Invio manda la richiesta, Maiusc+Invio va a capo.
- La collocazione delle pagine confronta i passaggi pertinenti del parlato e verifica che il contenuto sia didattico. Ogni pagina va nel punto più adatto, con una soglia iniziale più permissiva.
- La rielaborazione e le correzioni di Verifica usano formule LaTeX, anche per le reazioni chimiche, leggibili nell’editor, nella lettura e nello Studio.

### Correzioni

- Trascinando PDF o foto con il pannello Arricchimento aperto, il pannello si illumina e il rilascio apre il caricamento dei media, invece del riquadro di import di una nuova lezione.
- Miniature e immagini nel testo si vedono intere, senza tagli, anche quando sono molto larghe o molto alte.
- Su iPhone il foglio Chiedi/Verifica resta sopra la barra delle sezioni e la tastiera; la maniglia sceglie tre altezze e le risposte lunghe aprono il foglio a piena altezza.
- Nel testo il clic destro apre sempre il menu di RT, anche senza selezione e con ctrl+clic su Mac; ⌥ + clic destro apre il menu del browser.
- Le sottolineature di Verifica e Chiedi compaiono solo con il pannello delle note aperto; nello Studio si vede solo la nota del popup aperto.
- Copertine, titoli e pagine quasi vuote senza figure restano fuori dalla collocazione automatica, senza chiamare i modelli; intestazioni e piè di pagina ripetuti non contano come contenuto. Gli schemi con poco testo usano la descrizione visiva.
- Nell’import senza audio il primo documento è già selezionato come fonte principale; togliendolo, la scelta passa al primo rimasto.
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
