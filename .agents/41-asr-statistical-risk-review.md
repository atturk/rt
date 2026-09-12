# Task 41 — Rilevamento statistico deterministico del rischio ASR, integrato nella review a card

Dipende dal Task 40 (rimozione di `review_asr`, rename `rt review-science` → `rt review`): deve
essere già fatto e i test devono già passare prima di iniziare questo. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## Contesto e decisione di design (già discussa e approvata dall'utente in chat, non rimetterla
in discussione — implementala così com'è)

Con la fase `review_asr` rimossa e `review_science` rinominata internamente in `review` (Task
40 — modulo `rt/pipeline/review.py`, funzione `run_review`, fase di idempotenza `"review"`,
comando `rt review`), l'unico meccanismo restante di revisione post-rewrite è questa fase
`review`. L'utente vuole aggiungere, DENTRO `review` (non come fase separata), un secondo
meccanismo di rilevamento errori ASR: non
basato su LLM ma **puramente statistico e deterministico**, gratuito, che sfrutta la confidenza
per-parola preservata dal Task 35 (`wordTimestamps` in `trascritto grezzo.json`).

**Logica**: per ogni segmento ASR con un `wordRange` valido su `wordTimestamps`, calcola una
metrica di rischio basata sulle confidenze delle sue parole. Poi, guardando la distribuzione di
questa metrica su TUTTI i segmenti della lezione, individua quelli **significativamente più
degradati della norma di quella specifica lezione** (non una soglia fissa globale — la
calibrazione della confidenza varia troppo tra lezioni per qualità audio/microfono/accento).
Ogni segmento così flaggato genera una `ScienceIssue` di un nuovo tipo `ERR_ASR_ST`, che viene
mostrata all'utente ESATTAMENTE nella stessa interfaccia a card già usata per le issue
scientifiche (stesso comando `rt review`, stesso file `science_issues.json`, stessa navigazione
Indietro/Salta/Esci) — non una schermata separata.

A differenza delle issue scientifiche normali, per `ERR_ASR_ST` **non esiste una correzione
proposta**: non c'è un LLM che ha suggerito un testo alternativo, quindi non ha senso un'azione
"Applica correzione". Le uniche due azioni sensate sono:
- **Accetta**: il testo scritto dal rewrite per quell'unità viene lasciato così com'è (nessuna
  modifica al documento — vedi sotto perché questo va reso un'azione esplicita, non un
  side-effect casuale).
- **Modifica**: l'utente ascolta l'audio del segmento incriminato, legge l'unità intera così
  come l'ha scritta il rewrite, e se si accorge che il rewrite ha inventato/travisato qualcosa
  non fedele all'audio, riscrive lui stesso la parte corretta.

## Passo 1 — Metrica di rischio per segmento e soglia statistica adattiva

Nuova funzione (proponi un posto adatto, es. `rt/core/segments.py` o un nuovo modulo dedicato
`rt/core/asr_risk.py` se preferisci tenerla separata — usa il secondo se `segments.py` ti sembra
già abbastanza carico) che, dato il contenuto di `trascritto grezzo.json` (o direttamente la
`SegmentsData`/lista `Segment` già caricata via `load_segments_json`, verifica quale input è più
comodo per come verrà poi chiamata da `review.py`):

1. Per ciascun segmento con `wordRange` risolvibile su `wordTimestamps`: calcola il **10°
   percentile delle confidenze delle parole nel range** come metrica di rischio del segmento
   (NON la media — `Segment.confidence` esistente dal Task 35 è già una media e va lasciata
   invariata per il suo scopo attuale; questa è una metrica NUOVA e dedicata). Se il range ha
   meno di 3 parole, usa il minimo invece del percentile (un percentile su un campione
   piccolissimo non è stabile). Se non c'è `wordRange`/`wordTimestamps` per un segmento
   (retrocompatibilità con JSON senza questo dato), escludilo dal calcolo — nessun rischio
   calcolabile, non trattarlo come non-a-rischio né come a-rischio, semplicemente ignoralo.
2. Sulla distribuzione di questa metrica su tutti i segmenti della lezione con dato disponibile,
   calcola mediana e MAD (Median Absolute Deviation, `mediana(|x_i - mediana(x)|)`). Flagga un
   segmento come "statisticamente degradato" se la sua metrica è sotto
   `mediana - k * MAD_scaled` dove `MAD_scaled = MAD * 1.4826` (fattore standard per rendere il
   MAD comparabile a una deviazione standard sotto normalità) e `k` è configurabile (default
   ragionevole: `3.0` — uno z-score robusto di 3 è una soglia da outlier vero, non da rumore
   normale).
