# RT 4.3.3b1 · piani

Ramo della beta: **`claude/rt-4.3.3-beta`**, creato da `main` dopo la stable 4.3.2. Le PR degli
agenti vanno lì. Wireframe del piano 1: https://claude.ai/artifact/FhSTW8rDPPtGKhhpzdNzJ3

| # | Piano | Agente |
|---|-------|--------|
| 1 | `piano-immagini-sottounita-codex.md`: bottone con la graffetta e sezione delle immagini al posto del blocco; via "Dove le lascio" | Codex |
| 2 | `piano-pannello-arricchimento-agy.md`: pannello Arricchimento allargabile; clic su un'immagine della lezione la porta al centro del pannello | agy |
| 3 | `piano-archivio-veloce-agy.md`: archivio veloce (un solo giro sulle lezioni) e caricamento animato | agy |
| 4 | `piano-archivio-pagine-pdf-agy.md`: le pagine dei PDF non finiscono nell'archivio come immagini, pulizia di quelle già create | agy |

Task: `TASK-codex.md` (piano 1), `TASK-agy.md` (piani 4, 3, 2). I file non si sovrappongono; lo
schema OpenAPI e `index.css`, se vanno in conflitto, li sistemo io all'unione.
