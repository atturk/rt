# Piano agy: icona di RT nella barra dei menu di macOS (P18)

Base: main (104f9d1). Prima di tutto: `git pull` di questo branch. Solo codice e test unitari, niente Playwright.
Wireframe: tavola «Barra dei menu di macOS» in https://claude.ai/artifact/MSSWwtvcprkVENUsUYiCMr (tutto il necessario è qui sotto).

## Problema

Dopo la X della finestra, api e worker restano attivi (LaunchAgent `com.atturk.rt.api` / `.worker`, RunAtLoad+KeepAlive)
ma l'utente non vede niente: non sa che RT lavora, non può uscire davvero e i servizi ripartono a ogni accesso.
Il processo della finestra (`rt/window.py`) termina quando `webview.start` ritorna, quindi l'icona non può vivere lì.

## Soluzione

Un piccolo processo separato, solo macOS: `rt/menubar.py`, lanciato da un terzo LaunchAgent `com.atturk.rt.menubar`
gestito da `rt/services/service_manager.py` insieme agli altri due (install/start/stop/uninstall), con `LSUIElement`
equivalente (`NSApplicationActivationPolicyAccessory`: niente icona nel Dock).

1. **NSStatusItem** (pyobjc AppKit, già nel bundle): icona monocromatica *template* 16 pt (nuovo asset
   `rt/assets/menubar/rt-template.png` + `@2x`, ricavata dal logo, nero su trasparente, `setTemplate_(True)`), così segue chiaro/scuro.
   Clic → **menu** (non pannello):
   - «Apri RT» (prima voce, grassetto): `open -b <bundle id dell'app>` (stesso metodo con cui oggi si riapre l'app; vedi `_activate_existing`);
   - separatore;
   - stato: «Nessuna elaborazione in corso» oppure, per ogni job attivo (max 3): «<titolo lezione> — <fase> <percentuale>%» (voci disabilitate);
     se più di 3, «e altre N…»;
   - separatore;
   - «Avvia RT all'accesso» con spunta (vedi §3);
   - «Esci da RT»: se ci sono job attivi chiede conferma con lo stesso testo di `active_jobs_quit_message`; poi `stop_background(base_url)`
     (ferma api e worker con `service_manager.stop()`), chiude l'eventuale finestra aperta (PID in `_pid_path()`) e infine termina se stesso
     (`service_manager` deve fermare anche il LaunchAgent del menubar senza che KeepAlive lo riavvii: `bootout`).
2. **Indicatore di attività**: polling di `GET /api/v1/jobs?state=active` (o l'endpoint che usa già `_fetch_active_jobs`) ogni 3 s con
   job attivi, ogni 15 s senza; autenticazione come `_fetch_active_jobs`. Con almeno un job attivo l'icona mostra un puntino
   (seconda immagine template con punto) oppure, se più semplice, `button.setAppearsDisabled_` invertito: inattivo = opacità 60%.
   Se l'api non risponde, voce di stato «RT si sta avviando…» e nessun errore a schermo.
3. **Avvio all'accesso**: nuova impostazione `ui.start_at_login: bool = True` (config + `PUT /settings/preferences` + toggle in Impostazioni ›
   Generale, testo «Avvia RT all'accesso: le elaborazioni ripartono da sole dopo il riavvio del Mac»). Con `False`, i plist hanno
   `RunAtLoad=false` (riscritti da `service_manager`); la voce del menu e il toggle sono la stessa impostazione.
4. **Stesse azioni nel menu del Dock** dell'app quando la finestra è aperta (applicationDockMenu_ nel delegate pywebview, se facile;
   altrimenti salta questo punto e segnalalo nel commit).
5. **Worker in pausa più leggero**: in `rt/services/worker.py` il ciclo senza job fa `poll_interval=1.0` s. Con coda vuota da più di 60 s
   portare l'attesa a 5 s (back-off 1→2→5 s), tornando a 1 s appena arriva un job (o subito se si usa già un evento/notify). Test.
6. **Windows**: fuori da questo piano (serve una libreria tray non inclusa). Lasciare `rt/menubar.py` senza effetti su Windows.

## Test

- `service_manager`: il plist del menubar viene scritto/caricato/fermato insieme agli altri; `start_at_login=False` → `RunAtLoad=false` in tutti.
- Logica del menu separata dalla UI (funzione pura `menu_model(jobs) -> list[voce]`): nessun job, 1 job, 5 job; testo del job con fase e percentuale.
- «Esci»: chiama `stop_background`, poi termina; con job attivi chiede conferma (mock).
- Worker: back-off dell'attesa a coda vuota e ritorno a 1 s.

## Sovrapposizioni
Tocca `rt/window.py` solo se fai il punto 4, `rt/services/service_manager.py`, `rt/core/config.py` (UiConfig) e Impostazioni › Generale
(`frontend/src/components/settings/general.tsx`, che tocca anche il piano ONNX in un'altra sezione: conflitti piccoli).
