# QA notturna RT 4.3.6 — frontend desktop e iPhone (notte 2-3 novembre 2026)

Macchina: MacBook Pro di prova, RT aggiornato dall'app da 4.3.6b1 a **4.3.6** (build 105 · 09dcdfc).
Strumenti: Playwright (Chromium) + MCP rt, log `~/.rt/logs`. Passata 1 desktop 1440×900; passata 2 iPhone emulato (393×852, tocco, user agent iOS Safari, DPR 3).
Spesa LLM stanotte: **0,0006 USD** (una rielaborazione di 6 s di audio). Contatore RT: 3,1210 → 3,1216 USD. Totale QA dall'inizio ~0,71 USD.
Screenshot: cartella `shots/` accanto a questo file (`d-` desktop, `i-` iPhone, `m-` 390 px senza tocco).

Branch con l'unico fix fatto stanotte: `claude/qa-notte-437` (da main 4.3.6, 1 commit, push fatto, **nessuna PR aperta**).

---

## Riassunto per agy (4.3.7), in ordine di gravità

| # | Gravità | Dove | Problema | Stato |
|---|---|---|---|---|
| 1 | **Urgente** | Archivio, Info, popup import | Lezioni fantasma di prove nel DB reale → 500 su 3 endpoint, «Alleggerisci l'audio» sempre spento | **Fix robustezza sul branch**; resta la causa |
| 2 | **Urgente** | Studio lezione 30 | Un'ancora non valida nel ledger → `study-notes` 500, lo Studio dice «serve la rielaborazione» | Da fare |
| 3 | **Urgente (iPhone)** | Calendario | Popup dello slot: sesta icona tagliata, 6 icone senza etichetta | Da fare |
| 4 | **Urgente (iPhone)** | Lezioni | Titolo «Lezioni» tagliato in «L…» | Da fare (fix semplice provato e scartato, vedi sotto) |
| 5 | **Urgente (UX)** | Lezione dopo «Solo trascrizione» | Nessun pulsante per proseguire; «Aggiorna» → Estendi/Ricostruisci con avviso allarmante | Da fare |
| 6 | **Urgente (contenuti)** | Domande | Le domande già fatte su unità con segnalazioni aperte restano nella sessione | Da fare |
| 7 | Medio | iPhone | Nessun «Nuova lezione» nella barra in basso | Da decidere |
| 8 | Medio | Lezioni 74 e 15 | Errori grezzi Python/inglese mostrati all'utente | Da fare |
| 9 | Medio | Verifica su iPhone | Icone senza testo, «Nel testo» mostra tutto il paragrafo, warning del virtualizzatore | Da fare |
| 10 | Medio | Studio su iPhone | 5 icone senza testo, pallini arancioni non spiegati | Da fare |
| 11 | Medio | Dettagli su iPhone | Nomi delle fonti troncati con spazio libero a fianco | Da fare |
| 12 | Medio | Lezioni → «N lezioni mancanti» | Il popup mostra solo gli orari, non la materia | Da fare |
| 13 | Minore | Aggiornamento | ~30 s fermo a «99%» senza messaggio | Da fare |
| 14 | Minore | Desktop stretto con mouse | Scroll orizzontale di 60 px nelle pagine lezione sotto 768 px | Da fare |
| 15-21 | Minore | Vari | Date ISO, gergo nei job, avvisi del popup import, maiuscole materie, rumore 404/409, `<main>` annidati | Da fare |
| 22 | Processo | CI | Release lenta: test ripetuti | Passato al thread release (Attilio ha approvato) |

Cose che **funzionano** (nuove nella 4.3.6): aggiornamento dall'app, avviso registrazione già caricata, conferma materia nuova, audio finto/vuoto rifiutati subito con messaggio chiaro e **senza lezione orfana**, LaTeX della 68 riparato (RTPL, sched), Studio con «12 punti da verificare · Apri Verifica», nessuna pagina sopra 2,4 s, nessun errore JavaScript a parte le risposte 500 elencate, nessuno scroll orizzontale su iPhone emulato.

