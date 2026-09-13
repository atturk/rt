# Task 74 — Redesign della card di review scientifica: claim in rosso/correzione in verde inline, niente più timecode

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

L'utente trova la card attuale di `_build_science_panel` (`rt/pipeline/issue_review.py`, righe
264-319) troppo affollata: mostra separatamente una riga "⏱ Timecode (stima)" (inutile: è sempre
l'inizio dell'unità, non aiuta a localizzare nulla), una riga "⚠️ Affermazione" col claim isolato
dal contesto, e più sotto un blocco "📖 Contesto Draft (Unità intera)" col testo completo grezzo —
tre pezzi di informazione slegati che il lettore deve ricomporre mentalmente.

**Design approvato dall'utente**, dopo un'anteprima costruita con `rich` e confermata (vedi
`/Users/attilioturco/Desktop/rt_review_card_mockup.py`, lascialo lì, è solo un riferimento visivo,
non fa parte del codice di produzione — leggilo per il pattern esatto di colori/struttura prima di
implementare, è stato aggiornato più volte con le correzioni dell'utente, usa la versione finale
già salvata su disco): il testo COMPLETO dell'unità va mostrato una sola volta, con l'affermazione
contestata evidenziata in ROSSO (testo rosso semplice, **NON barrato**) esattamente dove appare nel
flusso del testo, preceduta inline da un "- " (stile diff, come una riga rimossa), e la correzione
proposta subito sotto in VERDE preceduta da "+ " — stile "diff" da agente di coding che propone una
modifica. Sotto la critica, una mini legenda con SOLO le emoji, senza scrivere il nome del colore:
"🔴 = claim attuale · 🟢 = correzione suggerita". Struttura dall'alto in basso:
1. Header: `[idx/totale] SCIENCE CRITIC (tipo) - ID: ...` + riga unità.
2. Corpo: testo unità con "- " + claim in rosso inline, poi su riga propria "+ " + correzione in
   verde.
3. Critica.
4. Legenda (solo emoji 🔴/🟢).
5. Barra azioni — **cambiano le lettere**, vedi sezione dedicata sotto.

## Ridenominazione tasti (decisa con l'utente, si applica a ENTRAMBI i rami della card)

L'utente ha chiesto di rinominare i tasti per uniformità, e ha confermato esplicitamente che il
nuovo schema si applica SIA alla card Science Critic SIA alla card RISCHIO ASR (non solo a quella
nello screenshot) — altrimenti la stessa lettera farebbe cose diverse a seconda del tipo di issue
in revisione, generando confusione in una sessione mista. Nuovo schema:

| Lettera | Significato          | Azione (branch Science Critic)                          | Azione (branch RISCHIO ASR)                        |
|---------|-----------------------|-----------------------------------------------------------|------------------------------------------------------|
| `A`     | Accetta               | Applica la correzione proposta (oggi `action_approve_or_accept`, ramo non-ASR) | Accetta il testo dell'unità così com'è (oggi `action_keep_or_accept_unit`, ramo ASR) |
| `R`     | Rifiuta               | Mantieni il claim originale, scarta la correzione (oggi `action_keep_or_accept_unit`, ramo non-ASR) | Nessun significato distinto oggi (era già un no-op per ASR) — mantieni no-op, ma verifica che non sia fuorviante se mostrato nella barra azioni di quel ramo: se non ha senso lì, non mostrarlo nell'action bar del ramo ASR |
| `M`     | Modifica              | Apri l'editor esterno per riscrivere liberamente (oggi `action_edit`, invariato nella logica) | Stesso identico comportamento, solo la lettera cambia da `E` a `M` |
| `I`     | Indietro              | Torna all'issue precedente (oggi `action_back`, bindato su `b,left,up,k`) | Identico, stesso handler condiviso |
| `S`     | Salta                 | Invariato (`action_skip`)                                  | Invariato                                             |
| `Q`     | Esci                  | Invariato                                                   | Invariato                                             |
| `P`/`O` | Play/Riavvia audio    | **NON toccare in questo task** — verranno ridisegnati da un task futuro (companion audio player), lascia il comportamento e le lettere attuali invariati per ora | Idem |

Nota bene: oggi `action_approve_or_accept` per il ramo ASR-risk mostra un messaggio d'errore
("Scelta 'A' non valida...") invece di fare qualcosa — con il nuovo schema quel messaggio
d'errore va RIMOSSO, perché "A" ora ha un significato reale anche per ASR-risk (accetta il testo
dell'unità, quello che oggi fa "M" per quel ramo). Riorganizza i binding/i metodi `action_*` in
modo che ogni lettera chiami un unico handler che internamente branch-a su `is_asr_risk` per fare
la cosa giusta (segui lo schema già esistente di `action_keep_or_accept_unit`/
`action_approve_or_accept`, che già branch-ano così — semplicemente riassegna quale lettera
chiama quale handler, secondo la tabella sopra), invece di introdurre metodi duplicati.

## Modifica

