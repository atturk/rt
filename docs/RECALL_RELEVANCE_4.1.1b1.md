# Recall e rilevanza 4.1.1b1

Il classificatore di rilevanza usa per default tre livelli score: 0 (nessun contenuto disciplinare pertinente), 1 (uno o due nuclei informativi), 2 (tre o più). Questa valutazione orienta il recaller: **non è una quota di domande e non esclude automaticamente le unità**. Un contenuto breve resta valido se contiene una conoscenza pertinente. Logistica, interruzioni, obiettivi e annunci dell'insegnamento non sono conoscenze da interrogare; un metodo disciplinare realmente descritto può esserlo.

Classificatore e recaller condividono definizione e contesto: materia, titolo della lezione e argomenti (prima quelli espliciti in info.yaml, altrimenti quelli generati nell'outline). Quiz, mirata e vasta mantengono regole di stile, few-shot e override del prompt di sistema. Il suffisso variabile con la valutazione arriva per ultimo nel prompt utente. Il recaller decide autonomamente di produrre zero, una o più domande, entro il limite tecnico di dodici per risposta; count è soltanto l'obiettivo del batch.

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

Il controllo strutturale verifica il protocollo, non la correttezza scientifica: le domande e le spiegazioni richiedono anche un giudizio di pertinenza, chiarezza, aderenza al testo e ridondanza. Il modello concreto scelto dal router free va riportato quando il provider lo rende disponibile.
