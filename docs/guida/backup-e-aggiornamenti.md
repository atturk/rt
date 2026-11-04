# Backup e aggiornamenti

RT protegge i tuoi dati in modo automatico prima di ogni aggiornamento dell'applicazione, offrendo strumenti semplici per ripristinare le informazioni in caso di imprevisti.

## Backup automatico pre-aggiornamento

Prima di installare qualsiasi aggiornamento (sia tramite l'app grafica su macOS/Windows, sia tramite il comando da terminale `rt -u`), RT crea in automatico un backup leggero:
- **Cosa include**: una copia coerente del database SQLite (`rt.db`) e tutti i file di testo delle lezioni (testi Markdown, file di stato JSON e YAML).
- **Cosa esclude**: file audio pesanti, registrazioni vocali, immagini e PDF sorgente, che restano intatti nella cartella multimediale sul disco senza occupare spazio duplicato.
- **Dove si trova**: i backup vengono salvati nella cartella dati di RT sotto `backups/prima-aggiornamento/` nel formato `rt-<versione>-<data-ora>.zip`.
- **Rotazione automatica**: RT conserva automaticamente gli ultimi 5 backup pre-aggiornamento, eliminando i più vecchi per risparmiare spazio.
- **Sicurezza preventiva**: se la creazione del backup dovesse fallire per qualsiasi ragione (ad es. spazio su disco esaurito), l'aggiornamento viene immediatamente bloccato per evitare rischi di corruzione.

## Ripristino dei dati

Se dopo un aggiornamento riscontri problemi con i tuoi dati, puoi ripristinare lo stato precedente:
- **Dall'applicazione desktop**: apri il menu principale e seleziona **Ripristina dati prima di un aggiornamento…**.
- **Da riga di comando**: esegui `rt restore --pre-update`.

Verrà mostrata la lista degli archivi disponibili con versione e data. Dopo la conferma, RT mette al sicuro lo stato corrente e ripristina il database e i testi precedenti.

> [!NOTE]
> Il ripristino interviene solo sui **dati di studio**, non sull'eseguibile del programma. Se desideri tornare alla versione precedente dell'applicazione software, reinstalla l'installer scaricabile dalla pagina delle release su GitHub.