- Riscrivi `_build_science_panel` (o estrai una nuova funzione dedicata se risulta più pulito,
  mantenendo la firma chiamante compatibile con `IssueReviewApp._render_panel`, riga ~418-437) per
  il ramo NON-`is_asr_risk` (il vero "Science Critic", quello nello screenshot dell'utente):
  - Rimuovi del tutto la riga `⏱ Timecode (stima)`.
  - Trova `iss.claim` dentro `sci_unit.content` (quando `sci_unit` è disponibile — verifica che
    lo sia sempre in questo ramo, leggendo come viene popolato nel chiamante) con una ricerca
    diretta della sottostringa (`content.find(claim)`), tenendo conto di `fix_mojibake` già
    applicato ad entrambi i lati prima del confronto. Se il claim NON si trova verbatim (possibile
    con testo generato da LLM che riformula leggermente): fai un fallback ragionevole — es. mostra
    comunque il testo dell'unità per intero senza evidenziazione, e il claim originale a parte
    subito sotto (come oggi), invece di far fallire la card o mostrare un'evidenziazione sbagliata.
    Documenta la scelta nel riepilogo finale.
  - Componi il testo: parte PRIMA del claim (stile normale) + `"- "` (stile rosso, grassetto) +
    claim (stile rosso, `Text(..., style="red")`, NON `"strike red"`) + parte DOPO il claim (stile
    normale) — il claim resta INLINE nel flusso del paragrafo, il `"- "` è solo un prefisso subito
    prima del testo rosso, non va a capo. Poi, SEMPRE su una riga separata subito sotto, se
    `iss.suggested_fix` è presente: `"+ "` (stile verde, grassetto) + la correzione proposta
    (stile verde) — se `iss.suggested_fix` è ASSENTE (può capitare: verifica cosa mostrare in quel
    caso), ometti del tutto il blocco verde, non mostrare un "+ " vuoto. Guarda esattamente
    `/Users/attilioturco/Desktop/rt_review_card_mockup.py` per il pattern preciso (i prefissi
    `"- "`/`"+ "`, non simboli diversi come "✚").
  - Sotto la critica (`iss.reason`), aggiungi la mini legenda SOLO se è stato mostrato un blocco
    verde (correzione presente) — se non c'è correzione da mostrare, la legenda non ha senso e va
    omessa. La legenda usa SOLO le emoji, senza scrivere il nome del colore: `"🔴 = claim attuale
    · 🟢 = correzione suggerita"` (non "🔴 rosso = ...").
  - Mantieni invariati: `📌 Ultima decisione`, `last_status`. La barra azioni finale e le lettere
    associate CAMBIANO secondo la tabella nella sezione "Ridenominazione tasti" sopra — questo
    task tocca sia il layout visivo sia le lettere/i binding, per entrambi i rami della card
    (Science Critic e RISCHIO ASR), non solo il layout del ramo Science Critic.
  - Il `Panel`/i colori esistenti (`border_style="magenta"`) restano invariati salvo dove la nuova
    struttura richiede modifiche minime per accomodare i blocchi rosso/verde. Il layout a
    diff rosso/verde si applica SOLO al ramo Science Critic (quello con un `suggested_fix` da
    proporre) — il ramo RISCHIO ASR mantiene il proprio layout visivo attuale invariato, riceve
    SOLO il cambio di lettere/binding descritto sopra, non il redesign grafico.

## Test

- Test che verifica che, con un `iss.claim` presente verbatim in `sci_unit.content`, il testo
  renderizzato contenga `"- "` + claim in stile rosso (verifica sulle `Text.spans`/stili
  applicati, non solo sul contenuto testuale grezzo) e `"+ "` + correzione in stile verde su riga
  propria, nell'ordine corretto (prima del claim → "- "+claim rosso → dopo il claim → "+ "+
  correzione verde).
- Test che verifica l'assenza della riga "Timecode" nell'output (ramo Science Critic).
- Test che verifica il fallback quando il claim NON è trovato verbatim nel testo dell'unità
  (nessun crash, comportamento di fallback ragionevole applicato).
- Test che verifica che la legenda compaia SOLO quando è presente una correzione proposta, e sia
  assente altrimenti, e che contenga SOLO le emoji (nessuna stringa "rosso"/"verde" nel testo).
- Test che verifica che il layout VISIVO del ramo `is_asr_risk` resti invariato (nessun blocco
  rosso/verde/legenda lì, solo il cambio di lettere).
- Test che verifica la nuova mappa di lettere per ENTRAMBI i rami (tabella sopra): `A` accetta
  (testo unità per ASR, correzione per Science), `R` rifiuta/mantieni originale (Science) o no-op
  per ASR, `M` apre l'editor per ENTRAMBI i rami, `I` torna indietro per entrambi, `S`/`Q`
  invariati. Verifica che il vecchio messaggio d'errore "Scelta 'A' non valida" per ASR-risk sia
  sparito (A ora fa qualcosa di reale anche lì).
- Adatta i test esistenti su `_build_science_panel`/`IssueReviewApp` che assumevano il vecchio
  formato con "Timecode"/"Contesto Draft" separato o le vecchie lettere (`e`/`b` invece di
  `m`/`i`).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Il redesign VISIVO (rosso/verde/legenda) riguarda SOLO il ramo
Science Critic; la ridenominazione di TASTI/lettere riguarda invece ENTRAMBI i rami. Non toccare
`P`/`O` (play/riavvia audio): restano com'è, saranno oggetto di un task futuro dedicato al
companion audio player.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. `rt review "<cartella_lezione>"` su una lezione con issue di tipo Science Critic: confronta
   visivamente con `/Users/attilioturco/Desktop/rt_review_card_mockup.py` (stesso layout,
   colori coerenti, legenda presente quando c'è una correzione, prefissi "- "/"+ ").
3. `rt review "<cartella_lezione>"` su una lezione con issue di tipo ASR-risk: verifica che il
   layout visivo sia identico a prima, ma che i tasti A/M/I/S/Q rispondano secondo la nuova
   mappatura (A=accetta, M=modifica, I=indietro).
