# Web app di RT

`rt web` avvia tutto quello che serve alla web app e apre il browser già autenticato:

```bash
rt web                 # http://127.0.0.1:8765
rt web --port 9000     # altra porta
rt web --no-browser    # stampa il link di accesso invece di aprire il browser
```

Il comando avvia in un solo processo l'API REST (`rt api`, vedi [API.md](API.md)), un
`rt worker` per i job (trascrizione, pipeline, immagini, recall) e l'interfaccia, servita
dall'API sulla stessa origine. Ctrl+C li ferma tutti. Tutto ascolta solo su `127.0.0.1`.

## Accesso

All'avvio `rt web` crea un link monouso (`/login?code=...`, valido 5 minuti) e apre il browser
già autenticato; la sessione resta con un cookie. Se il link è scaduto, riavvia `rt web` oppure
incolla nella pagina di accesso il token dell'API (stampato al primo avvio di `rt api`). **Esci**
chiude la sessione anche sul backend.

## Cosa si fa dalla web

La web fa tutto quello che si fa nel terminale; la tabella di parità, con i test che lo
verificano, è in [RT4_PARITY.md](RT4_PARITY.md). Tutto quello che salvi vive nel backend (DB e
cartella `media/`) e resta dopo la ricarica della pagina.

- **Dashboard:** lezioni raggruppate per materia con filtri, stato delle fasi, issue da
  valutare e costi.
- **Importa:** carichi l'audio, scegli data e materia e, se vuoi, avvii subito la pipeline.
- **Job:** i job in coda e in corso con gli eventi in tempo reale; si possono annullare. Se
  nessun worker è attivo la pagina lo segnala.
- **Lezione:** documento con i timecode cliccabili, player dell'audio con forma d'onda, fasi
  con validazioni, avvio di una singola fase, costi, download del Markdown o dello zip.
- **Scaletta:** vista ad albero dell'outline, approvazione o richiesta di modifiche.
- **Revisione:** le issue della review scientifica accanto al testo, con diff, frase
  evidenziata e audio al punto giusto; accetta, mantieni l'originale, modifica, annulla (anche
  da tastiera: `a`, `r`, `e`, `u`, frecce). Con l'ultima decisione la pipeline in attesa
  riparte da sola.
- **Recall:** riserva di domande, quiz, domande mirate e vaste, risposte scritte o a voce.
  Due selettori a slitta scelgono dove fare il recall (**Telegram** o **Qui**) e il tipo di
  domanda (Quiz, Mirata, Vasta, anche con le frecce della tastiera); sotto ciascuno c'è la
  scelta attiva. **Qui:** la sessione parte con la prima domanda e **Termina sessione** la
  chiude, con il riepilogo (domande, risposte date, quiz giusti) che resta dopo la ricarica.
  **Telegram:** **Avvia su Telegram** chiede al bot di aprire la sessione nel topic della
  materia; serve il bot configurato e avviato, altrimenti l'interruttore è disabilitato e la
  pagina dice cosa manca. Una sessione in corso su Telegram, avviata dall'app o dal bot, si vede
  nella pagina della lezione (e in quelle delle altre lezioni) e **Interrompi** la chiude:
  nel topic arriva «Sessione interrotta dall'app».
- **Immagini:** slide, foto o PDF da integrare nel documento finale, e immagini dal web:
  **Immagini per unità** è quante cercarne per ogni unità (0 = nessuna ricerca), su tutte le
  unità o su quelle scelte (caselle raggruppate per sezione, con «seleziona sezione»). Le
  immagini entrano nel documento come link Markdown, una sotto l'altra. La ricerca web richiede
  SearXNG: se manca, la pagina rimanda alle Impostazioni.
- **Bot Telegram:** stato, avvio e arresto del bot.
- **Impostazioni:** cartella lezioni, provider e chiavi (cifrate), modelli per fase, prezzi,
  Telegram e trascrizione. Al primo avvio una configurazione guidata chiede quello che manca.

## Installazione e aggiornamento

`install.sh` e `rt -u` installano la web app compilata dalla GitHub Release della versione
(`rt-spa-<versione>.tar.gz`, verificata con `SHA256SUMS`) nella cartella `rt/spa`. Se la
release non la contiene, `rt web` avvia comunque API e worker e l'indirizzo risponde con un
messaggio che spiega come ottenerla.

In un checkout di sviluppo la web app si compila da `frontend/` (`npm install && npm run build`,
vedi [frontend/README.md](../frontend/README.md)); la build in `frontend/dist` viene usata se
`rt/spa` non c'è. `RT_SPA_DIR` sceglie un'altra cartella.

## Interfaccia legacy (Gradio, deprecata)

`rt web --legacy` avvia ancora la vecchia interfaccia Gradio per questa release, con un avviso:
verrà rimossa nella prossima. Accetta `--lessons-root`, `--port` (default 7860), `--no-browser`
e `--log-file`.

L'interfaccia Gradio si avvia localmente e legge i dati esistenti di RT:
manifest, stato delle fasi, documento Markdown, issue di review, ledger delle
decisioni, file audio e configurazione. La review scrive le decisioni nel ledger RT
e aggiunge un registro delle azioni web nella stessa cartella della lezione.

### Avvio

Dopo aver installato o aggiornato RT:

```bash
rt web --legacy
```

Gradio non è più tra le dipendenze standard: per usarla installa
`requirements-web.txt` nel virtualenv (`./.venv/bin/python -m pip install -r requirements-web.txt`).

Se la cartella delle lezioni non è impostata in `config/general.yaml`, l'app si
apre sulla schermata Configurazione. Inserisci il percorso di una cartella
esistente oppure scegli dove crearne una nuova e premi **Salva**.
Il percorso viene salvato in `telegram.lessons_root`, mantenendo intatte le altre
impostazioni. Per provarne un'altra solo per la sessione corrente:

```bash
rt web --legacy --lessons-root "/percorso/alle/lezioni"
```

L'app si apre su `http://127.0.0.1:7860`. Si può usare `--port 7868` per cambiare
porta o `--no-browser` per non aprire automaticamente il browser. `bin/rt-web`
resta disponibile come avvio diretto equivalente. Il server ascolta
solo su `127.0.0.1` e non genera un link pubblico Gradio.

Il terminale mostra avvio, richieste HTTP, durata delle azioni, errori Python e
segnalazioni dal browser. Gli stessi eventi vengono salvati in un file locale a
rotazione (5 MB per file, tre copie): su macOS `~/Library/Logs/rt/web.log`, oppure
nel percorso scelto con `--log-file`. `RT_WEB_LOG` permette la stessa scelta via
variabile d'ambiente. I log non includono corpi delle richieste né il percorso dei
file audio serviti. Premi Ctrl+C per fermare il server.

### Schermate

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
