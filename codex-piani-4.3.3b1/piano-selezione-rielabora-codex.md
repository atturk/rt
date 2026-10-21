# Piano 6 · Selezione multipla: rieseguire la pipeline da Dettagli

Agente: **Codex**. Nella pagina Lezioni, con più lezioni selezionate, il popup Dettagli
("3 lezioni selezionate", `frontend/src/components/lessons/SelectionDetails.tsx`) mostra solo i
numeri. Attilio vuole poter rielaborare da lì come dal pannello Dettagli della singola lezione.

## Cosa c'è nella lezione singola

`frontend/src/components/lesson/panels/DetailsPanel.tsx`, righe ~495-505: quattro pulsanti a icona
- "Includi la revisione scientifica" (`ShieldCheck`, interruttore);
- "Esegui la pipeline" · solo le fasi da fare (`Play`) → job `run_pipeline`;
- "Riesegui tutte le fasi" · anche quelle già fatte (`RotateCw`) → conferma → `run_pipeline` con
  `force: true`;
- "Riesegui tutto da capo" · anche trascrizione e lettura dei documenti (`ListRestart`) → conferma →
  `updateSources` con `mode: 'rebuild', reingest: true` (solo se `reingest_available`).

## Cosa fare

1. Stessi quattro pulsanti, stesse icone e suggerimenti, in alto nel popup della selezione (a
   destra del titolo, prima della X). Niente testo in più.
2. Backend: una rotta sola per non fare N chiamate dal browser:
   `POST /lessons/batch/pipeline` con `{lesson_ids: list[int] (max 200), mode: 'run' | 'force' |
   'reingest', with_review: bool}`. Per ogni lezione riusa esattamente le funzioni che oggi servono
   le rotte della lezione singola (stessi controlli, stessi job, stessa coda). Risposta
   `{queued: [{lesson_id, job_id}], skipped: [{lesson_id, motivo}]}`; motivi: lezione in lavorazione,
   ripartenza da capo non disponibile, lezione non trovata.
3. Conferme, come nella lezione singola ma al plurale: "Rifare tutte le fasi di 3 lezioni?" e
   "Rieseguire da capo 3 lezioni?", con lo stesso testo sui costi. Per "Esegui la pipeline" nessuna
   conferma, come oggi.
4. Dopo l'avvio: il popup resta aperto; una riga breve sotto i pulsanti "3 avviate" oppure
   "2 avviate · 1 saltata" con il motivo nel suggerimento. I job compaiono nella coda come al solito.
5. Pulsanti disattivati con suggerimento "Lavorazione in corso" se **tutte** le lezioni selezionate
   sono già in lavorazione.
6. Rigenera lo schema OpenAPI.

## Test

- pytest: la rotta accoda un job per lezione con il modo giusto, salta quelle occupate e quelle senza
  ripartenza da capo, rifiuta più di 200 id.
- vitest `SelectionDetails`: i quattro pulsanti; la conferma per "tutte le fasi" e "da capo" con il
  numero di lezioni; la riga con avviate/saltate.