3. Aggiungi una **soglia assoluta di sicurezza** indipendente dal test statistico: se la metrica
   di un segmento è sotto un valore fisso configurabile (default `0.35`), flaggalo SEMPRE, anche
   se il test mediana+MAD non lo segnala come statisticamente anomalo — serve a coprire il caso
   di una lezione con audio uniformemente scadente, dove anche i pezzi realmente a rischio non
   risultano "anomali" rispetto a una base già bassa di suo.
4. Casi limite da gestire esplicitamente: se ci sono meno di ~10 segmenti con metrica calcolabile
   nella lezione, salta il test statistico relativo (mediana/MAD non sono affidabili su campioni
   così piccoli) e usa solo la soglia assoluta. Se il MAD calcolato è 0 (tante metriche
   identiche), salta il termine statistico e usa solo la soglia assoluta per evitare divisioni
   concettualmente degeneri.
5. Rendi `k` e la soglia assoluta configurabili in `config/general.yaml` (nuova sezione, es.
   `review: {asr_statistical_k: 3.0, asr_statistical_floor: 0.35}` — verifica lo stile già usato
   altrove in `RTConfig` per sezioni opzionali e segui lo stesso pattern), con questi stessi
   valori come default se la sezione non è presente.

## Passo 2 — Raggruppamento per unità e creazione delle issue

