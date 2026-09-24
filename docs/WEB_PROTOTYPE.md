# Prototipo web locale

La nuova interfaccia Gradio è un'anteprima per valutare il flusso di lavoro prima di
sostituire la TUI Textual. Si avvia localmente e legge i dati esistenti di RT:
manifest, stato delle fasi, documento Markdown, questioni di review, ledger delle
decisioni, file audio e configurazione. La review scrive le decisioni nel ledger RT
e aggiunge un registro delle azioni web nella stessa cartella della lezione.

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
- **Review:** elenco delle questioni, affermazione, proposta e diff, motivazione,
  unità completa e citazione ASR espandibili, estratto audio relativo al segmento
  quando disponibile. Accetta, mantiene l'originale o salva un testo modificato
  nel ledger usato anche da CLI e Telegram. Una decisione presa dalla GUI si può
  riaprire. La prossima questione in attesa viene selezionata automaticamente.
- **Configurazione:** percorsi e modelli in uso, senza mostrare le chiavi API. Le
  impostazioni si continuano a modificare dal wizard CLI.

Le lezioni di prova non vengono importate nel repository: la UI usa la loro cartella
originale, esattamente come fa RT. La verifica è stata eseguita sulla lezione di
Patologia generale del 26 febbraio 2025 in `prove trt`: una decisione di prova è
stata salvata, riletta dalla dashboard e poi riaperta. Il ledger è tornato a 18
questioni in attesa. Il log `web_review_events.jsonl` conserva entrambi gli eventi
(`recorded` e `reverted`) nella sottocartella `_state/` della lezione. Se un log
esiste già nella radice di una lezione con il vecchio layout, RT usa quel file.

## Passi successivi

1. Unificare ulteriormente le azioni di review della CLI e di Telegram attorno al
   servizio usato dalla GUI, mantenendo le regole attuali dei tre canali.
2. Estrarre la configurazione dal wizard CLI in servizi condivisi e rendere
   modificabile la schermata delle impostazioni.
3. Aggiungere azioni di pipeline con stato e avanzamento strutturati, senza lanciare
   comandi CLI come sottoprocessi dalla pagina.
4. Verificare il flusso completo con le lezioni di prova e poi scegliere la modalità
   di distribuzione. Docker è opzionale: il prototipo funziona nell'ambiente Python
   locale già usato da RT.

La TUI e la CLI restano disponibili durante la migrazione. Textual potrà essere
rimosso quando la GUI coprirà le operazioni utili e il flusso sarà verificato.
