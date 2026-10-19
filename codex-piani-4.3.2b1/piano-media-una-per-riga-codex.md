# Piano per Codex · 4.3.2b1 · Media della lezione: una pagina per riga

Base: `claude/rt-4.3.2-beta`. File: `frontend/src/components/lesson/panels/MediaGallery.tsx`, `EnrichmentPanel.tsx` e i rispettivi test.

## Richiesta (Attilio)
In Arricchimento › Media della lezione le pagine sono in una griglia a 3 colonne (`grid grid-cols-3`): nel pannello laterale le slide diventano miniature illeggibili. Serve una vista con una slide per riga, a tutta larghezza, con scorrimento verticale.

## Cosa fare
1. **Due viste, "Righe" (predefinita) e "Griglia".** In `EnrichmentPanel.tsx`, nell'intestazione "Media della lezione · N" accanto ai pulsanti Aggiungi e Cerca, aggiungere una `IconButton` che alterna la vista: icona `Rows3` (lucide) con label "Una pagina per riga" quando si è in griglia, icona `LayoutGrid` con label "Vista a griglia" quando si è in righe. Stato `mediaView: 'rows' | 'grid'`, letto e salvato in `localStorage` con chiave `rt.media.view` (try/catch come per `autoPlaceMode`, valore predefinito `'rows'`). Passarlo a `MediaGallery` come prop `view`.
2. **In `MediaGallery`, vista `rows`:**
   - contenitore del gruppo `flex flex-col gap-3` al posto di `grid grid-cols-3 gap-2.5` (stesso `role="group"` e `aria-label`);
   - la cella occupa tutta la larghezza; il riquadro immagine usa `aspect-video` (le slide sono 16:9) invece di `aspect-[4/3]`, sempre con `object-contain`, così una pagina verticale (foto, A4) resta intera con bande ai lati;
   - didascalia sotto l'immagine su una riga: "Pag. N" a sinistra, unità usate (in grassetto) o "non usata" a destra; niente `font-mono` in questa vista, testo `text-meta`, senza troncare a 3 colonne (resta `truncate` solo sulla parte unità se lunga).
   - Tutto il resto identico alla griglia: selezione con clic e Maiusc+clic, doppio clic per il visore, pressione lunga, trascinamento nel testo, pulsante Ritaglia, badge ritaglio, opacità delle non usate.
3. **Vista `grid`:** esattamente il codice di oggi.
4. Per non duplicare la cella, estrarre il rendering di una pagina in un componente interno (`MediaCell`) con una prop `view` che cambia solo le classi del contenitore, del riquadro e della didascalia.
5. `loading="lazy"` sulle immagini resta: con 63 pagine a tutta larghezza è quello che tiene leggero lo scorrimento.

## Test (vitest)
- `MediaGallery` con `view="rows"`: il gruppo non ha la classe `grid-cols-3`, la cella ha il riquadro `aspect-video`; con `view="grid"` torna `grid-cols-3`.
- `EnrichmentPanel`: di base la vista è a righe; il pulsante "Vista a griglia" passa alla griglia e salva `rt.media.view = 'grid'` in localStorage; rimontando il pannello resta in griglia.
- I test esistenti di selezione, Maiusc+clic, ritaglio e trascinamento in `MediaGallery.test.tsx` restano verdi (aggiornare solo dove assumono la griglia; farli girare in entrambe le viste se semplice).

Comandi: `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run src/components/lesson/panels`.

## Changelog
Sezione 4.3.2b1 di `CHANGELOG.md`: "Media della lezione mostra una pagina per riga, grande e leggibile. Il pulsante accanto a Cerca torna alla griglia, e RT ricorda la scelta."