---

## 0. Aggiornamento dall'app (test dell'updater)

Impostazioni → Info e aggiornamenti → «È disponibile RT 4.3.6» → Scarica (212,0 MB) → Installa e riavvia.

| Passo | Ora locale | Durata |
|---|---|---|
| Release v4.3.6 pubblicata su GitHub | 23:25:49 | — |
| Clic su «Scarica» | 23:30:27 | — |
| Download 0 → 99% | | 3 min 25 s (~1 MB/s) |
| Fermo a «99%», poi compare «Installa e riavvia» | | **~33 s senza messaggio** |
| Clic su «Installa e riavvia» → API risponde 4.3.6 | 23:34:40 → 23:34:54 | 14 s |

La pagina non si è ricaricata prima del riavvio (correzione 4.3.6b1 confermata) e mostra 4.3.6 da sola. Durante il riavvio la console registra ~10 `ERR_CONNECTION_REFUSED` su `/health` e `/system/update` (atteso, polling).

![](shots/00-aggiornamento-disponibile.png) ![](shots/01-pronto-installa.png) ![](shots/02-aggiornato-436.png)

**#13 [minore]** Gli ultimi ~30 s (verifica checksum/estrazione) restano su «Scarico RT 4.3.6 (99%)…». Proposta: «Verifico il pacchetto…».

---

## 1. [URGENTE] Lezioni fantasma di prove nel database reale

**Cosa si vede**
- In Lezioni, gruppo «Senza data»: `tmp2fizm4fm` e `lesson_4`. Il 5 settembre ci sono due BIOCHIMICA (una con il testo «MOCK Correzione #1 … #10»). Screenshot: `shots/d-lezioni.png` (fondo pagina), `shots/d-l77.png`, `shots/d-l78.png`.
- Le materie BIOCHIMICA (2 lezioni) e MATERIA INESISTENTE compaiono in Impostazioni → Materie e nel menu Materia dei Dettagli di ogni lezione.
- **Impostazioni → Info → «Alleggerisci l'audio delle lezioni» è sempre disattivato** senza spiegazione, perché la sua anteprima va in 500.
- Pannello Arricchimento → Archivio vuoto (`/archive/summary` 500), e aggiungere un materiale nel popup Nuova lezione fa 500 su `/archive/lookup`.

**Dati**
```
id 75  storage=folder  /private/var/folders/ny/…/T/tmp2fizm4fm              created 2026-11-02 08:37:36
id 76  storage=folder  /private/var/folders/ny/…/T/tmp6emfp320/lesson_4     created 2026-11-02 09:32:41
id 77  BIOCHIMICA 2026-09-05  …/T/tmpi2l0rqs8/out/[2026-09-05] BIOCHIMICA      created 2026-11-02 11:18:58
id 78  BIOCHIMICA 2026-09-05  …/T/tmp4__6a7k4/cli/out/[2026-09-05] BIOCHIMICA  created 2026-11-02 11:24:05
```
Le cartelle 75 e 76 esistono ancora ma non hanno `info.yaml`. Stanotte (23:30-23:55): 13× 500 su `GET /system/compact-audio/preview`, 8× su `GET /archive/summary`, 1× su `POST /archive/lookup`, tutti con:
```
rt/services/archive_service.py:21 usage_index → read_info_yaml
FileNotFoundError: info.yaml non trovato in '/private/var/folders/…/T/tmp2fizm4fm/_state/info.yaml'
```
`indexed_lesson_ids()` scarta le lezioni folder la cui cartella non esiste, ma qui la cartella esiste (senza info.yaml). Inoltre **RT ricrea `_state/` dentro quelle cartelle** quando le legge (data di modifica 23:42 e 23:45, durante i miei test).

**Fix fatto** (branch `claude/qa-notte-437`, commit `adb05e82`, +2 test di regressione che falliscono senza il fix):
- `audio_compaction.all_lessons_list`: considera solo le lezioni del DB che hanno `info.yaml`.
- `archive_service.usage_index`: salta le lezioni senza `info.yaml`.
- `tests/test_audio_compaction.py`, `tests/test_archive.py`: 18 passati.

**Da fare in 4.3.7**
1. Trovare chi ha registrato queste lezioni sul Pro il 2/11 tra le 08:37 e le 11:24 UTC. Non è pytest: `tests/conftest.py` isola dati e DB. È probabile un comando CLI o uno script (agy?) lanciato su cartelle temporanee con la cartella dati vera. Il nome `cli/out` della 78 lo suggerisce.
2. Non indicizzare cartelle sotto la cartella temporanea di sistema, oppure non registrare nel DB le lezioni create da comandi su percorsi esterni senza conferma.
3. Leggere una lezione non deve creare `_state/`.
4. Dare all'utente un modo per togliere le lezioni con la cartella mancante o rotta («Rimuovi dall'elenco»).
5. Le lezioni 75-78 **non le ho cancellate**: decide Attilio (export prima; la 75 e la 76 non hanno nulla da esportare).

