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

## Novità della fase FA

La fase FA ha consolidato la web dopo il primo uso reale. In breve:

- **Job più robusti (FA1):** una risposta del modello fuori schema dà un errore leggibile; **Riprova** riprende un job fallito dalla fase in cui si era fermato;
  il worker avvisa su Telegram a fine lezione (se le notifiche sono accese); i job su lezioni diverse girano in parallelo
  (numero regolabile in Impostazioni).
- **Documento come conferma (FA2):** il documento finale è la conferma dell'anteprima e non
  dipende più dalla revisione, che dà solo avvisi nel dialogo di conferma. Recall, immagini e
  download funzionano già dopo la rielaborazione.
- **Anteprima modificabile (FA3, beta):** il timecode sta sotto il titolo di ogni unità e la
  matita sul documento apre un editor Markdown (vedi "Modificare l'anteprima").
- **Navigazione (FA4):** ricerca immediata anche per materia e data, barra laterale riducibile
  a icone per materia, sezione **Review** con le lezioni che hanno issue da valutare.
- **Impostazioni (FA5):** modelli per fase anche nella configurazione guidata, **Prova** del
  modello prima di salvarlo, pricing con avvisi, SearXNG per la ricerca immagini da
  Impostazioni › Ricerca web, campi segreti che non attivano il portachiavi del Mac.
- **Cartella dati e Telegram (FA6):** scelta della cartella con Finder o con il navigatore,
  anteprima di token e Chat ID (dalla versione successiva alla 4.2.5 Telegram manda solo
  notifiche).
- **Recall e immagini (FA7):** la sessione di recall si termina con un riepilogo; le immagini
  dal web si cercano per unità, sulle unità scelte.
- **Revisione e player (FA8):** revisione ordinabile per tipo e gravità, velocità del player
  regolabile da 0.5× a 3×.
- **Chiusura (FA9):** l'interfaccia non cita più comandi del terminale; un test lo controlla.

## Accesso

All'avvio `rt web` crea un link monouso (`/login?code=...`, valido 5 minuti) e apre il browser
già autenticato; la sessione resta con un cookie. Se il link è scaduto, riavvia `rt web` oppure
incolla nella pagina di accesso il token dell'API (stampato al primo avvio di `rt api`). **Esci**
chiude la sessione anche sul backend.

### Da iPhone o da un altro dispositivo

RT ascolta solo su `127.0.0.1`. Il modo consigliato per raggiungerlo da iPhone è Tailscale
Serve, che lo pubblica soltanto nella tua tailnet, in HTTPS (necessario per il recall a voce):

1. Installa Tailscale sul Mac e sull'iPhone con lo stesso account; nella console di Tailscale
   abilita MagicDNS e i certificati HTTPS.
2. Sul Mac: `tailscale serve --bg 8765` (resta attivo ai riavvii; `tailscale serve status`
   mostra l'indirizzo, del tipo `https://nome-mac.tailnet.ts.net`).
3. Nella web app sul Mac: **Impostazioni > Generali > Accesso da un altro dispositivo**: RT
   propone da solo quell'indirizzo (lo legge da Tailscale, su qualunque Mac); premi **Crea QR di
   accesso** e inquadra il QR con l'iPhone. Non usare l'IP 100.x: il certificato HTTPS di
   Tailscale vale solo per il nome del Mac.
4. Su iPhone: Condividi > Aggiungi alla schermata Home.

Non usare `tailscale funnel`: renderebbe RT pubblico su Internet.

## Cosa si fa dalla web

La web è l'interfaccia completa di RT (nel terminale restano i comandi); la tabella di parità, con i test che lo
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
- **Notifiche Telegram:** a fine pipeline, e dopo il solo documento, il worker manda "Lezione
  pronta"; quando un job si ferma sulla scaletta da approvare (se non si approva da sola) o
  sulle issue da decidere, e quando una lavorazione non riesce, manda un avviso (solo con le
  notifiche accese e configurate; in modalità prova no). Se l'invio non riesce il job non cambia
  esito e l'errore compare tra gli eventi.
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
- **Pagina Recall (`/recall`):** le lezioni raggruppate per materia, in schede o in tabella
  (domande da porre per tipo e risposte date), ordinate per data, titolo o domande da porre;
  vista, ordine e materie chiuse restano nel browser come nella pagina Lezioni. **Recall della
  materia** apre `/recall/materie/<materia>`: una sessione con la stessa logica di quella di una
  lezione, ma le domande arrivano a turno da tutte le lezioni della materia, con risposta, voto, salto, **Termina sessione** e riepilogo. La pagina
  genera anche le domande delle lezioni che non ne hanno ancora. La scelta della domanda è in
  `rt/services/recall_subject.py`.
- **Recall:** pool di domande dell'intera lezione dalle unità scelte (di predefinito le
  rilevanti, con score e livello del classificatore), quiz, domande mirate e vaste, risposte
  scritte o a voce. **Rigenera pool** passa al recaller tutte le unità selezionate e aggiunge domande a
  quelle già generate; la pagina **Domande** le mostra tutte e permette di eliminare,
  anche in blocco, quelle che non convincono. Quando
  restano 5 quiz, 3 mirate o 2 vaste da porre ne arrivano altre da unità scelte a caso.
  Il selettore a slitta sceglie il tipo di domanda (Quiz, Mirata, Vasta, anche con le frecce
  della tastiera). La sessione parte con la prima domanda e **Termina sessione** la chiude, con
  il riepilogo (domande, risposte date, quiz giusti) che resta dopo la ricarica.
