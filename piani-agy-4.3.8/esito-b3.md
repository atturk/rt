# Esito Piano 4.3.8b3

- Voce 1 (Guida nel menu «Aiuto» della barra dei menu): Fatta - Aggiunto il menu nativo di primo livello «Aiuto» con «Cerca nella guida…», sottomenu per ogni pagina e ancore per sezioni (`setHelpMenu_` su macOS, barra menu nativa su Windows).
- Voce 2 (Guida modificabile da Attilio, con immagini): Fatta - Creato `docs/guida/indice.yml` come unica sorgente per ordine e titoli, supporto immagini inline con fallback in `GuideMarkdown.tsx` e guida `docs/guida/COME-MODIFICARE.md`.
- Voce 3 (Bottone «Indietro» della guida bloccato): Fatta - Risolto il blocco di navigazione in `/guida` con tracciamento `returnAddress` per tornare alla pagina di provenienza o a `/` senza restare intrappolati nella guida.
- Voce 4 (Niente bottone «?» dentro l'app): Fatta - Rimosso il pulsante `?` da `PageHeader` e rimosso `HelpLink`, aggiunta la voce di menu «Guida» in Impostazioni e mantenuti gli shortcut F1 / ⌘?.
- Voce 5 (Togli «Genera domande» dal ripasso vuoto): Fatta - Rimosso il link contestuale «Genera domande» dalla schermata di ripasso vuoto in `LightweightSession.tsx`, preservando il pulsante «Genera».
- Voce 6 (Stati di studio personalizzati): Fatta - Implementati stati personalizzati configurabili in Impostazioni (aggiungi, modifica, riordina, elimina con conteggio unità in uso), ciclo tasto S / click icona e fallback di import/sconosciuti a `in-apprendimento`.
- Voce 7 (Player audio a scomparsa in Studio): Fatta - Aggiunto player audio a scomparsa in Studio e barra zen con pulsante cuffie se presente audio; con player aperto i tasti freccia ←/→ eseguono seek ±5s senza cambiare unità.
- Voce 8 (Valutazione delle risposte mirate e vaste): Fatta - Introdotti i parametri Correttezza, Completezza e Attinenza in riga dedicata, flusso interattivo con domanda di approfondimento (testo, voce, non lo so, salta) e salvataggio recap.
