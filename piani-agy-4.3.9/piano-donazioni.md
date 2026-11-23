# Piano — Supporta RT: pagina nelle Impostazioni e bottone periodico nella barra

Branch: `agy/4.3.9-donazioni` (parte da `claude/rt-4.3.9-beta`). Solo codice e test unitari, niente verifiche
nell'app. Commit e push sul branch.

## Oggi
- `rt/core/donazioni.py`: `DONAZIONI_URL` (base Ko-fi) e `donazioni_app_url()` → `https://ko-fi.com/attilio_o/donate`.
  `GET /api/v1/system/info` lo espone come `donazioni_url`.
- `frontend/src/routes/settings.tsx`: `SupportButton` blu (cuore + "Supporta RT") sotto "Guida" nella barra delle
  Impostazioni, oggi è un `<a target="_blank">` diretto a Ko-fi (`data-testid="link-sostieni-rt"`).
- I link `target="_blank"` nell'app desktop si aprono nel browser di sistema (`OPEN_EXTERNAL_LINKS_IN_BROWSER`).

## Colore e icona (uguali ovunque)
Blu pieno `bg-blue-600 hover:bg-blue-700 text-white`, icona lucide `Heart` con `fill-current`. Stesso aspetto in
tema chiaro e scuro. Focus visibile `focus-visible:ring-2 ring-blue-400`.

## 1. Backend: stato del promemoria (`rt/services/support_prompt.py`, nuovo)
File JSON `<config_dir>/supporto.json` (usa `rt.core.paths.config_dir()`), scrittura atomica (tmp + `os.replace`),
lettura tollerante (file mancante o rotto = stato iniziale). Stato:
`{"used_days": 0, "last_day": null, "next_at": 7, "hide_streak": 0, "paused_until": null}`.

Funzioni pure con `today: date` iniettabile (per i test):
- `register_day(state, today)`: se `last_day != today` → `used_days += 1`, `last_day = today`.
- `is_visible(state, today)`: `used_days >= next_at` e (`paused_until` è null o `today >= paused_until`).
- `on_opened(state)`: clic sul bottone della barra → `next_at = used_days + 5`, `hide_streak = 0`.
- `on_hidden(state)`: pressione lunga → `hide_streak += 1`, `next_at = used_days + min(5 * 2**hide_streak, 30)`
  (quindi 10, 20, 30, 30…).
- `on_donated(state, today)`: clic su "Dona con Ko-fi" → `paused_until = today + 182 giorni`,
  `next_at = used_days + 5`, `hide_streak = 0`.

Endpoint in `rt/api/routers/system.py`:
- `GET /api/v1/system/support-prompt` → `{ "visible": bool, "url": str }`. Registra il giorno d'uso (data locale)
  e salva. `visible` è sempre false se `donazioni_app_url()` è vuoto. Errori di I/O → `visible: false`, mai 500.
- `POST /api/v1/system/support-prompt` body `{ "event": "opened" | "hidden" | "donated" }` → stesso schema della GET.
- Lock (`threading.Lock` a livello di modulo) attorno a lettura+scrittura.
- Rigenera `docs/openapi.json` (`python scripts/export_openapi.py`) e `frontend/src/api/schema.d.ts`
  (`npm run gen:api` in `frontend/`).

Test `tests/test_support_prompt.py`: primi 7 giorni invisibile, 7° giorno visibile; stesso giorno contato una volta;
opened → riappare dopo 5 giorni d'uso; hidden ripetuto → 10, 20, 30, 30; donated → invisibile per 182 giorni di
calendario anche con molti giorni d'uso, poi visibile; file rotto → stato iniziale; URL vuoto → visible false.

## 2. Pagina "Supporta RT" (`/impostazioni/supporta`)
- Route nuova in `frontend/src/routes/index.tsx` sotto `impostazioni` (`path: 'supporta'`,
  `SupportSettingsPage` in `routes/settings.tsx`). NON aggiungerla a `SETTINGS_SECTIONS` (non è una voce normale).
- In `SettingsLayout`: se il path è `/impostazioni/supporta`, titolo "Supporta RT" (anche su telefono nel
  PageHeader); la freccia indietro funziona già col `useReturnAddress` (riporta alla lezione aperta prima).
- `SupportButton` nella barra delle Impostazioni diventa un `NavLink` a `/impostazioni/supporta` (non più link
  esterno), stesso aspetto blu; da attivo aggiungi `ring-2 ring-blue-400 ring-offset-2 ring-offset-background`.
  Resta nascosto se `donazioni_url` è vuoto. Mantieni `data-testid="link-sostieni-rt"`.
