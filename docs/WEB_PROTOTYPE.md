# Prototipo web locale

L'interfaccia Gradio si avvia localmente e legge i dati esistenti di RT:
manifest, stato delle fasi, documento Markdown, issue di review, ledger delle
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

Se la cartella delle lezioni non è impostata in `config/general.yaml`, l'app si
apre sulla schermata Configurazione. Inserisci il percorso di una cartella
esistente oppure scegli dove crearne una nuova e premi **Salva**.
Il percorso viene salvato in `telegram.lessons_root`, mantenendo intatte le altre
impostazioni. Per provarne un'altra solo per la sessione corrente:

```bash
rt web --lessons-root "/percorso/alle/lezioni"
```

L'app si apre su `http://127.0.0.1:7860`. Si può usare `--port 7868` per cambiare
porta o `--no-browser` per non aprire automaticamente il browser. `bin/rt-web`
resta disponibile come avvio diretto equivalente. Il server ascolta
solo su `127.0.0.1` e non genera un link pubblico Gradio. Gradio fa parte delle
dipendenze standard di RT; `requirements-web.txt` resta come alias compatibile.

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
  al caricamento. I timecode avviano il player a forma d'onda dell'audio integrale;
  le frecce accanto al lettore passano tra le unità della lezione. L'audio viene
  servito con richieste HTTP a intervalli di byte per consentire la ricerca e
  la riproduzione continua anche di file lunghi.
- **Review contestuale:** il pulsante delle issue apre un pannello a destra del
  documento, raggruppabile per unità o tipo. Cliccando una issue, RT evidenzia il
  claim nel testo e mostra proposta modificabile, motivazione, domanda al docente
  e azioni accetta/mantieni originale. Le segnalazioni sulla qualità ASR e sulla
  fedeltà al parlato sono marcate come avvisi dell'unità, non come errori
  concettuali confermati. Una decisione si può riaprire; la successiva issue in
  attesa viene selezionata automaticamente. Le issue senza ancora valida non
  vengono applicate al testo: il pannello segnala il numero e permette di aprire
  il JSON originale nell'app predefinita.
- **Configurazione:** la cartella lezioni viene salvata in `config/general.yaml`
  e riletta dopo un refresh. I pulsanti aprono form per lezioni, connessioni,
  Telegram e trascrizione. Una connessione comprende provider, Base URL e una o
  più chiavi; RT alterna le chiavi quando sono più di una. La tabella assegna a
  ciascuna delle sei fasi una connessione e un modello ricercabile. Il pulsante
  `+` aggiunge un ID modello alla connessione scelta. I cinque job LLM storici
  di recall condividono ora la route `recall`; le vecchie configurazioni sono
  lette automaticamente finché la nuova route non viene salvata. Le chiavi
  restano nel `.env` locale e non sono mostrate dopo il salvataggio. Si possono
  inoltre configurare token, chat e topic
  Telegram, ascoltare nuovi topic e avviare il bot in background dalla dashboard.
  Il motore STT predefinito può essere `macparakeet` oppure un server
  OpenAI-compatible che restituisce `verbose_json` con timestamp di segmento.
  Le route secondarie e i fallback esistenti sono preservati; le opzioni avanzate
  restano modificabili nei file YAML.
- **Importa audio:** il pulsante nell'intestazione apre il setup non interattivo
  della CLI. Richiede data e materia; la trascrizione con `macparakeet-cli` è
  selezionabile. Una lezione esistente non viene sovrascritta.

L'interfaccia usa Seravek quando disponibile sul sistema, con font di riserva, e
segue la modalità chiara o scura del sistema.
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

Restano da aggiungere stato e avanzamento strutturati all'importazione e alle
altre azioni di pipeline, e da verificare end-to-end un server STT custom e un bot
Telegram configurato da zero. Docker è opzionale: la web app funziona già
nell'ambiente Python locale usato da RT.

La TUI e la CLI restano disponibili durante la migrazione. Textual potrà essere
rimosso quando la GUI coprirà le operazioni utili e il flusso sarà verificato.
