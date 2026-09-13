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
implementare): il testo COMPLETO dell'unità va mostrato una sola volta, con l'affermazione
contestata evidenziata in ROSSO (testo rosso semplice, **NON barrato**: l'utente ha esplicitamente
corretto una mia prima bozza che usava lo strikethrough) esattamente dove appare nel flusso del
testo, e la correzione proposta subito sotto in VERDE — stile "diff" da agente di coding che
propone una modifica. Sotto la critica, una mini legenda: "🔴 rosso = claim attuale · 🟢 verde =
correzione suggerita" (l'utente l'ha chiesta esplicitamente). Struttura dall'alto in basso:
1. Header: `[idx/totale] SCIENCE CRITIC (tipo) - ID: ...` + riga unità.
2. Corpo: testo unità con claim in rosso inline + correzione in verde subito sotto.
3. Critica.
4. Legenda rosso/verde.
5. Barra azioni (invariata).

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
  - Componi il testo: parte PRIMA del claim (stile normale) + claim (stile rosso, `Text(...,
    style="red")`, NON `"strike red"`) + parte DOPO il claim (stile normale), poi su una riga
    separata subito sotto la correzione proposta (`iss.suggested_fix`, se presente — se ASSENTE,
    verifica cosa mostrare: il ramo `is_asr_risk` potrebbe non avere sempre un `suggested_fix`
    significativo, gestiscilo mostrando solo il rosso senza il blocco verde in quel caso, non un
    verde vuoto) in stile verde, con un prefisso visivo tipo "✚ " (vedi il mockup per lo stile
    esatto).
  - Sotto la critica (`iss.reason`), aggiungi la mini legenda SOLO se è stato mostrato un blocco
    verde (correzione presente) — se non c'è correzione da mostrare, la legenda non ha senso e va
    omessa.
  - Mantieni invariati: `📌 Ultima decisione`, `last_status`, la barra azioni finale (con le stesse
    lettere `A/M/E/P/O/B/S/Q` già esistenti — questo task NON tocca i comandi, solo la
    presentazione), e il ramo `is_asr_risk` (RISCHIO ASR) — l'utente ha parlato solo della card
    "Science Critic" nello screenshot, non toccare il ramo ASR-risk a meno che tu non trovi un
    motivo tecnico stringente per farlo (in tal caso segnalalo, non deciderlo in autonomia).
  - Il `Panel`/i colori esistenti (`border_style="magenta"`) restano invariati salvo dove la nuova
    struttura richiede modifiche minime per accomodare i blocchi rosso/verde.

## Test

- Test che verifica che, con un `iss.claim` presente verbatim in `sci_unit.content`, il testo
  renderizzato contenga il claim in stile rosso (verifica sulle `Text.spans`/stili applicati, non
  solo sul contenuto testuale grezzo) e la correzione in stile verde, nell'ordine corretto
  (prima del claim → claim rosso → dopo il claim → correzione verde).
- Test che verifica l'assenza della riga "Timecode" nell'output.
- Test che verifica il fallback quando il claim NON è trovato verbatim nel testo dell'unità
  (nessun crash, comportamento di fallback ragionevole applicato).
- Test che verifica che la legenda compaia SOLO quando è presente una correzione proposta, e sia
  assente altrimenti.
- Test che verifica che il ramo `is_asr_risk` resti visivamente INVARIATO (nessuna regressione
  accidentale lì).
- Adatta i test esistenti su `_build_science_panel`/`IssueReviewApp` che assumevano il vecchio
  formato con "Timecode"/"Contesto Draft" separato.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Non toccare i tasti/azioni disponibili, solo la presentazione
visiva della card. Non toccare il ramo `is_asr_risk`.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. `rt review "<cartella_lezione>"` su una lezione con issue di tipo Science Critic: confronta
   visivamente con `/Users/attilioturco/Desktop/rt_review_card_mockup.py` (stesso layout,
   colori coerenti, legenda presente quando c'è una correzione).
