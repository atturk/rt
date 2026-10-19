# Piano 1 · Aggiornamenti nella finestra dell'app, download separato dall'installazione, beta

## Com'è oggi

- `rt/core/app_update.py` controlla l'ultima release **stabile** (`/releases/latest`), e `start()`
  scarica e installa in un colpo solo, in un thread del processo API.
- Lo stato (`STATE`) vive in memoria: se RT si chiude durante il download il file `.part` si perde,
  e non esiste uno stato "scaricato, da installare".
- L'unica interfaccia è `UpdateSection` (`frontend/src/components/settings/update.tsx`), dentro
  Impostazioni › Info. La voce di menu "Controlla aggiornamenti…" (`rt/window.py`) apre quella pagina.
- Le beta non si installano mai da qui (`run_cli` con `--beta` rimanda alla pagina delle release).

## Cosa deve succedere

Nell'app (finestra pywebview, Mac e Windows):

1. Quando c'è un aggiornamento, si apre un **popup dell'app**: una seconda finestra piccola della
   finestra RT, non un dialogo dentro la pagina. Mostra versione e dimensione, con un pulsante
   Scarica. La finestra principale resta usabile.
2. Durante il download il popup mostra l'avanzamento. Si può chiudere: il download continua nel
   processo API.
3. A download finito e verificato, il popup (riaperto se era chiuso) propone **Installa e riavvia**.
   L'utente può chiuderlo e rimandare.
4. Il file verificato resta su disco. Al prossimo avvio dell'app, o con "Controlla aggiornamenti…",
   se il file della versione più recente c'è già il popup compare subito con Installa e riavvia,
   senza riscaricare.
5. La sezione Aggiornamenti in Impostazioni › Info resta, mostra lo stesso stato e ha gli stessi
   pulsanti (Scarica, Installa e riavvia, Controlla ora). Serve anche a chi usa RT nel browser.

Canale beta: chi è sul canale beta riceve anche le beta dall'app (decisione di Attilio del 2026-10-19,
che sostituisce "solo stabili").

## Backend: `rt/core/app_update.py`

### Canale

- Nuova funzione `effective_channel(current)`: il valore di `get_update_channel()` se il file del
  canale esiste; altrimenti `beta` se `is_prerelease(current)`, altrimenti `stable`. Chi installa
  una beta dal DMG resta così sulle beta senza toccare nulla.
- `check()`: con canale `stable` resta com'è (`/releases/latest`). Con canale `beta` legge
  `/releases?per_page=30` e sceglie la release più alta (con `parse_version`) fra quelle non draft
  che hanno l'installer per questo sistema e `SHA256SUMS`, prerelease comprese. Poi la passa a
  `evaluate()`, che quindi non deve più scartare le prerelease quando il canale è beta: aggiungi un
  parametro `allow_prerelease: bool = False`.
- `UpdateCheck` guadagna `channel: str` e `prerelease: bool` (la versione trovata è una beta).
- `run_cli(wants_beta=True)` imposta il canale beta (`set_update_channel`) e aggiorna come per le
  stabili, invece di rimandare alla pagina delle release.

### Download che sopravvive

- `download()` scrive in `updates/<asset>.part`, poi `os.replace` su `updates/<asset>` (come oggi),
  e in più scrive `updates/ready.json` con `{"version", "asset_name", "sha256", "size"}`.
- Nuova `ready_file(info) -> Optional[str]`: il percorso dell'installer se `ready.json` indica la
  stessa `version` e lo stesso `asset_name` di `info`, e il file esiste con la stessa dimensione.
  Altrimenti `None`.
- Nuova `cleanup(keep: Optional[str])`: toglie da `updates/` gli installer, i `.part` e `ready.json`
  che non riguardano `keep`. Si chiama dopo ogni `check()` riuscito (tiene solo l'asset della
  versione trovata), e all'avvio con `--after-update` (non tiene niente).
- Il download riprende da capo se interrotto (niente range HTTP: non serve).

### Stato e fasi

- `_State.phase`: `idle | downloading | ready | installing | error`.
- `as_dict()` / l'API espongono anche `ready: bool`, vero quando `ready_file()` trova il file (anche
  dopo un riavvio, quando `phase` è di nuovo `idle`).
- `start()` diventa `start_download(info)`: solo download, e alla fine `phase = "ready"`.
- Nuova `start_install(info)`: verifica di nuovo lo SHA256 del file su disco contro `ready.json` (un
  file manomesso o troncato non si installa: errore e `cleanup`), poi `phase = "installing"` e
  `install(path)`.

## API: `rt/api/routers/system.py`

- `GET /system/update`: come oggi, più `ready`, `channel` e `prerelease`.
- `POST /system/update`: avvia **solo il download**. Se il file è già pronto risponde subito con
  `ready: true`.
