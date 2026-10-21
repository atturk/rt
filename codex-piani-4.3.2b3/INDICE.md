# RT 4.3.2b3 · piani

Ramo di integrazione: **`claude/rt-4.3.2b3`** (parte da v4.3.2b2 e ha già due correzioni dirette:
evidenziatore dello Studio che si spegne dopo l'ultimo colore; popolamento dell'archivio con nome
leggibile e avanzamento per lezione). Le PR degli agenti vanno lì; alla fine lo unisco nella beta.

| # | Piano | Agente |
|---|-------|--------|
| 1 | `piano-verifiche-unita-sparite-codex.md`: le issue di un'unità sparita dopo la rielaborazione non restano "Da riconfermare" in loop | Codex |
| 2 | `piano-lezioni-ordine-agy.md`: nessun raggruppamento in Lezioni e ordine "(Ri)create di recente" | agy |
| 3 | `piano-esporta-pdf-agy.md`: Esporta PDF, immagini due per riga a 1600 px | agy |
| 4 | `piano-nomi-job-agy.md`: nomi leggibili per tutti i job | agy |

Task: `TASK-codex.md` (piano 1), `TASK-agy.md` (piani 4, 2, 3). I file non si sovrappongono; lo schema
OpenAPI, se va in conflitto, lo rigenero io all'unione.
