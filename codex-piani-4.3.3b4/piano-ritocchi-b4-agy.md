# Piano · ritocchi 4.3.3b4 (agy)

Ultimi ritocchi della 4.3.3b4. Cinque punti. Le ore da recuperare cliccabili nel riepilogo della
settimana le fa Claude in `CalendarPopups.tsx`: non toccare quel file.

## 1. Righe della pagina Lezioni

File: `frontend/src/components/lessons/LessonsView.tsx` (`LessonRow`, `ReviewShield`),
`frontend/src/lib/lessonsPage.ts` (`lessonSubtitle`), `rt/services/lesson_service.py`
(`_info_counts`), `rt/api/schemas.py` (modello della lezione).

1.1 **Cerchio a destra.** Oggi `lesson-indicators` ha due caselle da 34 px: anello e scudo. Quando
lo scudo manca resta una casella vuota e l'anello non è sul bordo destro. Togli la casella dello
scudo e `ReviewShield`: resta solo la casella dell'anello, sul bordo destro della riga. La casella
resta anche quando l'anello non c'è, così le righe restano allineate.

1.2 **Verificato e media nel sottotitolo.** In fondo a `lessonSubtitle`, dopo unità e domande:
- `Verificato` se `phases.review === 'VALID'` e `pending_issues === 0`, la stessa condizione dello
  scudo di oggi. Altrimenti niente.
- `N media` se la lezione ha almeno un media, altrimenti niente.

Esempio: `12 ott · Fassetti · 16 unità · Verificato · 14 media`.

Il numero dei media è quello che mostra la Galleria del pannello arricchimento (`useLessonImages`,
cioè `GET /lessons/{id}/images`, senza filtri). Aggiungi `media_count: int = 0` al modello della
lezione e calcolalo in `_info_counts` contando la stessa sorgente dell'endpoint, senza leggere le
immagini e senza aprire file pesanti: la pagina Lezioni carica tutte le lezioni insieme. Rigenera lo
schema.

Test: unitari di `lessonSubtitle` (con e senza verifica, con e senza media), pytest per
`media_count` (0 senza immagini, N con N immagini). Aggiorna gli e2e che cercano
`lesson-review-shield`.

## 2. Avviso delle lezioni mancanti

Oggi (`MissingLessonsButton.tsx`, `calendar_service.get_missing_lessons`):
- funziona solo se è impostato l'**Inizio del periodo** (dal riepilogo di una settimana nel
  calendario); senza, l'API risponde vuota e non compare niente;
- compare solo con il raggruppamento per materia;
- si apre con un clic, in una finestra modale.

Nuovo comportamento:

2.1 **Al passaggio del mouse.** Il triangolo resta piccolo accanto al nome del gruppo. Al passaggio
del mouse (e al focus) si apre un piccolo popup ancorato al triangolo, con lo stesso elenco di oggi e
gli stessi link al blocco del calendario. Usa il comportamento del punto 4 (resta aperto 3 s dopo
l'uscita, si chiude subito con un clic altrove). Su telefono, senza hover, lo apre il tocco. Niente
modale.

2.2 **Tutti i raggruppamenti.** Il triangolo compare nell'intestazione di ogni gruppo che ha lezioni
mancanti:
- `materia`: le ore mancanti di quella materia (come oggi);
- `data`: le ore mancanti di quel giorno;
- `mese`: le ore mancanti di quel mese;
- `docente`: le ore mancanti con quel docente. Aggiungi `docente` a `CalendarToRecoverItem`, preso
  dall'evento del calendario;
- `nessuno`: nessuna intestazione, nessun avviso.

Il calcolo resta nel backend: il frontend filtra la risposta di `useMissingLessons` per la chiave del
gruppo. Confronta materie e docenti con la stessa normalizzazione già usata per i gruppi.

Test: pytest per `docente` negli elementi; vitest per il filtro di ogni raggruppamento; e2e per
l'apertura al passaggio del mouse.

## 3. Strumenti dello Studio in un gruppo espandibile

File: `frontend/src/components/study/Study.tsx` (`HighlightTools`).

Oggi evidenziatore, gomma, Verifica e Chiedi sono un gruppo sempre aperto, e il cestino «Togli tutte
le evidenziazioni» è un pulsante a parte. Nuovo comportamento:
- il cestino entra nel gruppo, in fondo, dopo Chiedi, con lo stesso popup di conferma;
- chiuso, il gruppo mostra un solo pulsante con l'icona `PencilRuler` di lucide e tooltip
  «Strumenti». Se è attivo uno strumento (evidenzia, gomma, verifica, chiedi), il pulsante chiuso
  mostra l'icona di quello strumento, così si vede cosa è attivo;
- si apre al passaggio del mouse con il comportamento del punto 4. Su telefono lo apre il tocco;
- le scorciatoie (G, V, C e le altre) funzionano anche a gruppo chiuso.

Aggiorna gli e2e dello Studio che cliccano `highlight-*` perché aprano prima il gruppo.

## 4. Gruppi espandibili: aperti per 3 s dopo l'uscita

Oggi i gruppi che si aprono al passaggio del mouse usano solo il CSS (`group-hover`): uscendo per un
attimo si richiudono. I gruppi sono:
- `LessonUpdateBar.tsx`: «Aggiorna» che si divide (`group/split`);
- `routes/calendar.tsx`: il menu della matita (`group-hover:flex`, circa riga 363);
- il nuovo gruppo degli strumenti dello Studio (punto 3);
- il popup delle lezioni mancanti (punto 2).

Crea un hook condiviso, per esempio `frontend/src/lib/useHoverExpand.ts`, e usalo in tutti:
- entrata del puntatore nel gruppo: si apre e si annulla il timer;
- uscita: parte un timer di 3 s, poi si chiude;
- rientro prima dei 3 s: resta aperto;
- clic o tocco fuori dal gruppo: si chiude subito;
- Esc: si chiude subito;
- il focus da tastiera dentro il gruppo lo tiene aperto.

Togli le classi `group-hover` di questi gruppi: lo stato viene solo dall'hook. Mantieni i
comportamenti di oggi al tocco e da tastiera (per esempio il clic su Aggiorna che divide senza
avviare Estendi).

Test: vitest dell'hook con timer finti (resta aperto a 2,9 s, chiuso a 3 s, rientro, clic fuori,
Esc).

## 5. Ritorno alla pagina Lezioni sulla lezione appena chiusa

Oggi tornando da una lezione alla pagina Lezioni la pagina riparte dall'alto.

Nuovo comportamento: se la pagina precedente era una lezione (`/lezioni/:id`, Studio di una lezione
escluso), comunque ci si torni (freccia indietro, icona della barra laterale, altri pulsanti):
- la riga di quella lezione viene portata al centro dello schermo, senza animazione di scorrimento;
- la riga si evidenzia per 2 s con uno sfondo più marcato (`bg-accent` o un token simile, che
  funzioni in tema chiaro e scuro), poi torna come le altre con una dissolvenza breve;
- se la lezione non è nella lista (filtrata o in un gruppo chiuso), non succede niente.

Implementazione suggerita: la pagina della lezione, quando si chiude, salva l'id in una variabile di
modulo (non in localStorage). La pagina Lezioni lo legge una volta, al primo render con i dati, e lo
cancella. Qualunque altra pagina aperta nel mezzo lo cancella, così il ritorno dal calendario non
evidenzia niente. Rispetta `prefers-reduced-motion` per la dissolvenza.

Test: e2e: apri una lezione in fondo alla lista, torna con l'icona della barra laterale, la riga è
visibile e ha l'attributo dell'evidenziazione, che sparisce dopo 2 s.
