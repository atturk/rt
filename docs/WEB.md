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
- **Ricerca:** la dashboard e gli elenchi di Recall, Immagini e Review hanno la stessa barra:
  testo, materia e stato. Il testo cerca nel titolo, negli argomenti, nella materia e nella data,
  che si può scrivere come `2026-09-26`, `26/09/2026`, `26-09-2026` o `26 settembre 2026`; con
  più parole compaiono le lezioni che le contengono tutte. Il punto interrogativo accanto a
  **Cerca** lo ricorda (al passaggio del mouse e al focus da tastiera). Il filtro lavora
  nel browser sull'elenco già caricato, quindi risponde subito a ogni tasto; i filtri restano
  nell'indirizzo (`?q=&materia=&stato=`) e dopo la ricarica.
- **Importa:** carichi l'audio, scegli data e materia e, se vuoi, avvii subito la pipeline.
- **Job:** i job in coda e in corso con gli eventi in tempo reale; si possono annullare. Se
  nessun worker è attivo la pagina lo segnala. La voce **Job** del menu porta un badge con il
  numero di job attivi più quelli in attesa di una tua decisione (arancione se c'è una decisione
  da prendere o nessun worker attivo).
  Nelle fasi a unità (rielaborazione, revisione) il dettaglio mostra l'unità in lavorazione sul totale, per esempio "Revisione · 8/31".
  L'elenco degli eventi segue gli ultimi finché sei in fondo; se scorri verso l'alto per
  leggere si ferma e il pulsante **Vai agli ultimi** lo riporta in coda.
- **Riprova:** un job fallito ha il pulsante **Riprova** accanto allo stato "Fallito", nel
  dettaglio del job e nel pannello job della lezione. Crea un job nuovo con lo stesso tipo e le
  stesse opzioni, collegato al vecchio (i due dettagli si linkano a vicenda), che riparte dalla
  fase fallita: le fasi già valide si saltano e le unità già fatte non si rifanno (una pipeline o
  una fase forzata non riparte da zero). Se sulla lezione sta già lavorando un altro job, Riprova
  lo dice e non crea nulla. I file caricati di un job fallito restano per il nuovo tentativo e si
  cancellano quando questo finisce (quelli mai ripresi dopo 7 giorni).
- **Risposte fuori schema:** se un modello risponde con testo invece del JSON richiesto (nel
  primo test reale `openrouter/free` ha risposto "User Safety: safe / Response Safety: safe"), RT
  ripete la richiesta sulla stessa route ricordando il formato e poi passa alle altre route
  configurate. Se un'unità non riesce comunque, le altre proseguono: la fase finisce parziale e
  il job fallisce con un messaggio che dice modello, unità e inizio della risposta. Riprova rifà
  solo le unità mancanti.
- **Notifica Telegram:** a fine pipeline, e dopo il solo documento, il worker manda la notifica
  "Lezione pronta" come da terminale (se Telegram è configurato; in modalità prova no). Se
  l'invio non riesce il job resta completato e l'errore compare tra gli eventi.
- **Review:** le lezioni con issue della review scientifica da valutare, con il numero per
  ciascuna; un clic apre la revisione della lezione.
- **Lezione:** documento con i timecode cliccabili, player dell'audio con forma d'onda (clic
  sulla velocità: slider da 0.5× a 3×, anche da tastiera; la scelta resta nel browser), fasi
  con validazioni, avvio di una singola fase, costi, download del Markdown o dello zip.
  Nell'intestazione **Recall**, **Immagini**, **Markdown** e **Tutti i dati (zip)** stanno sempre
  nello stesso ordine e posto: quando un'azione non è ancora disponibile il pulsante resta
  visibile, disabilitato, e il suo suggerimento dice cosa manca.
