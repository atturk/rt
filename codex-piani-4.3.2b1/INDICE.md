# Piani Codex per la 4.3.2b1

Base: `claude/rt-4.3.2-beta`, creato da main alla 4.3.1 stabile. Ogni PR va verso quel branch. Ordine consigliato:

1. `piano-scaletta-durante-aggiornamento-codex.md`: la scheda "Scaletta da approvare" non resta più a schermo mentre la lezione si aggiorna con nuove fonti.
2. `piano-file-scelti-media-codex.md`: "Aggiungi PDF o foto" mostra i file scelti, e Annulla li scarta.
3. `piano-media-una-per-riga-codex.md`: i Media della lezione mostrano una pagina per riga, e un pulsante torna alla griglia.
4. `piano-anteprima-tenendo-premuto-codex.md`: nella griglia, tenendo premuto su una miniatura si vede l'anteprima grande. Va fatto dopo il 3.
5. `piano-backup-copia-codex.md`: il backup con copia, rimandato dalla 4.3.1. Il piano nomina come base `claude/rt-4.3.1-beta`: per questa beta usa `claude/rt-4.3.2-beta`, e la voce di changelog va nella sezione 4.3.2b1.
6. `piano-ritocchi-dalla-4.3.1-codex.md`: tre ritocchi rimasti dalla 4.3.1 («da capo» senza arricchimento, icone delle unità che sfarfallano, collegamento all'ora perso durante un import).
7. `piano-preparazione-veloce-codex.md`: preparazione più veloce (pagine lette in parallelo, materiali insieme alla trascrizione, avanzamento visibile).
8. `piano-immagine-singola-miniatura-codex.md`: un'immagine da sola nel testo si mostra in miniatura.
9. `piano-docenti-per-materia-codex.md`: docenti per materia in Impostazioni, suggeriti nel campo Docente, Invio nel popup del calendario.
10. `piano-zoom-codex.md`: zoom dell'interfaccia (Aspetto, menu e Cmd +/− nell'app) e zoom del solo testo nello Studio con + e −.
11. `piano-suggerimenti-pulsanti-disattivati-codex.md`: il suggerimento dei pulsanti a icona compare anche quando sono disattivati (con il motivo in Nuova lezione).
12. `piano-informazioni-su-rt-codex.md`: Informazioni su RT con logo, versione e build reali (anche in Impostazioni › Info).
13. `piano-audio-codex.md`: l'audio che si blocca dopo pochi secondi (remux in cache fatto in parallelo e corrotto), con lock, controllo e rifacimento delle voci rotte.
14. `piano-ricerca-fissata-codex.md`: pulsante con la puntina accanto a Cerca che fissa la vista di Lezioni (raggruppamento, ordine, ricerca, filtri); una modifica la sblocca.
15. `piano-lettura-veloce-tasti-codex.md`: lettura veloce con L per entrare e uscire, S per lo stato, Option/Alt+frecce e due pulsanti per le unità, controlli al 25% durante la lettura.
16. `piano-calendario-codex.md`: vista annuale, Vai alla settimana, griglia delle settimane senza leggenda, copia e incolla dello stampo dentro Modifica (anche su più settimane dalla vista annuale), esporta e importa l'orario nelle Impostazioni.

## Divisione del lavoro per la 4.3.2b1

- Codex, ramo `codex/4.3.2b1`: piani 13, 8, 4, 7, 9, 16. Prompt: `TASK-codex.md`.
- agy, ramo `agy/4.3.2b1`: piani 11, 1, 2, 3, 6, 14, 15, 10, 12, 5. Prompt: `TASK-agy.md`.
