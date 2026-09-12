# Task 38 — `rt config`: schermata a blocchi navigabili per fase + conferma/modifica finale

Dipende dal Task 36 (bug fix puntuali nello stesso file) e dal Task 37 (batch API key): fai
prima quelli, poi questo, per evitare conflitti di merge sullo stesso file
(`rt/pipeline/configure.py`) e per isolare i commit per causa. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano
preliminare.

## Contesto

Richiesta esplicita dell'utente dopo un giro di test reale: la configurazione dei modelli per
fase in `_configure_llm_provider_section` (`rt/pipeline/configure.py`, righe 640-757) oggi
presenta un `questionary.select` sequenziale, una domanda alla volta, per ciascun gruppo di job
(`"Modello per 'outline':"`, poi appena finita `"Modello per 'rewrite':"`, ecc. — i gruppi sono
già definiti in `_JOB_GROUPS`, riga 550-557: `outline`, `rewrite`, `review_asr`,
`review_science`, un gruppo unico per i 5 job `recall_*`, un gruppo unico per i 2 job
`image_*`). Ogni domanda che richiede un NUOVO profilo (`➕ Configura un nuovo modello per
questa fase`) rilancia l'intero sotto-flusso `_create_new_model_profile` (provider → base URL →
chiavi → fetch modelli → selezione modello → conferma → pricing opzionale → nome profilo),
allungando molto il tempo totale quando fasi diverse richiedono provider diversi. Una volta
finite tutte le fasi, il wizard scrive subito la configurazione e stampa un riepilogo statico
(`run_config_wizard`, righe 1137-1159) — non c'è modo di tornare indietro su una fase già
configurata senza uscire e rilanciare `rt config` da capo (che poi permette di modificare i
singoli profili via `rt config --models`, ma non di rivedere l'ASSEGNAZIONE fase→profilo appena
fatta nello stesso passaggio).

L'utente chiede esplicitamente uno stile "come science-review": blocchi/card che si possono
scorrere a destra e sinistra, con un'intestazione che mostra quali fasi sono già configurate
(confermate), navigazione libera avanti/indietro tra le domande, e — solo alla fine — un'azione
esplicita "conferma" che scrive la configurazione; se non si conferma si può sempre tornare
indietro e modificare, e anche dopo aver confermato si può scegliere "modifica" per riaprire la
configurazione.

**Il pattern esiste già nel codebase** ed è esattamente quello usato dalla vera "science
review": `rt/pipeline/issue_review.py::run_interactive_review` (righe 351-900 circa) implementa
già una UI a card testuali con:
- `rich.Live(console=console, auto_refresh=False, transient=False, vertical_overflow="visible")`
  (riga 497) per un pannello che si ridisegna in place;
- `rt.core.keyboard.raw_mode()` + `read_single_key(already_raw=is_raw)` (righe 497, 534, 733)
  per input a tasto singolo senza Invio;
- un pannello `rich.Panel` con titolo che mostra la posizione corrente (`_build_asr_panel`,
  riga 266, titolo `f"ASR Review [{idx + 1}/{total_count}]"` — vedi anche `_build_science_panel`,
  riga 307, stesso schema);
- navigazione "indietro" già implementata: `elif choice in ("b", "indietro", "back", "left"):
  ... idx -= 1 ...` (righe 675-685 e 878-888), che ridisegna il pannello dell'issue precedente.

Riusa ESATTAMENTE questo pattern (stessa libreria, stesso stile di pannello, stessa gestione
tasti) per la nuova schermata a blocchi di `rt config`, invece di inventare una UI diversa — è
lo stile "science-review" a cui l'utente fa riferimento.

L'utente chiede anche di rendere la sezione "Pricing Custom" (`_configure_pricing_section`,
righe 1028-1043) una semplice domanda invece di un'intestazione a riquadro separata: oggi
stampa un box a 3 righe (`"-"*60`, `"💰 4. Configurazione Pricing Custom (Opzionale)"`, `"-"*60`)
prima della domanda `questionary.confirm`. Nota che questa sezione viene invocata DENTRO il
flusso di creazione di un nuovo profilo modello (chiamata da riga ~439 dentro
`_create_new_model_profile`), non come una fase separata a sé — quindi il box "4." è già
concettualmente fuori posto (appare intercalato dentro la sezione "1.", non dopo la "3."); va
rimosso e sostituito da una domanda semplice inline, senza intestazione numerata.

