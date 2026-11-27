# Piano 4.3.10b4 (parte 2): macparakeet senza Homebrew + ritocchi UI dei componenti

Base: ramo con la parte 1 (Application Support) già rivista. Decisioni di Attilio 2026-11-27:
Mac = macparakeet (consigliato) scaricato da RT, senza Homebrew; Windows = solo Parakeet ONNX
(da sistemare a parte); motori mostrati in base al sistema.

## 1. Componente «Motore di trascrizione per Mac» (solo macOS)
- Sorgente: release ufficiale GitHub moona3k/macparakeet, tag `cli-v5.1.0` (eseguibile arm64 unico,
  ~61 MB, firmato Developer ID + notarizzato, ffmpeg incluso, solo framework di sistema).
  URL dell'asset e SHA256 fissati in una costante (Claude li compila dopo la verifica sul Pro);
  il download si rifiuta se lo SHA256 non coincide.
- Destinazione: `<cartella dati>/bin/macparakeet-cli` (download in `.part`, poi chmod 755 e
  os.replace). Niente attributo quarantine (scarica Python, non il browser).
- Modello: subito dopo il binario, `macparakeet-cli models download parakeet-v3` (finisce in
  ~/Library/Application Support/FluidAudio/Models, ~480 MB). Avanzamento: dall'output se c'è una
  percentuale, altrimenti dalla crescita della cartella del modello rispetto a 480 MB.
- In rt/core/components.py: nuovo id `macparakeet` con gli stessi stati/azioni (Scarica, Pausa,
  Riprendi, Riprova, Elimina; Elimina toglie binario e cartella del modello parakeet-v3).
  Lock e components.json come gli altri. «required» = True sul Mac quando il motore effettivo è
  macparakeet.
- `find_macparakeet_binary()` (rt/pipeline/setup.py): prima `<dati>/bin/macparakeet-cli`, poi
  PATH/Homebrew come oggi. Doctor e messaggi d'errore: niente più «brew install», ma
  «Scarica il motore da Impostazioni → Componenti».
- Se il binario manca quando parte una lezione con audio: il job lo scarica (con % nella scheda
  del lavoro) come fa oggi per il modello ONNX, invece di fallire.

## 2. Motore per sistema
- `default_engine()`: macOS → `macparakeet`; Windows/Linux → `parakeet`. config.example resta
  com'è ma init_data_dir scrive `macparakeet` su macOS (estendere _fallback_engine).
- `effective_engine()`: con `macparakeet` scelto e binario assente NON ricadere più in silenzio su
  ONNX: il job scarica il componente macparakeet (punto 1). Ricaduta su ONNX solo se il Mac non è
  Apple Silicon (macparakeet non gira).
- Impostazioni → Trascrizione: Mac = «macparakeet · consigliato», «Parakeet ONNX», «Server
  OpenAI-compatible»; Windows = «Parakeet ONNX · consigliato», «Server». Testi senza Homebrew.
- Pannello Componenti: sul Mac mostra «Motore di trascrizione» (macparakeet) e il modello ONNX
  solo se il motore scelto è Parakeet ONNX; su Windows solo il modello ONNX.

## 3. Avviso quando il motore/modello non c'è
- Pallino come per gli aggiornamenti (UpdateNoticeDot / useUpdateNotice) sull'ingranaggio e su
  «Lavorazione delle lezioni» quando il componente necessario al motore effettivo non è pronto
  né in download. Il clic porta a /impostazioni/lavorazione#componenti.
- Se l'utente lo ignora, il download parte da solo alla prima lezione con audio.

## 4. Configurazione guidata, passo Modelli
- Scheda «Trascrizione» con il download del componente consigliato già avviato (barra, %, tempo)
  e un link piccolo «Usa un altro motore» che apre la scelta (sul Mac anche Parakeet ONNX; ovunque
  il server). Sostituisce l'attuale WizardTranscriptionDownload.

## 5. Browser per PDF e catture
- Download con `playwright install chromium --only-shell` (headless shell, molto più leggero).
  launch_capture_browser usa già headless senza executable_path; verificare che
  find_capture_browser_executable trovi la shell.
- Etichetta «Browser per PDF e catture», descrizione «serve per esportare in PDF e per le
  visualizzazioni» (non più «facoltativo»: il PDF usa _render_pdf in rt/api/routers/lessons.py).
- Se c'è già il Chromium completo, nessuna azione (funziona); Elimina + Scarica passa alla shell.

## Test (agy scrive i test unitari; le verifiche reali le fa Claude)
- Download macparakeet simulato (server finto): SHA256 sbagliato → errore; ok → binario in
  <dati>/bin eseguibile; modello con avanzamento; Elimina.
- default_engine per piattaforma; effective_engine non ricade più su ONNX su Apple Silicon.
- UI: opzioni motore per sistema; pallino; scheda nella guida; etichetta browser.

## Regole
- agy scrive solo codice; niente esecuzione del vero macparakeet-cli né download reali nei test.
- Test e script non devono mai toccare la ~/.rt vera né Application Support veri (HOME finta).
