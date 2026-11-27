# Piano agy: lezione di esempio come guida rapida, senza tracce (P12 + P17)

Base: main (104f9d1). Prima di tutto: `git pull` di questo branch. Solo codice, contenuti e test unitari, niente Playwright.

File: `scripts/make_sample_lesson.py` (genera `rt/assets/esempio/lezione-esempio.rt`), `rt/api/routers/lessons.py` (`POST /lessons/sample`),
l'import (`import_archive`), la cancellazione lezione, `frontend/src/components/lessons/WelcomeBox.tsx`.

Attenzione: il thread della beta corregge da sé B1 (la lezione di esempio dava errore 500 perché `outline.json` ha il formato
vecchio). Se nel frattempo è su main, fai `git merge origin/main` prima di iniziare; altrimenti genera già l'outline nel formato
che legge oggi `rt/pipeline/outline.py` `load_outline` e aggiungi un test che importa l'esempio e lo apre senza errori.

## P12 — una vera guida rapida dentro una lezione

Oggi la lezione di esempio ha 3 unità generiche. Deve diventare un **quick start condensato**: chi la apre impara RT
usandolo. Riscrivere il contenuto (trascritto, rielaborato, outline, verifica, domande) in 4 sezioni brevi, testo
chiaro per non tecnici, ogni unità 80-150 parole:

1. **Cos'è RT** — 1.1 «Dalla registrazione al testo»: carichi audio e materiali, RT trascrive, divide in unità e rielabora.
   1.2 «Come leggere una lezione»: indice a sinistra, unità con timecode, clic sul timecode = audio da quel punto.
2. **Creare una lezione** — 2.1 «Cosa caricare»: registrazione + slide, PDF, foto della lavagna (facoltativi). 2.2 «Mentre RT lavora»:
   la barra di avanzamento, si può chiudere la finestra, avviso a fine lavoro, costo stimato prima di partire.
3. **Verificare e correggere** — 3.1 «La scheda Verifica»: confronto con le fonti, cosa significano gli avvisi.
   3.2 «Modificare il testo»: modifica diretta, annulla, rigenera un'unità.
4. **Studiare** — 4.1 «Mettimi alla prova»: domande di ripasso e risposte. 4.2 «Stati di studio e calendario»: segnare cosa hai studiato,
   il calendario delle lezioni, Telegram facoltativo.

- Ogni unità può avere **uno screenshot** dell'app: prevedere le immagini come asset della lezione (stesso meccanismo delle immagini delle
  lezioni vere, `assets/images/…`), lette da `rt/assets/esempio/screenshot/<id-unità>.webp` al momento della generazione. agy **non**
  crea gli screenshot: aggiungi i riferimenti e, se il file manca, l'unità esce senza immagine (nessun errore). Claude li cattura dopo,
  con lo stesso nome file. Elenca in `rt/assets/esempio/screenshot/README.md` i nomi attesi e cosa deve mostrare ognuno.
- Domande di ripasso: 4-6, una per sezione, sui comandi veri di RT.
- Dimensione dell'archivio: alzare il limite dello script da 1 MB a 3 MB (gli screenshot WebP stanno sotto 150 KB l'uno).
- Rigenerare `rt/assets/esempio/lezione-esempio.rt` con lo script e committarlo.

## P17 — nessuna traccia della lezione di esempio

Decisione di Attilio: la lezione di esempio non deve lasciare segni nel resto di RT.

1. Nell'import dell'esempio la lezione è marcata come esempio (campo esistente se c'è; altrimenti colonna/flag `is_sample` nel DB con
   migrazione, oppure un marcatore in `info.yaml` letto all'import: scegli la via più piccola).
2. La lezione di esempio **non crea**: una materia reale (niente «ESEMPIO» nell'elenco materie, nei filtri, nei colori, nelle statistiche),
   un docente, blocchi o lezioni nel calendario, notifiche Telegram, voci nei conteggi del ripasso globale. Mostrarla in elenco con l'etichetta
   «Esempio» al posto della materia. Cercare dove si leggono materia/docente per elenchi e filtri e saltare le lezioni esempio.
3. Eliminare la lezione di esempio rimuove **tutto**: cartella, righe DB, cache, eventuali materia/docente creati da versioni precedenti
   se non usati da altre lezioni (così chi l'ha già importata con la 4.3.9 pulisce i residui eliminandola).
4. Reimportarla dopo l'eliminazione funziona (niente «Esiste già una lezione»: vedi fix 77c645d sulla cache del worker).
5. WelcomeBox: nessun cambiamento al flusso (il pulsante chiama ancora `POST /lessons/sample` e apre la lezione).

## Test (pytest)

- import dell'esempio → si apre (outline valido, nessun 500), ha le 4 sezioni e almeno 8 unità;
- dopo l'import l'elenco materie e il calendario non contengono «ESEMPIO»/«Team RT»;
- eliminazione → nessuna riga residua (lezione, materia, docente orfani); reimport ok;
- senza screenshot la generazione non fallisce; con un file finto l'unità ha l'immagine.

## Sovrapposizioni
Il piano «configurazione guidata» apre la lezione di esempio dalla schermata Pronto chiamando la stessa API: nessun conflitto se qui
l'API non cambia firma. Possibile conflitto con il fix B1 del thread della beta in `make_sample_lesson.py`.
