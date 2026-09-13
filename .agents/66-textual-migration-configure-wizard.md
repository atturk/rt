# Task 66 — Migra il carosello ruoli-fase di `rt config` (`configure.py`) da `rich.Live` a Textual

Fa parte della migrazione a Textual iniziata col Task 64 (pilota su `outline_review.py`). **Esegui
questo task solo dopo che i Task 64 e 65 sono stati completati e verificati** — è il file più
grande e delicato dei 4 (1968 righe totali, il cuore di `rt config`), va affrontato per ultimo tra
le 4 schermate, quando il pattern Textual è già consolidato e collaudato sui casi più semplici. Nel
progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano
preliminare.

## Contesto

Leggi prima `.agents/64-textual-migration-pilot-outline-review.md` per il contesto generale della
migrazione (motivazione, perimetro, cosa NON migrare).

Il carosello (`rich.Live` a riga 963 di `rt/pipeline/configure.py`) gestisce l'assegnazione dei
ruoli primario/fallback per ciascuna fase (introdotto dal Task 53): naviga tra "card" (una per
gruppo di job/fase, LEFT/RIGHT per cambiarla), ciascuna con un menu verticale di opzioni (UP/DOWN +
ENTER), e una schermata di conferma finale con 3 opzioni (Conferma e applica / Modifica una fase /
Annulla). Alcune opzioni del menu (`REMOVE_LABEL`, `NEW_PROFILE`) fanno `live.stop()`, aprono un
sotto-flusso (`questionary.select(...)` per la rimozione, oppure l'intera funzione
`_create_new_model_profile(...)` per un nuovo profilo — quest'ultima è una funzione corposa con
propri prompt `questionary` per provider/modello/chiave API/pricing), poi `console.clear();
live.start()` per riprendere il carosello (righe 1150-1176, 1178+).

**Importante — `_create_new_model_profile` resta su `questionary`, NON va riscritta in Textual**:
è un flusso lineare di prompt (testo/scelta), esattamente il tipo di interazione per cui
`questionary` va bene e non ha mai causato i bug che motivano questa migrazione (vedi il task 64,
sezione "perimetro"). Avvolgi la sua chiamata in `App.suspend()` invece di `live.stop()`/
`live.start()`, esattamente come per l'editor esterno del Task 65.

## Modifica

- Sostituisci `with raw_mode() as is_raw: with Live(...) as live: while True: ...` (righe 962-fine
  della funzione, verifica il range esatto leggendo la funzione per intero) con una `App`
  Textual, preservando ESATTAMENTE:
  - Le due "schermate" del carosello: la card per-fase (righe 1063-1176+, menu con UP/DOWN/ENTER,
    LEFT/RIGHT per cambiare fase, `C`/`F` per andare alla conferma, `Q` per uscire) e la schermata
    di conferma finale (righe 965-1062, stesso set di comandi ma 3 opzioni fisse).
  - Tutte le opzioni del menu per-fase: `keep_label` (mantieni configurazione attuale se
    rilevata), `SKIP_LABEL`, i profili esistenti, `NEW_PROFILE`, `REMOVE_LABEL` (condizionale, solo
    se almeno un ruolo è già assegnato) — con lo stesso ordine e la stessa logica condizionale di
    oggi.
  - Il comportamento di `option_indices` (ricorda l'indice selezionato per ciascuna card
    separatamente, così tornare a una card precedente non resetta la posizione del cursore).
  - La barra di stato in alto ("Avanzamento: ...") che mostra tutte le fasi con lo stato ✅/⏳.
- Per `REMOVE_LABEL` e `NEW_PROFILE`: avvolgi il sotto-flusso `questionary`/
  `_create_new_model_profile` in `App.suspend()`, poi aggiorna lo stato interno della `App`
  (`pending_selections`) e lascia che Textual ridisegni — nessuna `console.clear()` manuale.
- Alla conferma finale ("✅ Conferma e applica configurazione"): il salvataggio su disco
  (`_apply_profile_to_job`, `_apply_fallback_to_job`, `_save_model_profiles`,
  `_atomic_write_text`) resta IDENTICO, cambia solo il modo in cui si chiude la `App` prima di
  stampare il messaggio finale e fare `return job_assignments`.

## Test

- Verifica quali test esistenti coprono questo carosello (cerca in `tests/test_configure_wizard.py`
  test relativi al Task 53/al carosello ruoli-fase — probabilmente basati su mock di
  `read_single_key`/`Live`), riscrivili con `App.run_test()`/`pilot.press(...)`.
- Aggiungi/adatta test per: navigazione tra card con LEFT/RIGHT preserva l'indice del cursore per
  ciascuna card; assegnazione di un ruolo tramite un profilo esistente; creazione di un nuovo
  profilo dal carosello (`NEW_PROFILE`) e ritorno con il nuovo profilo assegnato al ruolo corretto,
  senza duplicazione visiva; rimozione di un ruolo assegnato (`REMOVE_LABEL`); la schermata di
  conferma finale con tutte e 3 le opzioni (conferma/modifica una fase/annulla), incluso il
  ritorno a "Modifica una fase" che riporta alla card corretta.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Non toccare `rt/core/keyboard.py` (rimosso solo nel Task 68). Non
toccare `_create_new_model_profile` né gli altri ~49 prompt `questionary` sparsi nel resto del
wizard (fuori perimetro, vedi Task 64). Non introdurre CSS/temi personalizzati in questo task.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale con `rt config --models` su una configurazione con più fasi/job: naviga tra le
   card, assegna un profilo esistente a un ruolo, crea un nuovo profilo da una card, rimuovi
   un'assegnazione, arriva alla schermata di conferma e completa il salvataggio — verifica che non
   ci sia mai duplicazione visiva, in nessuno dei sotto-flussi che oggi fanno `live.stop()`/
   `live.start()`.