Più segmenti flaggati possono ricadere nella stessa unità didattica del draft: raggruppali per
`unit_id` (usa la stessa mappatura segmento→unità già usata in `review.py`/
`issue_review.py`, es. `seg_to_unit`/`unit.source_segment_ids`) e genera **una sola
`ScienceIssue` per unità**, non una per segmento — altrimenti un'unità con 5 segmenti degradati
consecutivi produce 5 issue quasi identiche in coda di revisione. Per l'issue rappresentativa
dell'unità:
- `segment_id`: il segmento con la metrica di rischio più bassa tra quelli flaggati nell'unità
  (serve per l'ascolto audio mirato).
- `claim`: il testo RAW ASR di quel segmento rappresentativo (per farlo vedere all'utente
  accanto al testo riscritto — vedi Passo 3 per l'uso corretto di questo campo, NON va trattato
  come testo del draft).
- `reason`: spiegazione templata che cita il metodo, es. `"Confidenza ASR di questo tratto
  significativamente sotto la norma della lezione (percentile-10 parole: 0.09; soglia lezione:
  0.41) — verifica che l'unità rispecchi fedelmente quanto detto nell'audio."` (se più segmenti
  della stessa unità sono flaggati, menzionalo: "3 segmenti in questa unità risultano degradati,
  il più critico è mostrato qui").
- `suggested_fix`: `None` (nessuna correzione proposta).
- `diplomatic_question`: `None`.
- `severity`: deriva da quanto è estrema l'anomalia (es. `HIGH` se sotto la soglia assoluta,
  `MEDIUM` se flaggato solo dal test statistico relativo) — verifica i valori validi di
  `ScienceSeverity`.
- `status`: `"pending"` come le altre issue.

Aggiungi `ScienceType.ERR_ASR_ST = "ERR_ASR_ST"` in `rt/core/models.py` (accanto a
`ERR_DOCENTE`/`ERR_RECONSTRUCTION`/`SCIENCE_CHECK`).

Integra la chiamata a questo rilevamento dentro `run_review`
(`rt/pipeline/review.py`, ex `run_review_science`/`review_science.py` prima del Task 40, funzione
a riga 182 al momento della stesura): eseguilo PRIMA
o DOPO il giro LLM esistente (l'ordine relativo non è critico, ma deve avvenire sempre — a
differenza del giro LLM non richiede budget/chiamate esterne), unendo le issue statistiche a
`all_science_issues` prima del salvataggio finale con `save_science_issues`. Deve girare sempre
di default (nessun flag necessario per attivarlo — è il comportamento base di `rt review`; il
Task 42 aggiungerà un flag `--asr-llm` che cambia SOLO come le issue ASR vengono raffinate, non
se questo passo statistico gira).

## Passo 3 — TUI: card dedicata, e correzione di un bug reale nell'applicazione delle decisioni

`rt/pipeline/issue_review.py`, funzione `_build_science_panel` (riga 307): quando
`iss.type == ScienceType.ERR_ASR_ST` (o il futuro `ERR_ASR_LLM` del Task 42), differenzia il
rendering:
- Intestazione diversa da "SCIENCE CRITIC", es. `"🎙️ RISCHIO ASR (statistico)"` (per
  `ERR_ASR_LLM`, quando esisterà, userai un'etichetta analoga tipo "🎙️ RISCHIO ASR (validato
  LLM)").
- Etichetta del campo `iss.claim` diversa da "⚠️ Affermazione" (che implica un claim scientifico)
  — usa qualcosa come `"🎙️ Segmento raw sospetto:"` per chiarire che quel testo è la
  trascrizione grezza, non un'affermazione del draft.
- Il blocco esistente "📖 Contesto Draft (Unità intera)" (righe 333-338) resta invariato — è
  esattamente quello che serve per mostrare l'unità completa.
- `suggested_fix`/`diplomatic_question` restano `None` per questo tipo, quindi le righe
  condizionali che li stampano (righe 329-332) già non si attivano da sole — nessuna modifica
  necessaria lì.
- La riga di azioni (riga 346) deve OMETTERE "A=Applica correzione" per questo tipo, mostrando
  solo `"[M=Accetta / E=Modifica / P=Play audio / O=Riavvia audio / B=Indietro / S=Salta /
  Q=Esci]"`.

Nel loop di gestione tasti (dentro `run_interactive_review`, ramo `else: # science`, righe
715-880 circa): per `ERR_ASR_ST`/`ERR_ASR_LLM`, il tasto "A"/"Applica" **non deve essere
accettato come scelta valida** — se premuto, trattalo come input non riconosciuto (nessuna
azione, richiedi un altro tasto), non lasciarlo cadere nel branch `choice in ("a", "accetta",
"applica", "")` esistente (righe 736-747), che per questo tipo applicherebbe una correzione
vuota/inesistente. Il branch "M=Mantieni" (righe 748-758, già presente) è semanticamente
identico ad "Accetta" per questo tipo — riusalo così com'è, ma nel testo mostrato all'utente per
questo tipo chiamalo "Accetta" invece di "Mantieni" (coerente col punto sopra sulla riga di
azioni).

**Bug reale da correggere, trovato leggendo `rt/pipeline/ledger.py::apply_decisions_to_draft`
(righe 204-258)**: per le issue scientifiche normali, l'applicazione di una decisione cerca
`s_iss.claim` COME SOTTOSTRINGA LETTERALE dentro il contenuto dell'unità (righe 232-238,
`if claim_clean in content: target = claim_clean`) e poi lo sostituisce col testo risolto (riga
252). Per `ERR_ASR_ST`, `iss.claim` è la trascrizione RAW ASR — quasi certamente NON compare
letteralmente nel testo riscritto dal rewrite (il rewrite parafrasa/normalizza, e nel caso
peggiore l'intera frase è fabbricata ex novo, quindi non c'è alcuna sovrapposizione testuale con
la trascrizione grezza). Con la logica attuale: `target` resta `None` (riga 234), il blocco di
sostituzione (righe 240-252) non scatta MAI per questo tipo. Per la decisione "accepted" questo
è per fortuna innocuo (nessuna modifica = comportamento corretto per "Accetta"). Ma per la
decisione "edited" — quando l'utente ha davvero scritto una correzione — **la correzione
verrebbe silenziosamente scartata e MAI scritta nel documento finale**, il tipo esatto di bug
silenzioso che questa intera funzionalità dovrebbe prevenire.