---

## 2. [URGENTE] Ledger della lezione 30 non valido → Studio rotto

`GET /lessons/30/study-notes` → 500 (5 volte stanotte):
```
rt/pipeline/ledger.py:267 load_resolved_draft → review_migration.py:329 migrate_review_anchors → ledger.py:38 load_ledger (strict)
ValidationError: decisions.12.anchor — Posizioni incoerenti con la citazione
  {'quote': 'La trattazione…', 'start': 0, 'end': 2734}
```
Una sola decisione con ancora incoerente blocca tutto: in modalità strict solleva l'errore, in quella non strict restituisce **un ledger vuoto** (decisioni sparite senza avviso). Nello Studio la 30 compare come «Nessuna lezione pronta per lo Studio: serve la rielaborazione», un messaggio fuorviante (`shots/d-studio-30.png`).
Proposta: nella validazione, scartare o ricalcolare solo l'ancora rotta (e scriverlo in api.log) invece di invalidare tutto il ledger; e controllare quante altre lezioni hanno lo stesso problema.

---

## 3. [URGENTE iPhone] Calendario: popup dello slot tagliato

Tocco su «DATA MINING 09:30–11:30»: il popup ha 6 pulsanti di stato solo icona (orologio, spunta, !, salta, divieto, documento) e **il sesto è tagliato dal bordo del popup**. La data è in formato ISO «2026-11-02». In basso ci sono «Nessuna registrazione», 🔗 e «+»: dal telefono il «+» è l'unico modo per creare una lezione (vedi #7), ma niente lo dice.

![](shots/i-cal-1-tap.png)

Proposta: popup largo quanto lo schermo su telefono (o icone su due righe), etichette sotto le icone, data come «lun 2 nov».

---

## 4. [URGENTE iPhone] Titolo «Lezioni» tagliato in «L…»

`h1` largo 40 px per un testo di 71 px: i pulsanti Data, Recenti, cerca, fissa e seleziona occupano tutta la riga (`shots/i-lezioni.png`).
Ho provato `max-md:min-w-32` sul titolo in `PageHeader.tsx`: il titolo si vede, ma su tutte le altre pagine (lezione, job) la barra va a capo su due righe e la pagina della lezione mostra una riga vuota sopra le icone (`shots/i-lezioni-fix-titolo.png`, `shots/i-fix-_lezioni_68.png`). **Fix ritirato.**
Proposta: su telefono rendere «Data» e «Recenti» solo icona, oppure spostare fissa/seleziona in un menu «…».

---

## 5. [URGENTE UX] Dopo «Solo trascrizione» non si capisce come proseguire