## Modifiche

### 1. Nuova schermata a blocchi per `_configure_llm_provider_section`

Sostituisci il loop `for group_label, group_jobs in grouped_jobs:` (righe 683-751, che oggi fa
un `questionary.select` sequenziale per gruppo) con una UI a card navigabile:

- Un pannello per fase/gruppo (stesso `grouped_jobs` già calcolato a monte, righe 666-677 — non
  toccare quella logica di raggruppamento), che mostra: il nome del gruppo, il profilo
  attualmente assegnato (o "non configurato"), e le scelte disponibili (profili esistenti +
  "nuovo profilo" + "lascia vuoto") navigabili con SU/GIÙ o con lettere rapide, sullo stile già
  usato altrove nel file per `questionary.select` — non serve reinventare la selezione della
  singola scelta con `read_single_key`, quella può restare un `questionary.select` invocato
  DENTRO il rendering del blocco corrente; il cambiamento chiave è che l'utente può muoversi
  LIBERAMENTE tra i blocchi (fasi) con frecce SINISTRA/DESTRA (`read_single_key` già supporta
  `"LEFT"`/`"RIGHT"`, vedi `rt/core/keyboard.py:60-63`) prima di scegliere/confermare, invece di
  essere bloccato in avanti dopo ogni risposta.
- Un'intestazione (sopra il pannello corrente, o nel titolo del `Panel` stesso, stile
  `f"Configurazione modelli [{idx + 1}/{total_gruppi}]"` come fa già `_build_asr_panel`) che
  mostra lo stato di ciascuna fase: quali sono già assegnate/confermate (es. con un simbolo ✅)
  e quali no, così l'utente vede a colpo d'occhio l'avanzamento senza dover scorrere tutti i
  blocchi.
- Ogni blocco, quando l'utente sceglie "➕ Configura un nuovo modello per questa fase", invoca
  `_create_new_model_profile` esattamente come oggi (nessuna modifica alla logica interna di
  quella funzione in questo task, a parte il punto 3 sotto) — ferma temporaneamente il rendering
  `Live` (come fa già `live.stop()`/`live.start()` in `issue_review.py` riga 575-577 per aprire
  l'editor esterno) per lasciare spazio ai prompt `questionary` di quel sotto-flusso, poi
  riprende il rendering a blocchi.
- Naviga avanti/indietro tra i blocchi con LEFT/RIGHT (o frecce equivalenti); l'assegnazione di
  un blocco già visitato resta in memoria (un dict locale `job_assignments` come oggi, righe
  679/748-751) finché l'utente non arriva alla schermata finale di conferma (punto 2).

### 2. Schermata finale "Conferma" / "Modifica"

Dopo che l'utente ha scorso tutti i blocchi (o in qualunque momento sceglie un'azione esplicita
tipo "vai al riepilogo" da un blocco), mostra un riepilogo (stile simile all'attuale stampa in
`run_config_wizard` righe 1139-1145, ma come schermata interattiva, non solo testo statico) con
due azioni: **Conferma** (scrive la configurazione su disco come fa oggi
`_save_model_profiles`/`_atomic_write_text`, righe 753-756, poi procede a Telegram/STT come oggi)
e **Modifica** (torna alla navigazione a blocchi, riaprendo lo stato corrente per continuare a
cambiare le assegnazioni). Solo "Conferma" deve effettivamente persistere su disco — finché
l'utente non conferma, deve poter tornare indietro liberamente su qualunque blocco già visitato
senza che nulla sia stato scritto in modo definitivo (le scritture di credenziali/profili
avvengono già dentro `_create_new_model_profile`/`_save_model_profiles` quando si crea un NUOVO
profilo — è un side-effect preesistente e accettabile, dato che un profilo creato resta
comunque disponibile e riusabile anche se poi l'utente cambia l'assegnazione fase→profilo prima
di confermare; quello che questo task deve garantire è che l'ASSEGNAZIONE fase→profilo finale
scritta nei file YAML dei job — `_apply_profile_to_job`, riga 750 — avvenga solo dopo
"Conferma", non ad ogni blocco).

