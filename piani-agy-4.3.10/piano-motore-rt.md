# Piano agy (4.3.10b8): un solo motore locale «RT» + server personalizzato

Branch: `agy/4.3.10-motore-rt`, dalla beta DOPO l'uscita della b7 (LibreOffice). Solo codice e test automatici;
le verifiche le fa Claude. Test sempre con RT_DATA_DIR/HOME/USERPROFILE finti.

Decisione di Attilio (28/11, 10:16-10:20): niente più scelta tra macparakeet e Parakeet ONNX. Il motore locale si
chiama «RT» ed è consigliato; RT sceglie da solo l'implementazione per il sistema. Resta il server personalizzato.

## 1. Configurazione (non si rompe niente)
- I valori interni di `transcription.engine` restano (`macparakeet`, `parakeet`, `custom`) per compatibilità con
  config esistenti, job, worker e Docker. Nuovo valore logico `local` = «RT».
- `effective_engine()`: `local` → `macparakeet` su macOS Apple Silicon, `parakeet` altrove (Windows, Linux, Docker).
  Anche `macparakeet` e `parakeet` già salvati si trattano come `local` (stessa risoluzione per sistema): chi sul Mac
  aveva scelto Parakeet ONNX passa a macparakeet. Eccezione: variabile `RT_FORCE_STT_IMPL=parakeet|macparakeet`
  solo per test/diagnosi (non in UI).
- `default_engine()` = `local`; init_data_dir scrive `local`; config.example `engine: local` con commento.
- Al salvataggio dalle Impostazioni si scrive `local` o `custom`.
- API settings: `engine` può valere `local|custom` (accettare ancora i vecchi valori in ingresso, convertendoli);
  `effective_engine` continua a dire l'implementazione reale (serve a Componenti e diagnosi). Rigenerare openapi e
  schema.d.ts.

## 2. Impostazioni → Trascrizione (general.tsx) e configurazione guidata (wizard.tsx)
- Due opzioni:
  - **«RT · consigliato»** — descrizione: «Basato su Parakeet di NVIDIA, adattato da RT per questo computer.
    Funziona senza internet.» Sotto, una riga piccola con lo stato del componente (pronto / da scaricare ~500 MB su
    Mac, ~900 MB su Windows / in download con %).
  - **«Server personalizzato»** — come oggi (URL, modello, chiave).
- Togliere le etichette «macparakeet», «Parakeet ONNX», i testi su Apple Silicon/Homebrew e il link «Usa un altro
  motore» della guida diventa «Usa un server personalizzato».
- NewLessonDialog: «Il motore di trascrizione di RT» al posto di «Il motore/Il modello di trascrizione».

## 3. Componenti
- Mostrare solo il componente che serve al sistema: Mac → «Motore di trascrizione RT» (id macparakeet); Windows →
  «Motore di trascrizione RT» (id transcription). L'altro non compare (resta nel codice; se è già scaricato, mostrarlo
  solo con «Elimina» per liberare spazio, con nota «non più usato»).
- Detail: Mac «Parakeet v3 di NVIDIA tramite macparakeet (Neural Engine)»; Windows «Parakeet v3 di NVIDIA, ONNX
  int8 adattato da RT».

## 4. Riconoscimenti (pagina Informazioni)
- Sezione «Riconoscimenti» (o aggiungere a quella esistente): «La trascrizione usa Parakeet TDT 0.6B v3 di NVIDIA
  (licenza CC-BY-4.0), adattato da RT (quantizzazione int8). Su Mac usa macparakeet (GPL-3.0) e FluidAudio.
  NVIDIA non è affiliata a RT e non approva questo prodotto.» con i link alle pagine originali.
- Stessa nota in docs/guida (privacy o trascrizione) e nelle note della release stt-models.

## 5. Testi e guida
- grep «macparakeet», «Parakeet ONNX» nei testi visibili (frontend, human_error, doctor_service, docs/guida):
  sostituire con «il motore di trascrizione di RT» dove l'utente li legge. Log e codice interno restano.

## Test (agy)
- effective_engine per sistema con `local`, `macparakeet`, `parakeet`; RT_FORCE_STT_IMPL.
- Migrazione: config vecchia con `parakeet` su Mac → effettivo macparakeet; salvataggio scrive `local`.
- API: PUT con vecchi valori accettato e convertito.
- UI: due opzioni, testi, componente unico per sistema, riconoscimenti.
