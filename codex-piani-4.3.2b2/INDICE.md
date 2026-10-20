# Piani per la 4.3.2b2

Base: `claude/rt-4.3.2-beta` (dopo la 4.3.2b1). Ogni PR va verso quel branch.

1. `piano-aggiornamenti-app-codex.md`: aggiornamenti in un popup della finestra dell'app, download separato dall'installazione e conservato su disco, Installa e riavvia, canale beta anche dall'app.
2. `piano-notifiche-dock-codex.md`: notifica di sistema quando un job finisce o aspetta una decisione con la finestra in secondo piano; numero dei job sull'icona nel Dock.
3. `piano-apri-con-codex.md`: file aperti con RT ("Apri con", icona nel Dock, doppio clic su Windows) che aprono Nuova lezione.
4. `piano-risposte-codex.md`: ogni risposta è un tentativo nello storico; le domande riposte non mostrano la vecchia risposta; pagina Risposte dal pannello Domande.
5. `piano-dmg-apri-comunque-codex.md`: firma ad-hoc di RT.app e sfondo del DMG con le istruzioni per Apri comunque.
6. `piano-archivio-base-codex.md`: archivio unico delle fonti in `<data>/archivio/`, niente rielaborazioni dello stesso file, popolamento dalle lezioni esistenti.
7. `piano-archivio-pagina-codex.md`: pagina Archivio (elenco, dettaglio ridimensionabile, griglia e pagina singola, ignora, ritaglia, elimina, aggiungi a una lezione o ai suoi media).
8. `piano-aggiungi-fonte-codex.md`: finestra Aggiungi fonte con "Già nell'archivio", pagine, Estrai e Uso; DOCX e TXT.
9. `piano-immagini-nel-testo-codex.md`: immagini trascinate sotto il titolo della sottounità o dove le lasci, ridimensionamento, clic che seleziona nei media, cancellazione nel testo.
10. `piano-pannello-arricchimento-codex.md`: pulsante Archivio nel pannello, filtro Da descrivere, nuova barra della selezione.
11. `piano-integra-codex.md`: uso Integra, la fonte entra nella scaletta e può aggiungere unità.

Wireframe approvato dell'archivio: https://claude.ai/artifact/P1KzSVbQfXixTkEJ1kPBjf

"Salva con nome" per gli export non serve: nell'app pywebview mostra già la finestra di salvataggio per ogni download (Mac e Windows).

## Divisione del lavoro

Primo giro (in parallelo, poi unione):
- Codex, ramo `codex/4.3.2b2`: piani 6, 8, 7. Prompt: `TASK-codex.md`.
- agy, ramo `agy/4.3.2b2`: piani 1, 2, 3, 5, 4, 9. Prompt: `TASK-agy.md`.

Secondo giro (rami da `claude/rt-4.3.2-beta` dopo l'unione del primo):
- Codex, ramo `codex/4.3.2b2-giro2`: piano 11. Prompt: `TASK-codex-giro2.md`.
- agy, ramo `agy/4.3.2b2-giro2`: piano 10. Prompt: `TASK-agy-giro2.md`.

Poi unione, versione, changelog e rilascio della 4.3.2b2.
