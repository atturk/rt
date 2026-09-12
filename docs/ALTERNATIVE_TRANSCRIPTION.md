# Utilizzo di Motori di Trascrizione Alternativi in RT

Questo documento illustra come utilizzare motori di Speech-to-Text (STT) alternativi al motore predefinito `macparakeet-cli` (es. Whisper locale/faster-whisper, Deepgram, OpenAI Audio API, MacWhisper, Voxtral, Gladia, AssemblyAI, ecc.) con la pipeline di RT.

---

## Principio Architetturale

RT **non è vincolato a macparakeet-cli**: il core deterministico del sistema opera esclusivamente sulla struttura standard dei segmenti temporali (`segments.json`).

La fase `prepare` (`rt prepare "cartella_lezione"`) cerca nella cartella della lezione uno tra questi tre file:
1. `trascritto grezzo.json`
2. `segments_raw.json`
3. `transcript.json`

Indipendentemente da quale motore abbia generato la trascrizione, è sufficiente salvare l'output in uno dei formati riconosciuti con uno di questi nomi di file.

---

## I 4 Formati JSON Supportati da `parse_segments_from_json`

La funzione di ingestione `parse_segments_from_json` supporta automaticamente 4 formati:

### 1. Formato macparakeet-cli (Caso 4 — Motore Predefinito)
Struttura con array `transcriptSegments` e campo `rawTranscript`, in cui `startMs` ed `endMs` sono numeri in millisecondi.

```json
{
  "rawTranscript": "Buongiorno a tutti, oggi iniziamo la lezione.",
  "transcriptSegments": [
    {
      "startMs": 0,
      "endMs": 4500,
      "text": "Buongiorno a tutti, oggi iniziamo la lezione.",
      "speakerLabel": "Speaker 1"
    }
  ]
}
```

### 2. Formato MacWhisper (Caso 1 — Storico)
Struttura con array `segments` o lista root in cui `start` ed `end` sono numeri in millisecondi.

```json
{
  "segments": [
    {
      "start": 0,
      "end": 4500,
      "text": "Buongiorno a tutti, oggi iniziamo la lezione.",
      "speaker": "Speaker 1"
    }
  ]
}
```

### 2. Formato Timestamp a Stringa (Intervalli o Timecode)
Struttura in cui ogni segmento ha un campo `timestamp` come stringa (es. `"00:00 - 00:05"` o `"01:23"`).

```json
[
  {
    "timestamp": "00:00 - 00:04",
    "text": "Buongiorno a tutti, oggi iniziamo la lezione."
  }
]
```

### 3. Formato RT Conforme (Caso 3 — Consigliato per Convertitori Custom)
Struttura JSON già pienamente conforme allo schema interno `Segment`. È il formato più semplice e diretto se si sviluppa uno script di conversione per il proprio motore STT.

```json
[
  {
    "id": "seg_000001",
    "index": 1,
    "start_seconds": 0.0,
    "end_seconds": 4.5,
    "start_formatted": "00:00",
    "end_formatted": "00:04",
    "text_raw": "Buongiorno a tutti, oggi iniziamo la lezione."
  },
  {
    "id": "seg_000002",
    "index": 2,
    "start_seconds": 4.5,
    "end_seconds": 9.2,
    "start_formatted": "00:04",
    "end_formatted": "00:09",
    "text_raw": "Tratteremo la regolazione allosterica degli enzimi."
  }
]
```

#### Campi del Formato Caso 3:
- **`id`** *(string, obbligatorio)*: Identificativo del segmento (convenzione `seg_001`, `seg_002`, ...).
- **`index`** *(integer, obbligatorio)*: Indice progressivo 1-based del segmento.
- **`start_seconds`** *(float, obbligatorio)*: Tempo di inizio in secondi.
- **`end_seconds`** *(float, obbligatorio)*: Tempo di fine in secondi.
- **`start_formatted`** *(string, obbligatorio)*: Timestamp formattato `MM:SS` o `HH:MM:SS`.
- **`end_formatted`** *(string, obbligatorio)*: Timestamp formattato `MM:SS` o `HH:MM:SS`.
- **`text_raw`** *(string, obbligatorio)*: Testo trascritto grezzo del segmento.
- **`speaker`** *(string, opzionale)*: Identificativo speaker (se disponibile diarizzazione).
- **`confidence`** *(float, opzionale)*: Punteggio di confidenza ASR (0.0 - 1.0).

---

## Procedura Passo-Passo

Ecco come elaborare una lezione con un motore di trascrizione esterno:

### 1. Setup della Lezione senza macparakeet-cli
Esegui `rt setup` con il flag `--skip-transcribe`:
```bash
./bin/rt setup --skip-transcribe "percorso/audio.m4a" -d "2026-09-07" -m "Biochimica" -a "Prof. Rossi"
```
Questo comando crea la cartella della lezione, copia il file audio e inizializza `info.yaml`, senza tentare di invocare macparakeet-cli.

### 2. Trascrizione ed Esportazione
Trascrivi il file audio con il motore preferito (es. script Python locale con `faster-whisper`, API cloud Deepgram, ecc.) ed esporta il risultato convertito nel formato Caso 3 (o Caso 1/2).

### 3. Posizionamento del File Trascritto
Salva il JSON ottenuto come `trascritto grezzo.json` (oppure `segments_raw.json`) direttamente all'interno della cartella lezione appena creata.

### 4. Esecuzione Pipeline RT
Lancia `prepare` per estrarre e validare i segmenti deterministici, poi prosegui con i consueti step della pipeline:
```bash
./bin/rt prepare "cartella_lezione"
./bin/rt outline "cartella_lezione"
./bin/rt rewrite "cartella_lezione"
./bin/rt review-asr "cartella_lezione"
./bin/rt review-science "cartella_lezione"
./bin/rt build "cartella_lezione"
```
Oppure direttamente:
```bash
./bin/rt run "cartella_lezione"
```
