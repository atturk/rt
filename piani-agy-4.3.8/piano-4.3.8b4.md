# Piano 4.3.8b4 (oltre a piano-condivisione.md)

Base: `agy/4.3.8-condivisione` (= v4.3.8b3 + piano condivisione). Una voce per commit, dopo le voci 1-4 di `piano-condivisione.md`. Non modificare il testo di `docs/guida/*.md`.

## 5. Studio: via il blocco «Genera», bottone domande nella barra in alto

- In Studio il player audio (voce 7 della b3) finisce sopra il blocco in basso con «Genera»/«Genera altre»/«Ripassa l'unità»: **togli tutta quella barra in basso** (anche nella lettura veloce e in zen, se c'è lo stesso blocco).
- Al suo posto un **bottone con l'icona del cervello** (la stessa già usata per le domande, `Brain` di lucide) nella barra in alto, **subito accanto al bottone cuffie** (a sinistra o a destra, coerente con gli altri). Tooltip: «Domande su questa unità».
- Il bottone apre direttamente la schermata domande **della sola unità aperta** (lo stesso ripasso per unità di oggi). Se non ci sono domande per l'unità, in quella schermata l'utente le genera da lì (il blocco «Genera» con numero e tipi che c'è già nel ripasso vuoto). Tornando indietro si torna all'unità di Studio da cui si era partiti.
- Se esisteva una scorciatoia da tastiera per «Ripassa/Genera» sull'unità, la tieni sul nuovo bottone.
- Aggiorna i test e2e/vitest che cercano i quattro pulsanti tondi o «Genera altre» in Studio (es. `study.spec.ts` «quattro pulsanti tondi…», «finite le domande dell'ultima unità…»): ora devono passare dal bottone cervello.

## 6. Player audio spostabile (in basso, a sinistra, a destra)

- Il player di Studio si può **ancorare in tre posizioni**: in basso al centro (come ora), sul **lato sinistro** o sul **lato destro**, a metà altezza della pagina. Nei lati il player è verticale/compatto (play, tempo, velocità, ±5 s) e non copre il testo (il testo resta centrato; se lo spazio laterale è troppo poco, es. finestra stretta o telefono, resta solo «in basso»).
- Si sposta **trascinandolo** (maniglia): al rilascio va all'ancoraggio più vicino (non posizioni libere). In alternativa un piccolo menu sul player «Sposta a sinistra / in basso / a destra» per chi non trascina (anche per accessibilità).
- La posizione si ricorda per dispositivo (impostazione locale, come lo zoom).
- Vale anche per il player della pagina lezioni se usa lo stesso componente; se no, solo Studio.
- Test vitest: cambio ancoraggio dal menu, posizione ricordata, su schermo stretto solo «in basso».

## 7. Zoom (Ingrandisci/Riduci) che rompe il disegno della pagina

- Oggi `frontend/src/lib/zoom.ts` usa `document.documentElement.style.zoom`. Nell'app Mac (WKWebView), nella pagina lezione con zoom diverso da 100 %, scorrendo il testo viene disegnato solo nella parte alta e poi scompare (screenshot di Attilio). È il CSS `zoom` sull'intera pagina.
- Correggi così:
  - **App desktop**: usa lo zoom nativo della finestra invece del CSS. macOS: `WKWebView.setPageZoom_` (macOS 11+) via pyobjc in `rt/window.py`; Windows: `ZoomFactor` del controllo WebView2. Esponi in `DesktopApi` un metodo `set_zoom(fattore)` e fai chiamare quello da `zoom.ts` quando c'è il ponte desktop. Fattore e limiti come oggi; persistenza come oggi.
  - **Browser** (web app, iPhone): niente `zoom` sull'`<html>`; scala la dimensione del testo di base (`font-size` della radice, l'interfaccia è in rem) oppure lascia lo zoom del browser (⌘+/⌘−) e nascondi i comandi interni. Scegli la via che non rompe i layout esistenti e dillo nell'esito.
  - Aggiorna `zoomed(px)` e chi lo usa, se la scala cambia significato.
- Test: vitest su `zoom.ts` (ponte desktop chiamato, nessuno stile `zoom` sull'html); test Python per `set_zoom` con webview finto. La verifica visiva sul Mac la fa Attilio sulla beta.

## Prima della PR

Quella di `piano-condivisione.md` più:
- `python -m pytest tests/ -q -n auto --dist loadfile -p no:cacheprovider`
- `cd frontend && npm run -s typecheck && npm run -s lint && npx vitest run`
- `npm run build` e poi `npx playwright test e2e/study.spec.ts e2e/lesson-view.spec.ts e2e/settings.spec.ts` (gli e2e usano `frontend/dist`: senza build provano la versione vecchia).