- **Scaletta:** vista ad albero dell'outline, approvazione o richiesta di modifiche.
- **Revisione:** le issue della review scientifica accanto al testo, con diff, frase
  evidenziata e audio dal timecode dell'unità; accetta, mantieni l'originale, modifica, annulla
  (anche da tastiera: `a`, `r`, `e`, `u`, frecce). Le issue da decidere si ordinano per
  timecode o per tipo e gravità (prima gli errori concettuali più gravi; `?ordine=gravita`
  nell'indirizzo) e dopo ogni decisione si passa alla successiva in quell'ordine. Con l'ultima
  decisione la pipeline in attesa riparte da sola.
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
- **Immagini:** slide, foto o PDF da integrare nel documento, e immagini dal web:
  **Immagini per unità** è quante cercarne per ogni unità (0 = nessuna ricerca), su tutte le
  unità o su quelle scelte (caselle raggruppate per sezione, con «seleziona sezione»). Le
  immagini entrano nel documento come link Markdown, una sotto l'altra. La ricerca web richiede
  SearXNG: se manca, la pagina rimanda alle Impostazioni. Si aggiungono alla bozza e compaiono
  subito nell'anteprima.
- **Bot Telegram:** stato, avvio e arresto del bot; il gruppo configurato (Chat ID e token con
  l'occhio per vederli per intero); i topic per materia, ciascuno con il pulsante **Prova**; le
  ultime notifiche inviate (lezione pronta, issue da rivedere, prove dei topic); un link alle
  impostazioni di Telegram.
- **Impostazioni:** cartella lezioni, job in parallelo, provider e chiavi (cifrate), modelli per fase, prezzi,
  ricerca web, Telegram e trascrizione. Al primo avvio una configurazione guidata chiede quello
  che manca; si riapre dal link **Configurazione guidata →** in cima alle impostazioni.
  - **Modelli:** nel passo Modelli della configurazione guidata si usa di norma lo stesso modello
    per tutte le fasi; **Scegli per ogni fase** mostra le sei fasi (Outline, Rewrite, Review,
    Recall, Descrizione immagine, Giudice immagini) con connessione e modello ciascuna, come nella
    scheda Modelli. Accanto a ogni **Salva** c'è **Prova**: una chiamata minima (prompt di poche
    parole, pochi token di uscita, costo quasi nullo) alla connessione e al modello scritti nel
    form, anche prima di salvarli. Mostra se il modello risponde, la latenza e l'eventuale errore
    del provider.
  - **Costi:** il provider si sceglie tra quelli delle connessioni e il modello tra quelli in uso
    nelle fasi. Un valore diverso mostra un'icona di avviso nel campo ("Provider non configurato",
    "Modello non in uso"), ma si salva lo stesso. IN, OUT e R sono i prezzi per milione di token
    in input, in output e di ragionamento (se il provider lo fa pagare a parte). La stima non
    considera il caching dei token: il costo reale può essere più basso.
  - **Ricerca web:** l'URL base di un'istanza SearXNG (per esempio `http://localhost:8088`) per
    cercare immagini da aggiungere alle lezioni. **Prova** fa una ricerca immagini di prova e dice
    quante ne tornano; **Salva** lo registra nelle impostazioni, che l'aggiunta immagini rilegge a
    ogni job. SearXNG deve avere il formato json abilitato (`search.formats` nel suo
    `settings.yml`): se manca, la prova e la ricerca lo segnalano.
  - I campi delle chiavi e del token del bot sono mascherati ma non sono campi password, così
    Safari e il portachiavi di iCloud non propongono password salvate.

## Job in parallelo

