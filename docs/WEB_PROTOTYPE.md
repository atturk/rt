# Prototipo web locale

La nuova interfaccia Gradio è un'anteprima per valutare il flusso di lavoro prima di
sostituire la TUI Textual. Si avvia localmente e **legge** i dati esistenti di RT:
manifest, stato delle fasi, documento Markdown, questioni di review, ledger delle
decisioni, file audio e configurazione. Non crea né modifica file delle lezioni.

## Avvio

Dalla radice del repository, dopo aver installato RT:

```bash
./.venv/bin/python -m pip install -r requirements-web.txt
./bin/rt-web
```

Se la cartella delle lezioni non è impostata in `config/general.yaml`, oppure per
provarne un'altra:

```bash
./bin/rt-web --lessons-root "/Users/attilioturco/rt-stuff/prove trt"
```

L'app si apre su `http://127.0.0.1:7860`. Si può usare `--port 7868` per cambiare
porta o `--no-browser` per non aprire automaticamente il browser. Il server ascolta
solo su `127.0.0.1` e non genera un link pubblico Gradio. `requirements-web.txt`
aggiunge Gradio alle dipendenze di RT; l'installazione standard della CLI resta
invariata.

## Schermate

- **Dashboard:** scelta o ricerca di una lezione, stato delle cinque fasi, numero di
  questioni aperte e anteprima degli appunti.
- **Review:** elenco delle questioni, testo sorgente, proposta, motivazione e breve
  estratto audio relativo al segmento, quando disponibile. Le decisioni esistenti
  vengono lette dal ledger. I pulsanti di decisione sono per ora disabilitati.
- **Configurazione:** percorsi e modelli in uso, senza mostrare le chiavi API. Le
  impostazioni si continuano a modificare dal wizard CLI.

Le lezioni di prova non vengono importate nel repository: la UI usa la loro cartella
originale, esattamente come fa RT. Per la verifica iniziale è stata usata la lezione
di Patologia generale del 26 febbraio 2025 in `prove trt`, con 18 questioni in
attesa; la UI individua anche le altre lezioni presenti nella stessa cartella.

## Passi successivi

1. Estrarre le operazioni di review e configurazione oggi legate alla CLI in servizi
   Python invocabili da entrambe le interfacce, con validazione e scrittura atomica.
2. Collegare i pulsanti di decisione al ledger esistente e aggiornare la dashboard
   subito dopo ogni scelta.
3. Aggiungere azioni di pipeline con stato e avanzamento strutturati, senza lanciare
   comandi CLI come sottoprocessi dalla pagina.
4. Verificare il flusso completo con le lezioni di prova e poi scegliere la modalità
   di distribuzione. Docker è opzionale: il prototipo funziona nell'ambiente Python
   locale già usato da RT.

La TUI e la CLI restano disponibili durante la migrazione. Textual potrà essere
rimosso quando la GUI coprirà le operazioni utili e il flusso sarà verificato.