- Contenuto della pagina (max ~52ch):
  - quadrato blu 44px raggio 11px con cuore bianco 22px;
  - titolo `RT è fatto da uno studente, per gli studenti`;
  - testo: `RT è gratuito e senza abbonamenti: usi le tue chiavi e paghi solo quello che consumi dal provider.
    Lo sviluppo va avanti grazie alle donazioni.` e `Se RT ti fa risparmiare tempo, una donazione aiuta a
    tenerlo vivo.`
  - bottone blu `Dona con Ko-fi` (cuore + testo) = `<a href={url} target="_blank" rel="noopener noreferrer">`
    con `onClick` che fa `POST event: "donated"` (non bloccare l'apertura del link);
  - nota piccola `text-muted-foreground`: `Si apre nel browser: carta o PayPal.`

## 3. Bottone quadrato nella barra laterale (`frontend/src/components/Layout.tsx`)
Nuovo componente `frontend/src/components/shell/SupportRailButton.tsx`, inserito nella `nav` desktop tra
`<div className="flex-1" />` e `NavItem JOBS`. Niente sul telefono (barra in basso invariata).
- Dati: `useQuery(['support-prompt'], GET)`, `staleTime` 1 ora, `refetchOnWindowFocus: true`. Se `visible`
  è false o la query fallisce → non renderizza nulla. Non nascondere durante i job.
- Aspetto: 36×36 (`size-9`), `rounded-[9px]` come le icone della barra, blu, cuore 18px pieno. Entrata con
  piccola animazione scale/opacity (0.4→1, 500ms), niente con `prefers-reduced-motion`.
- Tooltip a destra, due righe: `Clic per donare` / `Clic a lungo per nascondere` (usa il tooltip già usato da
  `IconButton`/`NavItem`, `side="right"`). `aria-label="Supporta RT. Clic per donare, clic a lungo per nascondere"`.
- Interazione con pointer events (`setPointerCapture`, `touch-action: none`, `user-select: none`, niente menu
  contestuale):
  - **Clic breve** (rilascio entro 350 ms): `POST opened`, `navigate('/impostazioni/supporta')`, il bottone
    sparisce subito (aggiorna la cache della query a `visible: false`).
  - **Pressione lunga** (`HOLD_MS = 900`): durante la pressione il bottone scala a 0.94 e un alone bianco
    semitrasparente (radial-gradient, ~38% bianco) cresce dal centro da `scale(0)` a `scale(1.5)` in 900 ms
    lineari. Se rilasci prima o esci col puntatore: l'alone si ritira (200 ms) e non succede niente.
    A riempimento completo: `POST hidden`, il bottone diventa invisibile e parte la **frammentazione**.
  - Tastiera: `Invio` = clic breve; `Spazio` tenuto premuto 900 ms = nascondi (rilascio prima = annulla).
- **Frammentazione** (vetro che si rompe e cade): overlay `position: fixed; inset: 0; pointer-events: none;
  z-index: 60` creato in un portal solo per l'animazione e rimosso alla fine. Dividi il quadrato in una griglia
  4×4 con vertici interni spostati a caso (±28% della cella), ogni cella in 2 triangoli (32 frammenti). Ogni
  frammento è un `div` blu 36×36 posizionato sul bottone, con `clip-path: polygon(...)` del suo triangolo e
  `transform-origin` nel suo baricentro. Fisica in `requestAnimationFrame`: velocità iniziale verso l'esterno
  dal centro (`vx = (cx-0.5)*(1.2..2.8)`, `vy = -(0.6..2.0)*(1-cy*0.6)` px/frame), gravità 0.32 px/frame²,
  rotazione casuale ±7°/frame, rimbalzo smorzato (×-0.25) sul fondo della barra laterale (o della finestra),
  poi dopo ~650 ms dissolvenza in ~550 ms e rimozione. Con `prefers-reduced-motion`: solo dissolvenza 200 ms.
  Logica geometrica in una funzione pura esportata (`shatterPieces(n, jitter, rand)`) per i test.
- Test Vitest `SupportRailButton.test.tsx` (fake timers): non compare con `visible:false`; clic breve → POST
  `opened` e navigazione a `/impostazioni/supporta`; pressione 900 ms → POST `hidden` e bottone sparito;
  rilascio a 500 ms → nessuna POST; `shatterPieces(4, .28)` dà 32 triangoli con vertici in [0,1].
- Test della pagina: il bottone "Dona con Ko-fi" ha `href` dell'URL e `target="_blank"` e il clic fa POST
  `donated`. Aggiorna `routes/settings.test.tsx` per il NavLink interno (oggi controlla href esterno e `_blank`).

## 4. Changelog
Nella sezione più in alto di `CHANGELOG.md`, in "Novità":
`- **Supporta RT**: in fondo alle Impostazioni c'è la pagina per sostenere RT con una donazione su Ko-fi (si apre nel browser). Ogni tanto compare anche un quadratino blu col cuore nella barra laterale: un clic porta alla pagina, tenendolo premuto si nasconde.`
Esegui `pytest tests/test_changelog.py tests/test_support_prompt.py tests/test_donazioni.py` e
`npx vitest run` sui file toccati, `npx tsc --noEmit`.