Il worker avviato da `rt web` esegue fino a **2** job insieme (Impostazioni > Generali, "Job in
parallelo", da 1 a 4; si salva in `config/general.yaml`, `worker.concurrency`). Due job sulla
stessa lezione non girano mai insieme: il secondo aspetta (vincolo `active_lesson` della coda),
quindi il parallelismo vale tra lezioni diverse, per esempio la trascrizione di una lezione nuova
mentre un'altra è in revisione. Il valore si applica al riavvio: `rt web` lo legge all'avvio e lo
passa al worker (`rt worker --concurrency N`). `rt worker` lanciato a mano resta a 1 thread se
non si indica `--concurrency`.

## Barra laterale

La barra a sinistra elenca le lezioni per materia. Il pulsante in alto la **riduce** a una
colonna di icone, una per materia, e la riespande; la scelta resta nel browser anche dopo la
ricarica. Da ridotta:

- ogni icona mostra il nome completo della materia al passaggio del mouse e al focus;
- clic o Invio aprono accanto un pannello con le lezioni della materia, senza espandere la
  barra; un clic su una lezione la apre, Esc o un clic fuori chiudono il pannello;
- da tastiera: Tab arriva alle icone, frecce su e giù (Home, Fine) passano fra le materie.

Riespandendo la barra, le materie aperte o chiuse e la lezione selezionata restano come prima.
Su schermi stretti la barra resta il menu a comparsa di sempre.

Le icone sono le iniziali delle prime quattro parole significative del nome della materia,
senza articoli, preposizioni e congiunzioni (anche elise: *Medicina d'urgenza* → MU); numeri e
numeri romani in fondo restano (*Patologia generale 1* → PG1). Una iniziale è centrata, due
affiancate, tre due sopra e una sotto, quattro in griglia 2×2. Il colore pastello viene dal
nome: è sempre lo stesso per la stessa materia e materie con le stesse iniziali hanno colori
diversi.

## Documento finale: la conferma

Il documento finale (fase **Documento**) è la conferma di quello che vedi: l'anteprima della
lezione, cioè la bozza con le decisioni della revisione prese finora e le immagini aggiunte,
diventa l'elaborato finale.

- **Cosa serve:** preparazione, scaletta e rielaborazione aggiornate. La revisione non blocca:
  se non è aggiornata o è incompleta, o se restano issue da valutare o issue orfane (issue che
  non trovano più il loro testo nella bozza), il documento si crea lo stesso.
- **Avvisi prima di confermare:** questi controlli compaiono sotto la fase Documento e, quando
  premi **Esegui**, in un dialogo che li elenca (per esempio "3 issue ancora da valutare",
  "2 issue orfane", "Revisione non aggiornata"), con **Crea il documento comunque** e
  **Annulla**. La pipeline completa si comporta come prima: si ferma sulle issue da decidere e
  crea il documento dopo l'ultima decisione.
- **Quando va rifatto:** il documento resta aggiornato finché non cambiano bozza, scaletta,
  segmenti, decisioni della revisione, immagini o modifiche fatte a mano all'anteprima; una nuova revisione da sola non lo rende
  superato (servono le decisioni sulle sue issue).
- **Prima del documento finale:** recall, immagini e download funzionano già dopo la
  rielaborazione. Il download usa il documento finale se esiste ed è aggiornato, altrimenti
  l'anteprima: il file ha "(anteprima)" nel nome e lo zip contiene un file LEGGIMI che lo spiega.
  Le immagini aggiunte compaiono subito nell'anteprima ed entrano nel documento finale al
  build successivo; se il documento finale c'era già, diventa da rifare.

`rt status` segue la stessa regola: mostra la fase `build` indipendente dalla review e, sotto
le fasi, gli stessi avvisi.

## Modificare l'anteprima (beta)

Nella pagina della lezione, in alto a destra del documento, la matita (**Modifica
l'anteprima**) trasforma l'anteprima in un editor Markdown, con l'anteprima renderizzata
accanto. Prima di entrare compaiono due avvisi, ciascuno con **Non mostrare più** (salvato
nelle impostazioni, vale su ogni browser): se la lezione ha issue da valutare, che modificare a
mano un passaggio segnalato può rendere orfana la sua issue; sempre, che è una funzione beta e
che per modifiche importanti conviene creare il documento, scaricare il Markdown e modificarlo
in un editor esterno.

Nell'editor si cambiano titoli, testo, link e percorsi delle immagini. La struttura resta
quella della scaletta: non si aggiungono né si tolgono sezioni (`## 1. Titolo`) o unità
(`### 1.1 Titolo`). Il timecode di un'unità è la riga subito sotto il suo titolo, da solo:

```markdown
### 1.2 Il ciclo di Krebs
12:30

Testo dell'unità…
```

Si scrive `MM:SS` o `H:MM:SS`. Cambiarlo sposta l'inizio dell'unità nell'audio: deve stare
dentro la durata della registrazione e crescere da un'unità alla successiva; RT lo porta
all'inizio della frase dell'audio in cui cade. Gli errori compaiono sopra l'editor mentre
scrivi, con la riga (il link porta alla riga) e il motivo.

**Fine** o un clic fuori dall'editor salvano, **Esc** o **Annulla** lasciano tutto com'era.
Dopo il salvataggio la pagina ricorda che il documento finale va ricreato (fase Documento) e,
se il testo di qualche issue non c'è più, quante issue sono diventate orfane: restano
nell'elenco e compaiono negli avvisi della conferma del documento. Le decisioni della revisione
già prese sono dentro il testo che hai modificato e non vengono riapplicate.

## Cartella dati e Telegram nelle impostazioni

### Cartella dati

Nelle impostazioni e nel primo passo della configurazione guidata la cartella si sceglie con
**Scegli cartella…**, senza scrivere il percorso. Su macOS si apre la finestra di Finder; dove non
è disponibile (o se la chiudi con Annulla) compare un piccolo navigatore delle cartelle della
tua home: entri nelle cartelle, torni su, e premi **Usa questa cartella**. Il navigatore mostra
solo cartelle, mai file, e solo dentro la home. **Inserisci il percorso a mano** resta
l'alternativa (per esempio per un disco esterno). Poi **Salva**: se la cartella non esiste RT la
crea.

### Telegram

- **Token del bot e Chat ID:** dopo il salvataggio i campi restano vuoti (lasciali vuoti per
  mantenere i valori salvati) e sotto compare un'anteprima parzialmente nascosta, per esempio
  `1234…wXyZ` o `-100…7890`. Il pulsante con l'occhio mostra il valore completo, che la pagina
  chiede al backend solo in quel momento; premendolo di nuovo torna l'anteprima. Vale anche
  nella configurazione guidata.
- **Ascolta i topic per 20 secondi:** mentre ascolta, scrivi un messaggio in ogni topic dal
  telefono. RT aggiunge i topic trovati con il loro nome su Telegram e, se il nome coincide con
  una materia che RT conosce già (maiuscole e accenti non contano), propone anche la materia.
  Se Telegram non dice il nome (per esempio per un messaggio in risposta a un altro), il topic
  arriva senza nome e la materia la scrivi tu. I nomi si salvano con i topic.
- **Prova:** accanto al cestino di ogni topic invia nel topic il messaggio "Questo è il topic di
  MATERIA" e mostra l'esito.
- **Cancella i messaggi di rilevamento:** dopo una conferma elimina dal gruppo solo i messaggi
  ricevuti durante l'ultimo ascolto (mai altri messaggi, né quelli con cui Telegram crea i
  topic). Serve che il bot sia amministratore del gruppo; Telegram non permette di cancellare i
  messaggi più vecchi di 48 ore. Alla fine la pagina dice quanti messaggi ha eliminato e quali no,
  con il motivo.

### Esportare o ripulire la chat di un topic (non disponibile)

Un bot di Telegram non può leggere lo storico di una chat: riceve solo i messaggi che arrivano
mentre è in ascolto. Per esportare tutti i messaggi di un topic o ripulirlo servirebbe un
client che accede con il tuo account Telegram; per ora RT non lo fa.

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