- **Immagini:** slide, foto o PDF da integrare nel documento, e immagini dal web:
  **Immagini per unità** è quante cercarne per ogni unità (0 = nessuna ricerca), su tutte le
  unità o su quelle scelte (caselle raggruppate per sezione, con «seleziona sezione»). Le
  immagini entrano nel documento come link Markdown, una sotto l'altra. La ricerca web richiede
  SearXNG: se manca, la pagina rimanda alle Impostazioni. Si aggiungono alla bozza e compaiono
  subito nell'anteprima.
- **Impostazioni:** cartella dati (solo lettura), provider e chiavi (cifrate), modelli per fase, prezzi,
  ricerca web, Telegram e trascrizione. La configurazione guidata (aperta dall'installer) chiede quello
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

Il worker esegue fino a **8** lezioni insieme, una sola fase alla volta per lezione: due job sulla
stessa lezione non girano mai insieme (vincolo `active_lesson` della coda), quindi il parallelismo
vale tra lezioni diverse. Le trascrizioni locali vanno comunque una alla volta.
`rt worker --concurrency N` resta per l'uso a mano (predefinito: 8).

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

Telegram serve solo per le notifiche nella chat personale: lezione pronta, scaletta da
approvare, issue da decidere, lavorazione non riuscita. Le manda il worker; non c'è un bot
sempre acceso, né comandi, topic o recall in chat.

- **Ricevi le notifiche su Telegram:** l'interruttore (spento di predefinito).
- **Collegamento in quattro passi:** crei un bot con @BotFather, incolli il token, scrivi
  `/start` al bot e premi **Collega la chat**: RT legge l'ultimo messaggio ricevuto dal bot e
  salva la chat personale da cui è arrivato (i messaggi dei gruppi non contano).
- **Token e Chat ID salvati:** il campo del token resta vuoto (lascialo vuoto per mantenere quello
  salvato) e sotto compare un'anteprima parzialmente nascosta, per esempio `1234…wXyZ`. Il
  pulsante con l'occhio mostra il valore completo, che la pagina chiede al backend solo in quel
  momento.
- **Manda un messaggio di prova:** controlla che token e chat funzionino.
- **Ultime notifiche inviate:** le ultime 20, anche quelle non partite.

## Installazione e aggiornamento

`install.sh` e `rt -u` installano la web app compilata dalla GitHub Release della versione
(`rt-spa-<versione>.tar.gz`, verificata con `SHA256SUMS`) nella cartella `rt/spa`. Se la
release non la contiene, `rt web` avvia comunque API e worker e l'indirizzo risponde con un
messaggio che spiega come ottenerla.

In un checkout di sviluppo la web app si compila da `frontend/` (`npm install && npm run build`,
vedi [frontend/README.md](../frontend/README.md)); la build in `frontend/dist` viene usata se
`rt/spa` non c'è. `RT_SPA_DIR` sceglie un'altra cartella.
