# Risoluzione problemi e FAQ

In questa pagina trovi le risposte ai problemi più comuni e le istruzioni per consultare i registri dell'applicazione.

## Domande frequenti

### La trascrizione o l'elaborazione segnala un errore di rete o di chiave API
- Verifica in **Impostazioni → Modelli** che la chiave inserita sia corretta e non scaduta.
- Controlla sul pannello del fornitore (es. OpenAI o Anthropic) di avere credito residuo attivo sul tuo account sviluppatore.

### L'audio registrato risulta muto o con volume molto basso
- Su macOS e Windows, verifica nelle impostazioni di sistema che RT disponga dei permessi per accedere al microfono.

### L'app si chiude o non si avvia
- Puoi verificare lo stato dell'installazione eseguendo da terminale il comando diagnostico:
  ```bash
  rt doctor
  ```
  Questo comando controlla la cartella dati, i permessi, i modelli e la connessione locale.

## Dove sono i registri (log)

Se hai bisogno di esaminare i dettagli tecnici di un errore, RT scrive i propri registri nella cartella dati:
- Su macOS e Linux il percorso predefinito è `~/.rt/logs/`.
- Su Windows si trova nella cartella del tuo profilo utente in `.rt\logs\`.
- Puoi aprire direttamente la cartella dei log dall'applicazione desktop tramite il menu **Aiuto → Apri cartella dati** (o dalla riga di comando con `rt data`).