Flusso: Nuova lezione → audio → «Solo trascrizione» → Avvia. Il job finisce in 1,1 s; la pagina della lezione mostra:
- «Fonti nuove non ancora usate: demo_lecture.m4a · Aggiorna»: l'audio appena trascritto passa per una fonte nuova;
- «Questa lezione non è ancora pronta. **Avvia l'elaborazione** o riprova se si è interrotta.», ma un pulsante Avvia non c'è;
- «Aggiorna» apre «+ Estendi: aggiunge unità, non tocca quelle esistenti» e «↻ Ricostruisci: rifà la scaletta da zero»;
- Ricostruisci chiede «Ricostruire la lezione? … Le unità cambiate perdono decisioni e stato di studio», su una lezione che non ha ancora nessuna unità.

![](shots/d-nuova-lezione-5-creata.png) ![](shots/d-l79-aggiorna-0.png) ![](shots/d-l79-ricostruisci-0.png)

Con Ricostruisci funziona: 12,5 s (23:57:17 → 23:57:29), 0,0006 USD, avanzamento visibile in pagina (Scaletta 0% → Rielaborazione unità 1 di 1 → documento), `shots/d-l79-run-*.png`, `shots/d-l79-finale.png`.
Proposta: per le lezioni senza scaletta, mostrare un solo pulsante «Continua: scaletta e rielaborazione» al posto di Aggiorna/Estendi/Ricostruisci, e non contare come «fonte nuova» l'audio già trascritto.

---

## 6. [URGENTE contenuti] Domande vecchie su unità con segnalazioni aperte

La 4.3.6 salta le unità con segnalazioni aperte solo **quando genera** domande nuove (`rt/pipeline/recall.py:652`). Le domande già presenti restano:
- la sessione «Ripassa» della 68 parte da «QUIZ · unità 1.2 · domanda 1», e l'unità 1.2 ha una segnalazione aperta (pannello Verifica: «Con issue»), `shots/i-recall-0.png`;
- il pannello Domande elenca come «da porre» i quiz dell'unità 1.1, compreso «Che cosa rappresenta il parametro e_j», la cui risposta è proprio la definizione contestata (sci_000003 ancora aperta), `shots/d-l68-panel-Domande.png`.

Proposta: nella sessione, saltare o contrassegnare («la verifica ha dubbi su questa unità») le domande delle unità con segnalazioni aperte; dopo l'accettazione della correzione, proporre di rigenerarle.

---

## 7. [MEDIO] iPhone: «Nuova lezione» non raggiungibile dalla barra

La barra in basso ha 4 schede (Lezioni, Calendario, Job, Impostazioni); il «+» esiste solo nella barra laterale desktop (`Layout.tsx:158`, `!phone`). Dal telefono si crea una lezione solo dal «+» del popup di uno slot del calendario (#3). Se è voluto, va detto; se no, serve un «+» (ad esempio in alto in Lezioni). Esiste già `VoiceRecorder.tsx`: registrare dal telefono sarebbe naturale.

## 8. [MEDIO] Errori tecnici mostrati all'utente nelle lezioni vecchie

- 74: «SetupError: Trascrizione macparakeet-cli JSON fallita per 'finto-audio.mp3' (codice uscita: 1). Dettagli errore:» (vuoto). La 4.3.6 rifiuta subito i file così, ma le lezioni fallite prima mostrano ancora il testo grezzo. `shots/d-l74.png`
- 15: «il modello openai/gpt-6-luna ha dato errore (network_error): ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))». Proposta: «Connessione al modello interrotta. Riprova: rifà solo le unità mancanti.» `shots/d-l15-fallita.png`
- Elemento positivo: ora «Riprova» ed «Elimina» sono in pagina.

## 9. [MEDIO] Pannello Verifica su iPhone

