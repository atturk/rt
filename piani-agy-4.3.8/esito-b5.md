# Esito Piano 4.3.8b5

- Voce 1: Fatta — creata anteprima personalizzata compatta (68 px, angoli arrotondati, ombra/bordo) staccata di 18 px dal cursore con elemento fixed e soppressione anteprima nativa ingombrante.
- Voce 2: Fatta — le miniature degli allegati portano fromText/fromUnit; rimozione singola riga al rilascio sul pannello Media con velo di conferma «Rilascia per togliere dall'unità» e funzione removeImageOccurrence.
- Voce 3: Fatta — selezione multipla con Cmd/Ctrl+clic e Shift+clic, deselezione su clic vuoto o Esc; drag singolo o multiplo con payload a lista retrocompatibile, transazione atomica con un solo annulla Cmd+Z e anteprima a mazzo con badge.
- Voce 4: Fatta — ordine di resa delle slide LibreOffice → Keynote (osascript) → Quick Look con verifica conteggio pagine rigoroso, log worker chiaro in caso di fallimento e filtro delle immagini piccole/corrotte per il ripiego.
- Voce 5: Fatta — stili in PrintLessonPage per elenchi puntati (.print-page ul disc), numerati (ol decimal), padding-left 1.4em, spaziatura tra voci ed elenchi annidati con circle.
- Voce 6: Fatta — dentro le formule in repair_latex_escapes ripristinato prefisso \m davanti a athrm{, athbf{, athit{, athcal{, athbb{, athsf{ quando non preceduti da lettera o barra.
