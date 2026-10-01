# QC Recall RT 4.1.1b1 — 30 settembre 2026

Implementazione e verifiche strutturali superate. Il QC semantico rileva ancora difetti: questa beta non certifica automaticamente la correttezza o la pertinenza di tutte le domande.

## Copertura e metodo

Tutte le nove lezioni sono state importate nei test attraverso RT: **169 unità classificate**, più quattro controlli sintetici. Nessun errore del classificatore. Il recaller è stato provato su quattro unità per lezione, scelte per includere introduzioni, logistica, interruzioni e contenuti disciplinari: **36 unità reali**, più quattro sintetiche, per quiz, mirata e vasta. Questo è un campionamento della generazione: non sono state generate domande per tutte le 169 unità.

Il passaggio iniziale ha completato 90 gruppi: 89 risposte valide, inclusi 16 esiti vuoti, e un gruppo fallito per timeout. Il gruppo fallito è stato riprovato con successo con Space Bunny, producendo dieci quiz. Risultato effettivo: **368 domande sulle lezioni**, più cinque sul controllo; totale 373. Gli esiti vuoti validi restano distinti dagli errori.

| Lezione | Unità classificate | Quiz | Mirate | Vaste |
|---|---:|---:|---:|---:|
| Controllo sintetico | 4 | 2 | 2 | 1 |
| Diritto pubblico 28/09 | 19 | 16 | 17 | 2 |
| Elettromagnetismo 28/09 | 26 | 8 | 10 | 1 |
| Patologia generale 2 28/09 | 14 | 16 | 15 | 2 |
| Data mining 29/09 | 21 | 23 | 27 | 3 |
| PGSS 29/09 | 20 | 15 | 20 | 4 |
| Data mining 30/09 | 16 | 28 | 28 | 3 |
| Elettromagnetismo 30/09 | 14 | 17 | 18 | 2 |
| Patologia generale 2 30/09 | 18 | 15 | 22 | 3 |
| PGSS 30/09 | 21 | 22 | 26 | 5 |


Il primo passaggio usa l’implementazione pubblicata nel commit `9a269d8`. Dopo il QC, il prompt è stato affinato su esempi negativi, ridondanza, italiano e posizione della risposta corretta. Le regressioni finali coprono quattro casi quiz/mirata e tre gruppi vasta; gli output iniziali sono conservati. Le nove lezioni non sono state rigenerate integralmente dopo ogni affinamento. Gli input completi, gli output e il rapporto dettagliato restano fuori dal repository; questo documento contiene il riepilogo riproducibile. Nessuna credenziale è inclusa.

## Modelli e robustezza

Classificatore: esclusivamente `typesafe/jev-1.13`. Recaller: `stealth/space-bunny-alpha` primario, `openrouter/free` soltanto come fallback dopo timeout. I modelli concreti free osservati sono `nvidia/nemotron-3-super-120b-a12b:free` e `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`. Non sono stati scelti direttamente altri modelli. Non sono arrivate risposte `safe` nelle chiamate reali; i test verificano che `safe` e contenitori privi di `questions` siano invalidi.

Il controllo sintetico classifica ricevimento e guasto del proiettore a livello 0, arterie e vene a livello 1. Quiz e mirata producono zero sulle prime due e una domanda su ciascuna nozione; vasta collega arterie e vene ignorando la logistica. Questo conferma che una nozione breve non viene scartata e che zero non obbliga a riempire una quota.

Le valutazioni utilizzabili sono {'0': 6, '1': 2, 'None': 28, '2': 137} (None indica orientamento neutro, anche per incertezza). Non si tratta di una misura di accuratezza contro un gold standard. Lo score è un orientamento, non una decisione scientifica, una quota o un filtro automatico.

## Qualità osservata