![](shots/i-l68-Verifica_con_LLM.png)
- 6 icone senza testo (scudo con badge 1, orologio, occhio, doppia spunta, annulla, …).
- «Nel testo» riporta **tutto il paragrafo** dell'unità 1.1 invece della frase contestata (sedute *settimanali*): sul telefono occupa tutto lo schermo e l'errore non si trova.
- Titolo dell'unità troncato «1.1 Pazienti in lista d'attes…».
- api.log: `frontend warn [/lezioni/68?panel=verifica&issue=sci_000003] Measure loop restarted more than 5 times` (2 volte): il virtualizzatore della lista misura in loop.

## 10. [MEDIO] Studio su iPhone

![](shots/i-studio68.png)
In alto ci sono 5 controlli solo icona (Modalità zen, Strumenti, Stato, Lettura veloce, Audio) e una fila di pallini arancioni sopra la barra delle unità, che segnano le unità con segnalazioni ma non hanno legenda. Il pulsante ✨ a destra di «Mettimi alla prova · 6» non spiega cosa fa. La barra «12 punti da verificare · Apri Verifica» invece è chiara.

## 11. [MEDIO] Dettagli su iPhone: nomi troncati

![](shots/i-l68-Dettagli.png)
«Registrazione …» e «Radioterapia_2….» sono troncati, mentre a destra restano 100+ px liberi e la colonna delle icone è larga. Anche la stella arancione accanto alla registrazione non è spiegata. «Argomenti» ha l'etichetta a sinistra e il valore a destra, mentre gli altri campi hanno l'etichetta sopra.

## 12. [MEDIO] «N lezioni mancanti»: manca la materia

![](shots/d-lista-mancanti.png)
Il popup elenca «Lun 2/11 09:30–11:30», «11:30–13:30», «16:30–18:30» senza dire di quale materia. Inoltre le lezioni di prova del 2/11 (MATERIA INESISTENTE) non coprono gli slot, che risultano mancanti: è corretto, ma il conteggio confonde.

## 13. Vedi §0 (99% senza messaggio)

## 14. [MINORE] Desktop stretto con il mouse: scroll orizzontale