Aggiungi anche, dopo il riepilogo finale stampato da `run_config_wizard` (dopo Telegram e STT,
righe 1137-1159), un'analoga possibilità di scegliere "Modifica" per riaprire la sezione
modelli e cambiare qualcosa prima di uscire definitivamente dal wizard — non serve estendere
questo a Telegram/STT in questo task (fuori scope), ma la sezione modelli sì, dato che è quella
esplicitamente citata dall'utente.

### 3. Pricing come domanda semplice, non sezione a riquadro

In `_configure_pricing_section` (righe 1028-1043), rimuovi le 3 righe del box
(`"\n" + "-"*60`, `"💰 4. Configurazione Pricing Custom (Opzionale)"`, `"-"*60`) e lascia solo la
domanda `questionary.confirm` (righe 1036-1039), eventualmente con un testo leggermente più
autoesplicativo dato che perde il contesto del titolo di sezione, es.: `"Vuoi configurare un
listino prezzi custom per questo modello? (opzionale, RT ha già stime interne)"`.

Rinumera o rimuovi la numerazione delle altre 3 intestazioni (`"🤖 1. ..."` riga 646, `"✈️ 2.
..."` riga 766, `"🎙️ 3. ..."` riga 976) se la rimozione della sezione "4." la rende incoerente
(dato che oggi "4." appare cronologicamente PRIMA di "2." e "3." a runtime, essendo invocata
dentro "1.") — valuta se togliere del tutto la numerazione da tutte e 3 le intestazioni residue
(mantenendo solo le emoji e i titoli) per evitare di promettere un ordine che non rispecchia
l'esecuzione reale.

### 4. Documenta la navigazione nell'intro del wizard

Nel testo introduttivo di `_configure_llm_provider_section` (righe 648-651, stampato prima di
entrare nei blocchi) aggiungi una riga che spiega i tasti di navigazione disponibili (frecce
sinistra/destra per muoversi tra le fasi, tasto per confermare, tasto per tornare al riepilogo),
così l'utente non deve scoprirlo per tentativi.

## Test

Data la natura interattiva (rendering `rich.Live` + `read_single_key`), segui lo stesso
approccio di test già usato per `run_interactive_review` in `issue_review.py` — cerca nei test
esistenti (`tests/test_issue_review.py` o simile, verifica il nome esatto) come vengono simulate
sequenze di tasti (probabilmente mockando `read_single_key` con `side_effect` su una lista di
tasti predefinita, o iniettando input non-tty) e replica lo stesso approccio per i nuovi test su
questa schermata:
- Naviga avanti (RIGHT) attraverso tutti i blocchi senza scegliere nulla, poi indietro (LEFT)
  fino al primo: verifica che le eventuali assegnazioni già fatte restino in memoria e vengano
  mostrate correttamente al ritorno.
- Verifica che nessuna scrittura su `general.yaml`/file job avvenga finché non si sceglie
  esplicitamente "Conferma".
- Verifica che "Modifica" dopo "Conferma" permetta di cambiare un'assegnazione e che una nuova
  "Conferma" sovrascriva correttamente lo stato precedente.
- Test sulla rimozione del box "Pricing Custom": verifica che l'output non contenga più le
  righe del riquadro (cattura stdout/`capsys`).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa (inclusi i test
esistenti per `_configure_llm_provider_section`/`run_config_wizard`, che probabilmente vanno
adattati al nuovo flusso — verificali uno per uno, non limitarti a farli "passare" aggirando
l'asserzione).

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare `issue_review.py`: è solo un riferimento di stile da riusare, non va modificato in
questo task.

Non toccare la logica interna di `_create_new_model_profile` oltre a quanto necessario per
integrarla nel rendering a blocchi (es. `live.stop()`/`live.start()` attorno alla sua
invocazione) — i Task 36 e 37 la modificano già per altri motivi, verifica di partire dal loro
risultato per evitare conflitti.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto: lancia `rt config`, verifica a schermo che (a) il campo modello
   parta vuoto (Task 36), (b) sia possibile navigare avanti e indietro tra almeno 3 fasi con le
   frecce prima di confermare, (c) i dati non vengano scritti finché non si sceglie "Conferma",
   (d) dopo "Conferma" sia possibile scegliere "Modifica" e cambiare un'assegnazione.
