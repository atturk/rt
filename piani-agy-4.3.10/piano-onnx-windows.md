# Piano: Parakeet ONNX affidabile (motore di Windows, riserva sul Mac)

Decisione di Attilio (2026-11-27 19:39Z): Windows usa ONNX, che va sistemato. Prove sul Pro con una
lezione vera di 74:49 (script piani-agy-4.3.10/onnx_finestre_riferimento.py, variante HP6):

| Motore | Tempo | Parole | RAM |
|---|---|---|---|
| macparakeet 5.1.0 | 16,6 s | 7360 | 432 MB |
| ONNX HP6 (questo piano) | 202 s | 7403 | 3,2 GB |
| ONNX di RT oggi (b3) | 139 s | 3709 | 15,5 GB |

## 1. Modello: int8 per canale, solo MatMul, ospitato da noi
- Oggi: int8 di onnx-asr da Hugging Face (perde ~15% delle parole). Nuovo: encoder+decoder quantizzati con
  `onnxruntime.quantization.quantize_dynamic(per_channel=True, op_types_to_quantize=["MatMul"],
  weight_type=QInt8)` dal fp32 di istupakov/parakeet-tdt-0.6b-v3-onnx (~892 MB totali).
- Lo produce e lo carica Claude (asset della release `stt-models-1` su atturk/rt, segnata prerelease e
  non «latest», così l'aggiornamento di RT la ignora: parse_version("stt-models-1") è None), non agy.
  File: encoder-model.q8pc.onnx, decoder_joint-model.q8pc.onnx, vocab.txt, config.json, SHA256SUMS.
  Licenza del modello CC-BY-4.0 (NVIDIA, conversione ONNX istupakov): attribuzione nelle note della release
  e nel pannello Componenti («Parakeet TDT 0.6B v3 di NVIDIA, CC-BY-4.0»).
  agy mette costanti segnaposto; Claude compila URL/dimensioni/SHA256 in revisione. In codice: costanti URL + dimensione + SHA256 per file (encoder, decoder, vocab/config), come per
  macparakeet in components.py. Download con ripresa (Range), verifica SHA256, `.part` + os.replace.
- Nuova cartella `<dati>/models/parakeet-v3-q8pc/` (caricata con onnx_asr.load_model(MODEL_NAME, dir, quantization="q8pc")); il vecchio int8 si cancella dopo il primo download
  riuscito del nuovo (lo stato del componente «transcription» resta lo stesso id per l'UI).
- Il VAD Silero non serve più: non scaricarlo (e cancellarlo se presente).

## 2. Trascrizione (rt/core/onnx_stt.py, transcribe_onnx)
- Niente VAD. Finestre fisse da 6 s con sovrapposizione 1,5 s, batch 1, una sola sessione.
- Volume: guadagno globale = min(0,1 / rms, 4 / picco), clip a ±1 (registrazioni d'aula ~0,006 rms).
- Cucitura per PAROLE come onnx_finestre_riferimento.py (solo riferimento, non da importare): una parola appartiene alla finestra in cui inizia prima di
  metà sovrapposizione; scartare le prime parole della nuova finestra che ripetono una delle ultime 3
  tenute (testo uguale senza punteggiatura, inizio entro 1,5 s dall'ultima).
- RAM sotto 3 GB: decodifica con ffmpeg a blocchi (es. 60 s alla volta da stdout, s16le) e calcolo
  di rms/picco in un primo passaggio in streaming, senza tenere la forma d'onda intera in float32 né
  la copia normalizzata. Sessione ONNX con le opzioni predefinite (le opzioni «basso consumo»
  peggiorano RAM e tempo; niente CoreML EP: nessun guadagno).
- Uscita invariata (formato macparakeet: ms, wordTimestamps con confidenza, wordRange). Segmenti: chiudere
  un segmento su punteggiatura finale o pausa > 0,8 s tra parole, massimo ~30 s.
- Avanzamento in % = secondi elaborati / durata; annullamento tra una finestra e l'altra (come oggi).

## 3. Pannello Componenti / testi
- Dimensione mostrata ~900 MB; descrizione «Modello di trascrizione per Windows (e alternativa sul Mac)».

## Test (agy scrive solo i test unitari, niente download reali né modelli veri)
- Cucitura: finestre finte con parole sovrapposte → nessuna ripetizione, nessuna parola persa al confine.
- Normalizzazione: guadagno limitato dal picco.
- Decodifica a blocchi: stesso numero di campioni della decodifica intera (ffmpeg finto o wav sintetico).
- Download: SHA256 sbagliato → errore; ripresa da `.part`; il vecchio int8 e silero vengono cancellati.
- Regole: HOME/USERPROFILE/RT_DATA_DIR finti, mai la cartella dati vera.

## Verifica (Claude, sul Pro, dopo la beta)
- Stessa lezione da 74:49: ≥ 7300 parole, RAM < 3 GB, tempo ≤ 4 min. Poi prova su Windows quando possibile.