Con larghezza < 768 px e un puntatore con hover (finestra dell'app ridotta su Mac), le pagine della lezione scorrono in orizzontale di 60 px: la colonna laterale `absolute … w-[76px] [@media(hover:hover)]:block` dentro `ARTICLE` compare anche sotto `md`, mentre il padding `md:[@media(hover:hover)]:px-[76px]` vale solo da `md` in su. Su iPhone vero (hover: none) non succede. `shots/m-l70-scroll-orizz.png`

## 15-21. [MINORI]

15. **Date ISO nei testi**: avviso del duplicato «Questa registrazione è già nella lezione «[2026-09-01] QA PROVA NOTTE» del 2026-09-01» (meglio: «QA prova notte del 1 settembre»), popup del calendario «2026-11-02». `shots/d-dup-1-avviso.png`
16. **Job**: gli eventi mostrano gergo («[2/9] MACPARAKEET TRANSCRIPTION (ASR Timecoded)...», «Stream chiuso»); la pagina si chiama «Job in corso» ma elenca soprattutto job conclusi; su iPhone le schede hanno impaginazioni diverse (nome della lezione accanto al titolo oppure sotto). `shots/d-job-dettaglio.png`, `shots/i-job.png`
17. **Popup Nuova lezione**: l'avviso «demo_lecture.wav è già nell'elenco: l'ho aggiunto una volta sola» resta anche dopo aver cambiato i campi; un file vuoto risulta «1 KB» e viene rifiutato solo dopo Avvia («File vuoto: vuoto.m4a.»), mentre si potrebbe dirlo subito; il campo Materia è troppo stretto («PATOLOGIA GENERA…»); i 3 pulsanti in basso a destra (Solo trascrizione, Revisione, Arricchimento) sono solo icone. `shots/d-nuova-lezione-2-modifica.png`, `shots/d-bad-vuoto.m4a-1.png`
18. **Maiuscole delle materie**: «Pgss», «Qa prova notte»: le sigle andrebbero lasciate maiuscole.
19. **Rumore di rete** a ogni apertura di una lezione senza scaletta: `404 /lessons/{id}/outline` (74, 78, 79) e 409 su enrichment, che finiscono come errori in console. Non riprodotti stanotte: i 38× 422 su `recall/subject?materia=` e i 40× 404 su `/lessons/0` visti nei log del 1/11.
20. **Accessibilità**: due `<main>` annidati nella pagina Recall; nel popup Nuova lezione le icone in basso non hanno testo visibile.
21. **Esporta**: «Includi lo stato di studio» nel menu è rientrato e non mostra lo stato (casella) finché non lo si sceglie. `shots/d-l68-panel-Esporta.png`

## 22. [PROCESSO] Tempi della CI di release

La PR #153 è stata unita alle 22:24 e la release è uscita alle 23:25, dopo un primo giro di test fallito (21:18). La release rifà tutti i test della PR e intanto il push su main ne lancia un secondo giro, in coda sugli stessi runner macOS. Attilio ha approvato di riusare i risultati della PR e non rilanciare al merge: la richiesta è passata al thread «Gestire release e branch RT».

---

## Tempi di caricamento (navigazione fino a rete ferma)

| Pagina | Desktop | iPhone |
|---|---|---|
| Lezioni | 1,09 s | 1,14 s |
| Calendario | 0,66 s | 0,67 s |
| Job | 0,97 s | 1,00 s |
| Impostazioni (sezioni) | 0,61-1,30 s | 0,63-1,26 s |
| Lezione 68 (22 unità) | 1,66 s | 1,72 s |
| Lezione 60 | 1,78 s | 2,08 s |
| Recall 68 | 2,31 s | 2,32 s |
| Studio 68 | — | 1,61 s |

Nessuna pagina sopra 2,4 s. Le 404 su id inesistenti (`/lezioni/999`, `/job/nonesiste`, rotta sconosciuta) mostrano messaggi italiani corretti.

## Copertura

- **Desktop**: 31 rotte, inclusi stati limite (lezione fallita 15, lezione con errore 74, mock 73, fantasmi 77/78, id inesistenti); 10 sezioni delle Impostazioni; tutti i pannelli della 68 (Domande, Studio, Arricchimento, Verifica, Dettagli, Esporta); elenco (per data, materia, docente, ordina, cerca con e senza risultati, lezioni mancanti, selezione multipla); calendario (popup dello slot); job (elenco, dettaglio); popup Nuova lezione: materia nuova (conferma ✓), duplicato (avviso con «Apri la lezione»/«Crea comunque» ✓), mp3 finto (rifiutato ✓), file vuoto (rifiutato ✓), solo appunti .txt; rielaborazione reale su una lezione da 6 s.
- **iPhone**: 14 rotte con tocco; pannelli della 68; Studio; Recall; calendario con tocco sullo slot.
- **Non provato**: Safari vero su iPhone (era Chromium con user agent iOS), Telegram, generazione di arricchimento e infografiche (costo), download reale del PDF, accesso via Tailscale, «Alleggerisci l'audio» (bloccato da #1), annullamento di un job in corso (la lezione di prova finiva in 12 s).

## Dati lasciati sul Pro

- Lezione **79 «QA PROVA NOTTE»** (1/9/2026, audio da 6 s, rielaborata) e materia **QA PROVA NOTTE**: si possono eliminare.
- Lezioni fantasma 75-78 e materie BIOCHIMICA e MATERIA INESISTENTE: non toccate (vedi §1).
- `rt/frontend/node_modules` reinstallato (`npm ci`) e dipendenze dev nel `.venv` per eseguire i test; il checkout `rt/` è tornato su `main`.
