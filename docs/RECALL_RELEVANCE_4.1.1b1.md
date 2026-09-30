# Recall e rilevanza 4.1.1b1

Il classificatore di rilevanza usa per default tre livelli score: 0 (nessun contenuto disciplinare pertinente), 1 (uno o due nuclei informativi), 2 (tre o più). Questa valutazione orienta il recaller: **non è una quota di domande e non esclude automaticamente le unità**. Un contenuto breve resta valido se contiene una conoscenza pertinente. Logistica, interruzioni, obiettivi e annunci dell'insegnamento non sono conoscenze da interrogare; un metodo disciplinare realmente descritto può esserlo.

Classificatore e recaller condividono definizione e contesto: materia, titolo della lezione e argomenti (prima quelli espliciti in info.yaml, altrimenti quelli generati nell'outline). Quiz, mirata e vasta mantengono regole di stile, few-shot e override del prompt di sistema. Il suffisso variabile con la valutazione arriva per ultimo nel prompt utente. Per vasta riporta separatamente le valutazioni delle singole unità: non calcola un punteggio aggregato o una quota. Il recaller decide autonomamente di produrre zero, una o più domande, entro il limite tecnico di dodici per risposta; count è soltanto l'obiettivo del batch.

## Pool e unità selezionate

Non c'è più una riserva di poche domande sulle prime unità: la lezione ha un **pool**. **Rigenera pool** (web, `POST /lessons/{id}/recall/generate` senza `qtype`, `rt recall --pool`) passa al recaller tutte le unità selezionate, una chiamata per unità per quiz e mirate e una per gruppo di quattro unità consecutive per le vaste; le domande già generate restano e il recaller, che le vede, ne aggiunge di nuove senza ripeterle. Le domande che non convincono si eliminano dalla pagina **Domande** della lezione (`/lezioni/{id}/recall/domande`, anche in blocco), da `POST /lessons/{id}/recall/questions/delete` o con `rt recall --delete recall_000012,...`; le risposte date a quelle domande spariscono con loro e gli ID non tornano in uso.

Di predefinito sono selezionate le unità rilevanti: quelle che il classificatore non giudica organizzative o senza contenuto e a cui non dà livello 0, anche con il gate in ombra. Senza classificazione valgono tutte. Il selettore compatto nella pagina del recall mostra per ogni unità score e livello e permette di cambiare la scelta (`GET`/`PUT /lessons/{id}/recall/units`, `rt recall --units 1.1,2.3`; `rilevanti` torna alla predefinita). La scelta sta nel bank; le unità nuove dopo una rielaborazione partono dalla selezione predefinita. Le domande delle unità tolte non vengono proposte.

Quando le domande da porre di un tipo scendono a 5 quiz, 3 mirate o 2 vaste (`telegram.recall.refill_thresholds`), il recaller ne genera altre da unità selezionate scelte a caso (`refill_batch_size` come obiettivo). La vecchia `reserve_targets` non si usa più.

## Protocollo e compatibilità

Le nuove risposte richiedono `{"questions": [...]}`. Una lista vuota è un'astensione valida; un oggetto senza questions o una risposta `safe` sono errori di protocollo. RT assegna ID, unità e metadati, valida separatamente ciascuno stile e conserva spiegazioni quiz e scalette vaste. I quiz richiedono quattro opzioni distinte, indice valido e spiegazione. I bank storici e le risposte già registrate restano leggibili; l'interfaccia segnala le pending precedenti alla nuova policy, senza rivalutare retroattivamente l'intero bank.

Le decisioni choice/noul e score personalizzate restano disponibili. Una scala score personalizzata guida il recall soltanto se associata esplicitamente ai tre livelli. Errori, risultati incerti, classificazioni scadute, modalità shadow o disabilitata lasciano il recaller in modalità neutra. La modalità active continua a rispettare esclusioni choice/noul e correzioni manuali valide. Il prefiltro scientifico non cambia.

## Testo approvato e persistenza

Il recall classifica il testo con le decisioni del ledger applicate. `unit_relevance.json` descrive la bozza; `unit_relevance_resolved.json` descrive il testo effettivamente usato. Risultati e correzioni possono essere condivisi soltanto quando le impronte del testo e del contesto coincidono. Cambi al testo, al contesto o alla policy invalidano i risultati precedenti.

Il bank salva un checkpoint atomico dopo ogni risposta valida. Le risposte vuote e quelle interamente duplicate segnano il gruppo come esaurito e non causano nuovi refill invariati. Cambi di testo, contesto, configurazione, few-shot o rigenerazione esplicita permettono un nuovo tentativo. Un errore rimane riprovabile. Il merge sotto lock conserva domande e risposte concorrenti e assegna ID unici. Le impronte e i checkpoint viaggiano insieme al bank nello storage esistente.

## QC riproducibile

`scripts/qc_recall.py` importa lezioni Markdown con frontmatter e unità `###`, classifica tutte le unità e genera i tre stili su un campione esplicito. Gli output salvano testo, valutazioni, domande, astensioni ed errori per revisione. È riprendibile per gruppo, usa i client di RT e rifiuta configurazioni che impieghino modelli diversi da typesafe/jev-1.13, stealth/space-bunny-alpha e openrouter/free. Configurazioni e credenziali devono stare fuori dal repository, in RT_DATA_DIR; il corpus e i risultati privati non vengono pubblicati nel repository.

Esempio (configurazione privata già predisposta):

```sh
RT_DATA_DIR=/path/private RT_DATABASE_URL=off python scripts/qc_recall.py \
  --inputs /path/lessons --work-dir /path/qc --sample-plan /path/sample.json --workers 4
```

Il rapporto di questa esecuzione è in [QC_RECALL_4.1.1b1.md](QC_RECALL_4.1.1b1.md). Il controllo strutturale verifica il protocollo, non la correttezza scientifica: le domande e le spiegazioni richiedono anche un giudizio di pertinenza, chiarezza, aderenza al testo e ridondanza. Il modello concreto scelto dal router free va riportato quando il provider lo rende disponibile.