- Nuovo `POST /system/update/install`: 409 `not_ready` se il file non c'è, altrimenti installa.
- Rigenera `frontend/src/api/schema.d.ts` e l'openapi come fanno gli altri piani.

## Popup nell'app

### Pagina

- Nuova rotta `app/aggiornamento` in `frontend/src/routes/index.tsx`, `handle: bare`, senza barra né
  menu: è il contenuto del popup.
- Nuovo componente `frontend/src/components/settings/UpdatePopup.tsx` che usa le stesse query e
  mutazioni di `UpdateSection`. Conviene estrarle in un hook `useAppUpdate()` dentro `update.tsx` e
  usarlo in tutti e due.
- Contenuto minimo, senza testi di spiegazione:
  - riga 1: `RT <versione>`, con un badge "beta" se `prerelease`, e il link "novità";
  - stato:
    - disponibile → pulsante Scarica (con la dimensione);
    - in download → barra di avanzamento con percentuale;
    - pronto → pulsante **Installa e riavvia**;
    - errore → l'`Alert` con il messaggio e Riprova.
  - Niente "Più tardi": chiudere la finestra è rimandare.
- Durante `installing` mostra "Installo RT <versione>…": RT si chiude da solo.

### Finestra (`rt/window.py`)

- `DesktopApi.apri_aggiornamento()`: se il popup non esiste lo crea con
  `webview.create_window("Aggiornamento di RT", base_url + "/app/aggiornamento", width=420,
  height=240, resizable=False, on_top=True)`. Se esiste già, lo porta davanti (`show()`), senza
  aprirne due. Alla chiusura (`events.closed`) azzera il riferimento.
- La finestra condivide lo stesso `storage_path`, quindi la sessione: niente login. Verificalo nel
  test di fumo.
- Menu "Controlla aggiornamenti…": chiama `apri_aggiornamento()` (oggi carica `INFO_PATH`). Il popup,
  all'apertura, fa il controllo con `refresh: true`.
- Nel popup, "novità" deve aprire il browser esterno (`OPEN_EXTERNAL_LINKS_IN_BROWSER` già lo fa
  per `target="_blank"`).

### Quando si apre da solo

- Nella finestra principale, un hook `useUpdatePopup()` montato nel `Layout`, attivo solo con
  `isAppWindow()` (`frontend/src/lib/zoom.ts`), legge `GET /system/update` all'avvio e poi con la
  cadenza della query (il backend ha già la cache di 6 ore). Apre il popup
  (`window.pywebview.api.apri_aggiornamento()`) quando:
  - `ready` è vero (file già scaricato), oppure
  - `available` è vero e la versione non è già stata mostrata in questa sessione della finestra
    (`sessionStorage`).
- Quando un download avviato dal popup finisce mentre il popup è chiuso, la finestra principale
  vede `phase === "ready"` e lo riapre.
- Fuori dall'app (browser) l'hook non fa niente: resta la sezione in Impostazioni.

## `UpdateSection`

- Pulsanti come il popup: Scarica → (avanzamento) → Installa e riavvia. Il testo "RT si aggiorna solo
  alle versioni stabili…" diventa la descrizione del canale: "Canale: stabile" oppure
  "Canale: beta".
- Aggiungi uno `Switch` "Beta" che chiama un nuovo `PUT /system/update/channel` con body
  `{channel}`, che usa `set_update_channel`. Senza altro testo.

## Test

- `tests/test_app_update.py`:
  - `effective_channel` senza file, con file, con una versione beta;
  - `check()` sul canale beta sceglie la prerelease più alta con gli asset e scarta quelle senza
    SHA256SUMS;
  - `download()` scrive `ready.json`, e `ready_file()` lo ritrova;
  - con un file troncato `ready_file()` dà `None`;
  - `start_install()` rifiuta un file con hash diverso;
  - `cleanup()` tiene solo l'asset indicato.
- API: `POST /system/update` non installa, `POST /system/update/install` dà 409 senza file.
- Vitest:
  - `UpdatePopup` nei quattro stati;
  - `useUpdatePopup` chiama `apri_aggiornamento` con `ready` e una sola volta per versione con
    `available`;
  - `UpdateSection` con lo switch del canale.
- `tests/test_desktop_window.py`: `apri_aggiornamento` crea una sola finestra (finto `webview`), e il
  menu chiama quella funzione.

Prova a mano (Attilio): con una beta installata e il canale beta, all'apertura compare il popup;
chiudendolo durante il download e riaprendo RT compare Installa e riavvia senza riscaricare.

## Changelog

- Nell'app gli aggiornamenti arrivano in un popup: si scaricano mentre usi RT e si installano quando
  vuoi con Installa e riavvia. Il file scaricato resta anche se chiudi RT.
- Chi è sul canale beta riceve anche le beta dall'app.
