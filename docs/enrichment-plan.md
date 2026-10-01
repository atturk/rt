# Arricchimento — piano e contratti

Branch: `codex/images-macro-rework`.

1. Sostituire il giudice chat delle immagini con Decision API: una descrizione per richiesta, tutte le macro unità e il loro testo completo, etichette opache univoche e nessuna assegnazione possibile.
2. Persistenza separata di idee, valutazioni incrementali e asset pubblicati. Jev valuta separatamente l'utilità di infografiche e visualizzazioni per ogni subunità. L'arricchitore prepara titolo, descrizione e prompt JSON. Nessuna generazione automatica.
3. Job di analisi per lezione/gruppo e job di generazione esplicita, con deduplicazione, progressi, cancellazione e risultato precedente conservato durante la rigenerazione.
4. Rinominare Immagini in Arricchimento: analisi, limite per lezione, idee anche ignorate, creazione manuale, gestione dei risultati. Azioni di gruppo solo in questa pagina. Suggerimenti e frame in caricamento sotto il testo nell'anteprima.
5. Ruoli modello configurabili e impostazioni globali: automatico, soglia di utilità, tetto disattivato/fisso/proporzionale (default). Pipeline integrata, export immagine statica + HTML autonomo.
6. Verificare servizi, API, build/esportazione e TypeScript con controlli mirati; documentare configurazione e limiti reali.

Il tetto è un massimo, mai un obiettivo. Una subunità può ricevere entrambi i tipi o nessuno. Il generatore riceve solo la subunità selezionata. Idee ignorate, prompt modificati e risultati generati sopravvivono alle analisi successive. Le modifiche al testo rendono riconoscibili i contenuti precedenti senza eliminarli. La generazione manuale è indipendente dal tetto dei suggerimenti.

Il plugin OpenWebUI è un riferimento architetturale: RT non dipende dal DOM di una chat. Gli HTML sono autonomi, non possono accedere al documento padre e non effettuano richieste di rete. L'export conserva il medesimo HTML e una cattura statica. La verifica delle incoerenze tra unità è fuori da questo intervento, come concordato.

## Stato finale

Implementati servizi, API/job, pagina e blocchi inline, configurazione, pipeline ed export. Verificati i flussi offline e cinque richieste reali ai soli modelli autorizzati. Gli output reali sono conservati separatamente; non vengono pubblicati con gli estratti delle lezioni. Le fixture del repository sono sintetiche.
