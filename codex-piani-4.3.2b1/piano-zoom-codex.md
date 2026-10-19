# Piano per Codex · 4.3.2b1 · Zoom dell'interfaccia e zoom del testo nello Studio

Base: `claude/rt-4.3.2-beta`. File: `rt/window.py` (menu dell'app), `frontend/src/lib/` (nuovo `zoom.ts`), `frontend/src/main.tsx` o `App.tsx`, `frontend/src/components/settings/preferences.tsx`, `frontend/src/components/study/Study.tsx`, più i test.

## Richiesta (Attilio)
1. Uno zoom di tutta RT nelle opzioni Vista, come lo zoom del browser.
2. Un secondo zoom che ingrandisce solo il testo e solo nella pagina Studio, comandato soltanto dai tasti `+` e `-`.

## Contesto
- Nell'app (pywebview, `rt/window.py`) la finestra su Mac usa WKWebView, che non ha lo zoom del browser: Cmd + / Cmd − oggi non fanno nulla. Il menu dell'app (`_menu`) ha già voci come Ricarica e Apri nel browser. Su Mac c'è anche il menu di sistema "Vista" (`cocoa.menu.view`, oggi con solo "Attiva tutto schermo").
- Le preferenze di RT (`usePreference`) sono sincronizzate tra dispositivi. Lo zoom però è una scelta del singolo schermo (Mac contro telefono): va tenuto solo sul dispositivo, in `localStorage`, con try/catch come fa già `cachePreference`.

## 1. Zoom dell'interfaccia
- **`frontend/src/lib/zoom.ts`**
  - Livelli fissi `[0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2]`, valore iniziale 1.
  - `getZoom()`, `setZoom(v)`, `zoomIn()`, `zoomOut()`, `resetZoom()`.
  - Il valore si salva in `localStorage['rt-device:zoom']` e si applica con `document.documentElement.style.zoom = String(v)` (WebKit, Chromium e Firefox recenti supportano la proprietà CSS `zoom`).
  - Un evento `rt-zoom-change` avvisa chi mostra il valore.
  - Applicare il valore salvato in `main.tsx` prima del primo render, così non c'è uno scatto all'apertura.
  - Verificare che popup posizionati con `getBoundingClientRect` (calendario, menu del documento, tooltip DOM) restino al posto giusto con zoom ≠ 1. Se qualcuno calcola le coordinate a mano, dividerle per lo zoom con un helper `zoomed(px)` esportato da `zoom.ts`.
- **Scorciatoie (solo nella finestra dell'app):** Cmd/Ctrl `+` (accettare anche `=` e il + del tastierino), Cmd/Ctrl `-` e Cmd/Ctrl `0` chiamano `zoomIn` / `zoomOut` / `resetZoom` con `preventDefault`. Nel browser normale non intercettarle: lì c'è già lo zoom del browser e farlo due volte confonde. Per sapere se si è nell'app, `window.py` deve passare un segnale. La via più semplice: aggiungere `?app=1` all'URL iniziale (o un cookie/flag già esistente per l'autenticazione dell'app, se c'è) e salvarlo in `sessionStorage['rt-app']`.
- **Menu dell'app (`rt/window.py`, `_menu`):** un gruppo dopo "Ricarica" con "Ingrandisci", "Riduci" e "Dimensioni reali". Ciascuna voce chiama `window.evaluate_js("window.rtZoom && window.rtZoom('in'|'out'|'reset')")`, e `zoom.ts` espone `window.rtZoom`. Su Mac le voci vanno nel menu "Vista" di sistema se pywebview lo permette; altrimenti nel menu RT come le altre voci. pywebview 6.2.1 non mette scorciatoie sulle voci: le scorciatoie restano quelle del punto precedente. Aggiornare `_window_smoke` / il test del menu se elenca le voci.
- **Impostazioni › Aspetto (`preferences.tsx`):** campo "Zoom" con una `Select` dei livelli in percentuale (67%…200%) e un pulsante "100%". Vale su questo dispositivo, quindi funziona anche nel browser e sul telefono. Testo di aiuto: "Solo su questo dispositivo. Nell'app anche con Cmd + e Cmd − (Ctrl su Windows)."

## 2. Zoom del testo nello Studio
- **Solo in `Study.tsx`**, solo il testo della lezione: il contenitore dei paragrafi letti, non intestazione, barre, popup delle note e lettura veloce.
- Variabile CSS `--study-text-scale` sul contenitore del testo, con `font-size: calc(<dimensione attuale> * var(--study-text-scale))`. Formule KaTeX e immagini seguono in proporzione, perché usano `em`. Valore salvato in `localStorage['rt-device:study-text-scale']`; livelli da 0.8 a 2.0 a passi di 0.1, iniziale 1.
- **Tasti:** `+` (anche `=` senza Shift e il + del tastierino) ingrandisce, `-` (anche il − del tastierino) riduce. Valgono solo se nessun modificatore è premuto (Cmd, Ctrl, Alt) e se il focus non è in un campo di testo, una textarea o un elemento `contenteditable`, come le altre scorciatoie dello Studio. Aggiungerli nello stesso gestore `keydown` già presente, controllando che non ci siano conflitti con le scorciatoie attuali (frecce, evidenziatore, lettura veloce, che ha il suo `keydown`: con la lettura veloce aperta i tasti non fanno nulla).
- A ogni cambio compare per un attimo un'etichetta discreta in basso, per esempio "Testo 120%" per circa un secondo, con `role="status"`. Nessun pulsante: Attilio lo vuole solo da tastiera.
- Dopo il cambio, la posizione di lettura resta sul paragrafo in cima allo schermo: prima del cambio salvare il paragrafo visibile in alto, dopo farci `scrollIntoView({block:'start'})`. Così il testo non "scappa".
- Aggiungere `+` e `-` all'elenco delle scorciatoie dello Studio, se esiste un aiuto scorciatoie (cercare dove sono elencate frecce ed evidenziatore).

## Test (vitest)
- `zoom.ts`: `zoomIn` da 1 va a 1.1 e si ferma a 2; `zoomOut` si ferma a 0.67; il valore si salva in localStorage e si applica a `documentElement.style.zoom`; con localStorage che lancia eccezioni funziona lo stesso.
- Scorciatoie dell'interfaccia: con il segnale dell'app Ctrl+`=` ingrandisce e fa `preventDefault`; senza segnale non fa nulla.
- Aspetto: cambiare la Select aggiorna lo zoom; "100%" lo azzera.
- Studio: `+` porta `--study-text-scale` a 1.1; `-` torna a 1; in una textarea o con Ctrl premuto non cambia nulla; con la lettura veloce aperta non cambia nulla; l'etichetta "Testo 110%" compare.
- pytest: il menu di `rt/window.py` contiene le tre voci di zoom.

Comandi: `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`, `python -m pytest tests/test_window*.py -q`.

## Changelog
Sezione 4.3.2b1, Novità:
- "Zoom di RT: in Impostazioni › Aspetto e, nell'app, con Cmd + / Cmd − / Cmd 0 (Ctrl su Windows) o dal menu. Vale solo sul dispositivo dove lo imposti."
- "Nello Studio i tasti + e − ingrandiscono o riducono solo il testo della lezione."
