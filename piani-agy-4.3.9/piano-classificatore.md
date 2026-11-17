# Piano: collocazione delle pagine dei materiali (classificatore)

Lezione di prova: PATOLOGIA GENERALE 2 del 2026-11-12 (40 foto di slide, fonte "Contesto", estrai=immagini).
Codice: `rt/pipeline/material_mapping.py` (`classify_material_page`, `assign_material_pages`).

## Come funziona oggi
1. Candidate TF-IDF (`find_candidate_subunits_for_page`): fino a 5 sottounità con punteggio >= metà del migliore.
2. Jev (`image_unit_judge`): una domanda noul per candidata ("la pagina spiega un argomento trattato in modo
   specifico nella sottounità") + `didactic_content`. Contesto: testo della pagina (OCR del modello visivo)
   e 2 finestre di 600 caratteri della trascrizione per candidata.
3. Soglia unica 0,7: sottounità se la migliore >= 0,7; altrimenti "non collocata" sotto la macro della
   migliore candidata, qualunque sia il punteggio (anche 0,04).

## Misura sulla lezione di prova (40 pagine)
- 26 collocate, tutte plausibili. 14 "non collocate":
  - 8 pertinenti mancate (punteggio 0,46-0,63): Area a rischio (3.2), Correnti di lesione, Conta la durata,
    Dalla carenza di O2, Danno mitocondriale, ECG tratto ST e onda T, Potenziale del potassio, Alterazioni ST (3.1).
    La candidata TF-IDF giusta era la prima in 7 casi su 8: sbaglia la decisione, non la ricerca.
  - 5 slide di un'altra lezione (misurazione della pressione, punteggi 0,03-0,44) mostrate come "non collocate"
    sotto le sezioni 1 e 3.
  - 1 indice (didactic_content 0,78, passato con la soglia 0,7).
- Risultato giusto oggi: 26/40. Con una fascia 0,45-0,7 (simulata sulle probabilità salvate): 39/40
  ma vedi la verifica sotto: su altre lezioni la fascia sbaglia molto. Claude verifica
  su altre lezioni dopo l'implementazione.

## Verifica su altre 4 lezioni del Pro (punteggi salvati)
- Lezione 20 (rene) e 52 (alberi): molte pagine pertinenti non collocate tra 0,56 e 0,69, quasi sempre con
  una sola candidata giusta: la fascia 0,45-0,7 le recupererebbe.
- Lezione 59 (Data Mining): il PDF "Classificatori avanzati" (KNN, Naive Bayes, ensemble) non è trattato
  nella lezione, ma prende 0,45-0,67 su sottounità sbagliate (es. Gini), e 4 pagine sono già collocate
  male sopra 0,7. Con la fascia 0,45-0,7 ne entrerebbero altre decine nel posto sbagliato.
- Conclusione: i punteggi noul di Jev si sovrappongono (pertinente non riconosciuta e "stessa materia,
  argomento diverso" stanno entrambe tra 0,45 e 0,7). Abbassare la soglia NON è sicuro: la fascia resta
  fuori finché Claude non prova sul Pro domande diverse (sotto).

## Modifiche (agy)
1. In `classify_material_page`, costanti in cima al file:
   - `didactic_content` < 0,85 → introduttiva/decorativa, come oggi per < soglia.
   - migliore sottounità < 0,2 → "fuori tema": né sotto una sezione né non collocata;
     va in `state["off_topic"]` (stessi campi di `unplaced`) e l'immagine non entra nella lezione.
   - il resto come oggi (soglia della configurazione, 0,7).
2. Pagine doppie (due foto della stessa slide): pagine con lo stesso titolo (prima riga) e testo quasi uguale
   (Jaccard dei token >= 0,8) prendono la stessa collocazione, quella della copia con la probabilità più alta.
   Nella lezione di prova "Dalla carenza di O2" ha avuto 0,70 e 0,63 in due foto: una collocata e una no.
3. Una riga di log per pagina in api.log: `📎 Materiale <file> p.<n>: candidate [...] probabilità {...} → <esito>`
   (esito: sottounità X, macro Y, non collocata, fuori tema, introduttiva).
4. Il testo delle pagine non collocate va salvato in `material_attachments.json` anche nelle lezioni
   (oggi c'è solo per le collocate), per poterle analizzare.
5. Test in `tests/test_material_mapping.py` per ogni caso.

Non toccare: candidate TF-IDF, prompt di Jev, cache `material_decisions.json` (le probabilità salvate si riusano:
ricostruire la lezione applica le nuove regole senza nuove chiamate).

## Dopo (Claude), prove con Jev vero sul Pro
Insieme di prova: Patologia 2026-11-12 (8 pertinenti mancate), lezione 20 (pertinenti mancate),
lezione 59 PDF "Classificatori avanzati" (pagine fuori tema). Varianti da confrontare:
- concetti chiave dell'outline (`key_concepts`) nel testo delle candidate;
- una sola domanda a scelta tra le candidate + "nessuna" invece di una noul per candidata;
- lettura dall'immagine (`material_pages_reader: image`, già nel codice).
Si adotta la variante che recupera le pertinenti senza far entrare le fuori tema; se serve codice oltre
20 righe va in un secondo giro di agy.

## Dopo (Claude)
- Verifica sul Pro: lezione di prova + 2 lezioni con materiali diversi (PDF pulito, foto di proiettore).
- Prova a parte: concetti chiave dell'outline (`key_concepts`) nel testo delle candidate per Jev, misurando
  le probabilità prima e dopo; se aiuta, Claude ricalibra le fasce.
