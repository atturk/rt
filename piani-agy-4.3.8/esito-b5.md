# Esito Piano 4.3.8b5

- Voce 1: Fatta — creata anteprima personalizzata compatta (68 px, angoli arrotondati, ombra/bordo) staccata di 18 px dal cursore con elemento fixed e soppressione anteprima nativa ingombrante.
- Voce 2: Fatta — le miniature degli allegati portano fromText/fromUnit; rimozione singola riga al rilascio sul pannello Media con velo di conferma «Rilascia per togliere dall'unità» e funzione removeImageOccurrence.
- Voce 3: Fatta — selezione multipla con Cmd/Ctrl+clic e Shift+clic, deselezione su clic vuoto o Esc; drag singolo o multiplo con payload a lista retrocompatibile, transazione atomica con un solo annulla Cmd+Z e anteprima a mazzo con badge.
- Voce 4: Fatta — ordine di resa delle slide LibreOffice → Keynote (osascript) → Quick Look con verifica conteggio pagine rigoroso, log worker chiaro in caso di fallimento e filtro delle immagini piccole/corrotte per il ripiego.
- Voce 5: Fatta — stili in PrintLessonPage per elenchi puntati (.print-page ul disc), numerati (ol decimal), padding-left 1.4em, spaziatura tra voci ed elenchi annidati con circle.
- Voce 6: Fatta — dentro le formule in repair_latex_escapes ripristinato prefisso \m davanti a athrm{, athbf{, athit{, athcal{, athbb{, athsf{ quando non preceduti da lettera o barra.
- Voce 7: Fatta — con il player aperto Alt+frecce (Option su Mac) cambiano unità (navigateReading) mentre le frecce da sole mantengono il seek ±5 s; comandi «Unità precedente» e «Unità successiva» configurabili nel gruppo Studio di Editor e scorciatoie.
- Voce 8: Fatta — al cambio di unità con player aperto l'audio si sposta al timestamp d'inizio della nuova unità conservando play/pausa; preferenza «Il player segue l'unità» in Impostazioni → Aspetto e lettura (sezione Studio).
- Voce 9: Fatta — in StudyStatusesSection sostituite le frecce con maniglia GripVertical; riordino con drag & drop HTML5, linea d'inserimento visibile, salvataggio al rilascio e Alt+↑/↓ da tastiera sulla maniglia.