Le domande su definizioni, relazioni, meccanismi e dataset sono generalmente aderenti al testo. Le mirate hanno spesso una buona granularità; le vaste includono scalette utili e collegamenti fra concetti. Le risposte free sono meno prevedibili e possono superare il contratto JSON pur contenendo errori.

Difetti da mantenere visibili:

- **Pertinenza:** introduzioni e obiettivi formativi possono ancora diventare domande. L’appartenenza del corso viene eliminata nelle regressioni finali; i quiz sulle competenze promesse sono instabili (zero in un passaggio, tre nell’ultimo). Una regressione vasta su sola logistica genera ancora una domanda sulla prova scritta: QC semantico non superato per quel caso.
- **Quiz:** distrattori talvolta troppo facili; uno sulla lunghezza d’onda può essere semanticamente equivalente alla risposta corretta. Nel primo passaggio la distribuzione degli indici corretti è {1: 15, 0: 119, 2: 11, 3: 7}. Il prompt finale chiede di variarla; sul caso positivo finale la distribuzione è {3: 2, 1: 2, 0: 2, 2: 2}, senza garanzia statistica generale.
- **Mirata:** restano parafrasi della stessa conoscenza, ad esempio la relazione frequenza/lunghezza d’onda, e domande sul metodo del corso invece che sul metodo disciplinare.
- **Vasta:** alcune domande interrogano quasi soltanto una delle unità del gruppo; altre si sovrappongono. La valutazione di ciascuna unità è ora trasmessa esplicitamente, senza inventare un punteggio aggregato.
- **Lingua:** refusi e parole inglesi compaiono anche con Space Bunny, nelle domande e nelle scalette. Gli inviti a rileggere il testo non eliminano ogni difetto.
- **Fallback:** nel quiz di Patologia 30/09, unità 2.1, la spiegazione dell’iperventilazione parla di riduzione della “CO₂ atmosferica”: errore introdotto dal modello, non presente nel testo fornito.
- **Materiale di partenza:** la lezione di Elettromagnetismo 28/09 colloca Hertz prima di Maxwell e il recaller ripete l’inversione. La Royal Society colloca il lavoro di Maxwell nel 1865 e gli esperimenti di Hertz nel 1887–89. In Patologia viene ripresa la semplificazione acidosi = pH basso: il processo di acidosi va distinto dall’acidemia. Sono problemi della revisione scientifica del testo, che questa modifica non sostituisce.

Fonti verificate per queste due osservazioni sul materiale: [Royal Society, intervista a Malcolm Longair](https://royalsociety.org/blog/2015/03/350-anniversary-issue-author-q-a-malcolm-longair/) e [linee guida del panel francese sull’acidosi metabolica](https://pmc.ncbi.nlm.nih.gov/articles/PMC6695455/). La verifica non è una revisione scientifica completa delle lezioni.

## Verifica del software

162 test backend mirati su richiamo, schema, cache, score, configurazione, concorrenza e persistenza. Altri 68 test mirati su sessioni e lezioni verificati, incluse le otto API ricontrollate dopo gli ultimi adattamenti: **230 casi backend distinti**. Interfaccia: **13 test**, TypeScript e schema OpenAPI rigenerato. Nessuna suite completa, E2E o workflow GitHub avviato manualmente.

Verificati: score 0/1/2 senza esclusione automatica, incertezza neutra, scale personalizzate esplicitamente associate, testo del ledger separato dalla bozza, invalidazione per contesto, conservazione e reset degli override, zero/una/più domande, rifiuto di contenitori `safe`, ID e risposte, deduplicazione concorrente, checkpoint dopo interruzioni, astensione persistita, rigenerazione esplicita e round-trip DB/export. Il refill mock usa la stessa policy del checkpoint; vasta riceve i singoli giudizi.

Rimangono necessari un corpus di riferimento annotato e ulteriori controlli semantici prima di considerare automaticamente affidabile ogni domanda. I difetti trovati sono conservati nel JSON per ripetere il QC e confrontare i prossimi cambiamenti.
