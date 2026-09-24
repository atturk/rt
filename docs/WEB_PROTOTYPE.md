# Prototipo web locale

La nuova interfaccia Gradio è un'anteprima per valutare il flusso di lavoro prima di
sostituire la TUI Textual. Si avvia localmente e legge i dati esistenti di RT:
manifest, stato delle fasi, documento Markdown, questioni di review, ledger delle
decisioni, file audio e configurazione. La review scrive le decisioni nel ledger RT
e aggiunge un registro delle azioni web nella stessa cartella della lezione.

## Avvio

Dopo aver installato o aggiornato RT:

```bash
rt web
```

`rt -u` installa anche le dipendenze web e verifica quelle mancanti quando RT
è già aggiornato. In un checkout di sviluppo, installa manualmente
`requirements-web.txt` nel virtualenv e avvia `./bin/rt web`.

Se la cartella delle lezioni non è impostata in `config/general.yaml`, oppure per
provarne un'altra:

```bash
rt web --lessons-root "/percorso/alle/lezioni"
```

L'app si apre su `http://127.0.0.1:7860`. Si può usare `--port 7868` per cambiare
porta o `--no-browser` per non aprire automaticamente il browser. `bin/rt-web`
resta disponibile come avvio diretto equivalente. Il server ascolta
solo su `127.0.0.1` e non genera un link pubblico Gradio. `requirements-web.txt`
aggiunge Gradio alle dipendenze di RT; l'installazione standard include la web app.

Il terminale mostra avvio, richieste HTTP, durata delle azioni, errori Python e
segnalazioni dal browser. Gli stessi eventi vengono salvati in un file locale a
rotazione (5 MB per file, tre copie): su macOS `~/Library/Logs/rt/web.log`, oppure
nel percorso scelto con `--log-file`. `RT_WEB_LOG` permette la stessa scelta via
variabile d'ambiente. I log non includono corpi delle richieste né il percorso dei
file audio serviti. Premi Ctrl+C per fermare il server.

## Schermate

- **Dashboard:** sidebar sovrapposta e regolabile con lezioni raggruppate per
  materia, stato delle cinque fasi, issue aperte e appunti completi. Durante il
  cambio lezione il controllo di chiusura e le altre lezioni restano bloccati fino
  al caricamento. I timecode avviano il lettore nativo dell'audio integrale; le
  frecce accanto al lettore passano tra le unità della lezione.
- **Review:** elenco delle questioni, affermazione, proposta e diff, motivazione,
  unità completa e citazione ASR espandibili, estratto audio relativo al segmento
  quando disponibile. Accetta, mantiene l'originale o salva un testo modificato
  nel ledger usato anche da CLI e Telegram. Una decisione presa dalla GUI si può
  riaprire. La prossima questione in attesa viene selezionata automaticamente.
- **Configurazione:** percorsi e modelli in uso, senza mostrare le chiavi API. Le
  impostazioni si continuano a modificare dal wizard CLI.
- **Importa audio:** il pulsante nell'intestazione apre il setup non interattivo
  della CLI. Richiede data e materia; la trascrizione con `macparakeet-cli` è
  selezionabile. Una lezione esistente non viene sovrascritta.

L'interfaccia usa Seravek quando disponibile sul sistema, con font di riserva.
La cartella originale delle lezioni resta esclusa dall'accesso diretto via web:
RT prepara per Gradio solo l'audio della lezione scelta in una cartella temporanea.
Se un file chiamato `.m4a` contiene in realtà AAC grezzo, RT lo rimette in un
contenitore M4A riproducibile dal browser, senza modificare l'originale.

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
3. Aggiungere stato e avanzamento strutturati all'importazione e alle altre azioni
   di pipeline, senza lanciare comandi CLI come sottoprocessi dalla pagina.
4. Verificare il flusso completo con le lezioni di prova e poi scegliere la modalità
   di distribuzione. Docker è opzionale: il prototipo funziona nell'ambiente Python
   locale già usato da RT.

La TUI e la CLI restano disponibili durante la migrazione. Textual potrà essere
rimosso quando la GUI coprirà le operazioni utili e il flusso sarà verificato.
