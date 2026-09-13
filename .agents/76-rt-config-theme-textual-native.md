# Task 76 — `rt config --theme`: collega il sistema di temi nativo di Textual (rimasto in sospeso dal Task 60)

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Il Task 60 originale (tema chiaro/scuro fatto a mano per il vecchio motore `rich`+`questionary`,
per risolvere l'illeggibilità dei colori di default su terminale a sfondo chiaro) era stato
eliminato quando si è deciso di migrare le 4 schermate interattive a Textual (Task 64-68), perché
Textual ha un sistema di temi nativo che avrebbe risolto lo stesso problema senza doverlo
costruire a mano. Il problema: nei Task 64-68 è stato esplicitamente detto di NON introdurre temi
personalizzati ("resta lo stile di default Textual"), e nessun task successivo ha mai collegato
un modo per l'utente di scegliere/persistere un tema — la richiesta originale dell'utente
("`rt config --theme`") non è mai stata implementata per davvero.

**Verificato nell'ambiente reale**: Textual (versione installata, 8.2.8) espone
`App.theme` (property reattiva, stringa), `App.available_themes` (dict di temi pronti:
`textual-dark`, `textual-light`, `nord`, `gruvbox`, `dracula`, `solarized-dark`,
`solarized-light`, `catppuccin-latte`/`-mocha`/`-frappe`/`-macchiato`, `monokai`, `tokyo-night`,
`atom-one-dark`/`-light`, `rose-pine*`, `ansi-dark`/`-light`, `flexoki`), default
`"textual-dark"`. Tutte e 4 le `App` Textual del progetto (`OutlineReviewApp`, `IssueReviewApp`,
`ConfigurePhaseRolesApp`, `StaleRecallApp`) ereditano già questo sistema gratuitamente, semplicemente
non impostano mai un tema esplicito né lo rendono persistente/configurabile.

## Comportamento richiesto

L'utente vuole scegliere tra scuro e chiaro (il problema originale era la leggibilità su
terminale a sfondo chiaro) — non serve esporre tutti i ~20 temi di Textual, ma usare quel sistema
sotto al cofano invece di costruirne uno a mano.

1. Aggiungi un campo persistente in `RTConfig` (`rt/core/config.py`), es. una sezione
   `ui: UiConfig` con `theme: Literal["dark", "light"] = "dark"` (default "dark", coerente col
   default nativo di Textual `"textual-dark"`, così chi non ha mai scelto nulla non vede nessun
   cambiamento). Salvato in `general.yaml` sotto `ui: {theme: dark}`.
2. Mappa la scelta utente al nome di tema Textual effettivo: `"dark" -> "textual-dark"`,
   `"light" -> "textual-light"` (o un'alternativa più leggibile se in fase di verifica manuale
   `textual-light` risultasse poco curata — verifica visivamente prima di decidere, in tal caso
   `solarized-light` o `atom-one-light` sono alternative valide, documenta la scelta finale nel
   riepilogo).
3. In OGNUNA delle 4 `App` (`OutlineReviewApp` in `outline_review.py`, `IssueReviewApp` in
   `issue_review.py`, `ConfigurePhaseRolesApp`/`PhaseRolesCarouselApp` in `configure.py`,
   `StaleRecallApp` in `recall_session.py`), leggi la preferenza salvata all'avvio (es. in
   `__init__` o `on_mount`) e imposta `self.theme = <nome_tema_textual>` di conseguenza — verifica
   se ha senso centralizzare questa lettura/applicazione in un piccolo helper condiviso (es.
   `rt/core/ui_theme.py::apply_saved_theme(app: App) -> None`) invece di duplicare la stessa
   logica in 4 punti.
4. Nuovo flag `rt config --theme`: aggiungi al gruppo mutuamente esclusivo esistente in
   `configure_config_parser` (stesso pattern di `--models`/`--telegram`/`--topics`), collegato a
   una nuova funzione `run_theme_selection()` che chiede:
   ```
   Il tuo terminale ha uno sfondo scuro o chiaro?
   - 🌑 Scuro
   - 🌕 Chiaro
   ```
   (con `questionary.select`, coerente con lo stile del resto di `rt config`) e salva la scelta in
   `general.yaml`.
5. **Prima esecuzione**: se `ui.theme` non è ancora presente in `general.yaml` (wizard mai
   completato con una scelta esplicita), NON è necessario forzare la domanda durante `rt config`
   completo (il default "dark" è già quello attuale, nessuna regressione per chi non sceglie
   nulla) — ma valuta se ha senso comunque proporla una volta durante il wizard completo
   (`run_config_wizard`), subito prima di entrare nella prima schermata Textual del wizard
   (il carosello ruoli-fase), così chi la vede per la prima volta su sfondo chiaro non debba
   scoprire il problema da solo e poi cercare `--theme` a parte. Se decidi di aggiungerla lì,
   falla comparire UNA sola volta (se `ui.theme` è già presente, non richiederla di nuovo nel
   wizard completo — resta comunque sempre riapribile con `rt config --theme`).

## Test

- Test che verifica che `RTConfig`/`general.yaml` supporti il nuovo campo `ui.theme` con default
  `"dark"` quando assente.
- Test che verifica che `rt config --theme` salvi correttamente la scelta (mock di
  `questionary.select`).
- Test che verifica che ciascuna delle 4 `App` applichi il tema corretto in base al valore salvato
  (es. istanzia l'app con una config che ha `ui.theme = "light"` e verifica `app.theme ==
  "textual-light"` — o il nome scelto al punto 2 — dopo l'inizializzazione/mount).
- Test che verifica che, con `ui.theme` assente, il comportamento resti quello di default
  (`"textual-dark"`, nessuna differenza rispetto a oggi).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Usa ESCLUSIVAMENTE il sistema di temi nativo di Textual
(`App.theme`/`available_themes`) — non introdurre CSS custom, palette di colori scritte a mano, o
wrapper propri: è esattamente il lavoro che la migrazione a Textual doveva evitarci di fare.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. `rt config --theme`, scegli "Chiaro", poi apri una qualunque delle 4 schermate (es. `rt config`
   per il carosello, o `rt review` per la card di science review) su un terminale a sfondo chiaro
   e verifica che i colori siano leggibili. Ripeti con "Scuro" per verificare che non regredisca.