**Fix obbligatorio**: aggiungi in `apply_decisions_to_draft` un branch esplicito, PRIMA della
logica generica di ricerca-sostituzione (righe 231-252), per `s_iss.type in (ScienceType.ERR_ASR_ST,
ScienceType.ERR_ASR_LLM)` (il secondo valore esisterà solo dopo il Task 42, per ora gestisci solo
`ERR_ASR_ST` ma struttura il codice in modo che aggiungere l'altro valore dopo sia banale):
- Decisione `"accepted"`: non fare nulla al contenuto (no-op esplicito, non lasciato al caso).
- Decisione `"edited"`: sostituisci **l'intero contenuto dell'unità** (`content = resolved`,
  non una sostituzione di sottostringa) con il testo che l'utente ha scritto nell'editor — stesso
  pattern già usato altrove nel file per il caso "termine non trovato letteralmente nel draft"
  della revisione ASR (before its removal in Task 40, look at git history/`issue_review.py`'s
  existing ASR "modifica" branch for the exact wording/UX pattern it used, se non l'hai già
  presente: quando il termine non era trovabile, il messaggio diceva "Modifica liberamente il
  testo dell'intera unità qui sotto: sostituirà l'intero paragrafo nel documento finale" — è lo
  stesso concetto).

Coerentemente, in `run_interactive_review`, il ramo "E=Modifica" per `ERR_ASR_ST` (dentro
`_configure_llm_provider_section`... no, dentro il loop `elif choice in ("e", "modifica"):` a
riga 759) deve **seminare l'editor con il contenuto ATTUALE DELL'INTERA UNITÀ**
(`sci_unit.content`), non con `iss.claim` (che oggi semina l'editor per le issue scientifiche
normali, riga 763, `f"{iss.claim}\n"` — corretto per quelle, dato che lì claim è già un
frammento del draft, ma sbagliato per `ERR_ASR_ST` dove claim è testo raw ASR) — altrimenti
l'utente si troverebbe a "correggere" la trascrizione grezza invece del testo effettivo scritto
dal rewrite, che è quello che deve effettivamente modificare. Aggiungi un messaggio di intestazione
nell'editor per questo tipo che chiarisce: "# Questa è l'intera unità come riscritta. Modificala
liberamente per farla combaciare con l'audio: sostituirà l'intero contenuto dell'unità.\n\n".

## Passo 4 — Versione della fase e ricalcolo su lezioni già processate

Aggiorna `PHASE_VERSIONS["review"]` in `rt/core/idempotency.py` (rinominata dal Task 40, es. da
`"review_v1.0"` a `"review_v1.1"`) — il comportamento e lo schema di output della fase cambiano
(nuovo tipo di issue), quindi una lezione già passata da `review` prima di questo task deve
essere considerata da rieseguire per beneficiare del nuovo rilevamento statistico. Verifica che il meccanismo di fingerprint/versioning esistente
tratti correttamente questo bump (dovrebbe già funzionare per come è strutturato il resto del
file, ma verificalo con un test dedicato).

## Test

- Test unitari sulla funzione di rilevamento statistico: dataset sintetico di segmenti con
  confidenze note, verifica che (a) un segmento con un singolo outlier estremo venga flaggato,
  (b) una lezione con qualità uniformemente bassa non flaggi tutto SOLO per la soglia assoluta se
  sotto di essa, ma non flaggi nulla di più del previsto se sopra la soglia assoluta e non
  statisticamente anomala, (c) con meno di 10 segmenti il test statistico relativo venga
  disattivato e resti solo la soglia assoluta, (d) un segmento senza `wordTimestamps` non generi
  eccezioni e sia semplicemente escluso.
- Test che verifica il raggruppamento per unità: 3 segmenti flaggati nella stessa unità
  producono 1 sola `ScienceIssue`, non 3.
- Test che verifica che `run_review` includa le issue `ERR_ASR_ST` insieme a quelle LLM nel
  `science_issues.json` finale.
- Test sul fix del bug in `apply_decisions_to_draft`: una `ScienceIssue` di tipo `ERR_ASR_ST`
  con decisione "edited" deve risultare nel contenuto FINALE dell'unità sostituito per intero
  col testo risolto, anche quando `iss.claim` (testo raw) non compare affatto nel contenuto
  originale dell'unità — verifica esplicitamente questo caso, è il cuore del bug fix. Un test
  analogo per "accepted" deve verificare che il contenuto dell'unità resti ESATTAMENTE
  invariato.
- Test sulla card TUI: verifica che per `ERR_ASR_ST` il testo dell'azione non includa "Applica
  correzione", e che premere "a" non produca alcuna decisione registrata (resta in attesa di un
  tasto valido).
- Test sul seeding dell'editor: verifica che per `ERR_ASR_ST` l'editor venga aperto col contenuto
  dell'unità, non con `iss.claim`.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non introdurre alcuna chiamata LLM in questo task: il rilevamento deve essere puramente
matematico/deterministico, a costo zero. Il Task 42 aggiungerà il percorso con LLM come opzione
esplicita separata.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale se hai una lezione reale disponibile nell'ambiente Antigravity (anche con
   `--mock` per l'ASR ma servono `wordTimestamps` realistici con almeno un segmento
   volutamente molto degradato per verificare il flagging end-to-end): esegui `rt review
   <lezione>`, verifica che appaia una card `ERR_ASR_ST` con le sole azioni Accetta/Modifica,
   che "Accetta" non tocchi il documento finale, e che "Modifica" con un testo nuovo lo applichi
   correttamente all'unità nel documento finale dopo `rt build`.
