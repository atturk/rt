# Piano 4.3.10b3: RT senza altri programmi (motore + download modelli)

Base: claude/rt-4.3.10-beta (2d329f89). Documento completo: https://claude.ai/artifact/TzaD34f9iE6oVNdCKnbjnE
Decisione di Attilio (2026-11-27): b3 = motore + download; spostamento dati in Application Support = b4 separata.

## 1. Parakeet ONNX predefinito (piccolo)
- rt/core/config.py `default_engine()`: per installazioni nuove "parakeet" su Mac e Windows (se onnx_stt.available()). Chi ha già `transcription.engine` salvato in config lo tiene.
- rt/services/settings_service.py: `recommended` = "parakeet" ovunque; macparakeet resta scelta avanzata ("se installato con Homebrew").
- Configurazione guidata e Impostazioni: testi che non chiedono più Homebrew. install.sh invariato (strada sviluppatori).

## 2. Pannello «Componenti di RT» (Impostazioni → Generali)
- Righe: «Modello di trascrizione — necessario per trascrivere l'audio» (Parakeet ONNX + VAD, ~670 MB) e «Browser per le catture — facoltativo» (Chromium Playwright).
- Per ognuno: stato (non scaricato / in download / pronto / errore), dimensione, barra con %, tempo stimato, Pausa/Riprendi, Riprova, Elimina.
- API: GET /api/v1/components (stato+progresso), POST /api/v1/components/{id}/download|cancel, DELETE. Il download gira in un thread del worker o dell'API, un solo download per componente alla volta (lock su file in <data>/models/.lock), riusa `_download_resumable` di rt/core/onnx_stt.py e scrive il progresso in un file json letto dalla GET.
- Chromium: ensure_capture_browser (rt/desktop.py) non parte più in silenzio; usa lo stesso meccanismo e scrive lo stato (log resta browser-install.log).

## 3. Download avviato dalla configurazione guidata
- Al passo Modelli (o alla fine della guida) parte il download del modello di trascrizione in background, con la stessa barra.
- Se RT si chiude, al riavvio riprende da solo (file .part già supportati).

## 4. Nuova lezione con audio e modello non pronto
- Invece di un errore o di un lavoro bloccato senza info: riga nel dialogo «Il modello di trascrizione si sta scaricando (42%, circa 6 min): la lezione partirà appena è pronto.» e il job attende il modello (stato visibile nella card del job con la %).
- Il modello va caricato una sola volta per processo (bug visto nel collaudo: caricato due volte).

## 5. Riga «Presentazioni» in Impostazioni
- «Presentazioni .pptx convertite con: LibreOffice / PowerPoint / Keynote / Quick Look (qualità ridotta) / nessuno (solo testo)», da available_slide_methods(), con suggerimento su cosa installare per migliorare. Nessun download automatico.

## Fuori dalla b3
- Mirror del modello sulla release GitHub + download parallelo: prima misurare la velocità HF vs GitHub sul Pro.
- Spostamento dati in ~/Library/Application Support/RT e %LOCALAPPDATA%\RT: b4.

## Regole
- agy scrive solo codice; verifiche e Playwright le fa Claude.
- Test e script non devono mai toccare la ~/.rt vera (usare RT_DATA_DIR temporanea).
