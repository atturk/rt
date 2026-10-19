# Piano per Codex · 4.3.2b1 · Un'immagine da sola si mostra in miniatura

Base: `claude/rt-4.3.2-beta`. File: `frontend/src/components/lesson/lessonImageStrips.ts` (editor), `frontend/src/components/images/imageStripDOM.ts` (`mountDocumentImageStrips`, pagina della lezione e Studio) e i loro test.

## Richiesta (Attilio)
Quando in una sezione c'è una sola immagine, compare a tutta larghezza ed è invadente. Deve comparire in miniatura, come già succede quando le immagini sono due o più.

## Causa
La striscia di miniature si forma solo da 2 immagini consecutive in su:
- `findMarkdownImageStrips` (editor): `currentImages.length >= 2`, in due punti;
- `mountDocumentImageStrips` (documento e Studio): `flushGroup` con `currentImages.length >= 2`.
Un'immagine singola resta un normale `![...]()`, mostrato a piena larghezza (nell'editor da `lessonImages` in `lessonUnits`).

## Cosa fare
1. Abbassare la soglia a 1 in tutti e tre i punti, con una costante condivisa `MIN_STRIP_IMAGES = 1`, esportata da `imageStripDOM.ts` e usata anche in `lessonImageStrips.ts`. Aggiornare i commenti che dicono "2 o più" e "un'immagine singola resta invariata".
2. Nell'editor, il comportamento resta quello della striscia: con il cursore fuori si vede la miniatura; con il cursore sulla riga compare il Markdown da modificare. Verificare che `lessonImages` non disegni anche lui la stessa immagine a piena larghezza sopra o sotto la striscia (doppione). Se lo fa, escludere da `lessonImages` le righe già coperte da una striscia.
3. Clic sulla miniatura: si apre il visore come per le strisce di più immagini (stesso codice di `buildImageStripDOM`, nessuna modifica attesa). Controllare che una striscia di una sola immagine non mostri frecce o contatori "1 di 1" inutili. Se li mostra, nasconderli quando `images.length === 1`.
4. Esportazioni (PDF/DOCX/Markdown) e trascinamento delle immagini dai Media non cambiano: si tocca solo la visualizzazione.

## Test (vitest)
- `findMarkdownImageStrips`: un'immagine singola tra due paragrafi produce una striscia con 1 immagine; due immagini consecutive ne producono una con 2 (come oggi).
- `mountDocumentImageStrips`: un `<p><img></p>` da solo viene sostituito da `.rt-image-strip-slot`; lo smontaggio rimette il paragrafo originale.
- Editor: con il cursore fuori, la riga dell'immagine singola è sostituita dalla striscia; con il cursore dentro, si vede la riga Markdown.
- Aggiornare i test esistenti che si aspettano "immagine singola invariata".

Comandi: `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`.

## Changelog
Sezione 4.3.2b1, Novità: "Un'immagine da sola nel testo si mostra in miniatura, come le serie di immagini: clic per vederla in grande."
