# Risoluzione problemi e FAQ

In questa pagina trovi le risposte ai problemi più comuni e le istruzioni per consultare i registri dell'applicazione.

## Domande frequenti

### La trascrizione o l'elaborazione segnala un errore di rete o di chiave API
- Verifica in **Impostazioni → Modelli e connessioni** che la chiave inserita sia corretta e non scaduta.
- Controlla sul pannello del fornitore (es. OpenRouter, Google AI Studio o DeepSeek) di avere credito residuo attivo sul tuo account sviluppatore.

### L'audio registrato risulta muto o con volume molto basso
- Su macOS e Windows, verifica nelle impostazioni di sistema che RT disponga dei permessi per accedere al microfono.

### L'app si chiude o non si avvia
- Puoi verificare lo stato dell'installazione eseguendo da terminale il comando diagnostico:
  ```bash
  rt doctor
  ```
  Questo comando controlla la cartella dati, i permessi, i modelli e la connessione locale.

## Dove sono i registri (log)

Se hai bisogno di esaminare i dettagli tecnici di un errore, RT scrive i propri registri nella cartella dati di RT:
- Su macOS (app desktop) il percorso predefinito è `~/Library/Application Support/RT/logs/` (da terminale o su Linux è `~/.rt/logs/`).
- Su Windows il percorso predefinito è `%LOCALAPPDATA%\RT\logs\`.
- Puoi aprire direttamente la cartella dei log dall'applicazione desktop tramite il menu **RT → Mostra registri** (o **Apri cartella dati**; dalla riga di comando con `rt data`).
