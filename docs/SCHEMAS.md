# Schemi Dati e Contratti JSON (SCHEMAS.md)

Tutti i dati strutturati scambiati nel workflow RT 2.0 seguono schemi Pydantic rigorosi, validabili anche come JSON Schema.

---

## 1. `Segment` e `segments.json`

Rappresenta la sorgente di verità immutabile derivata dall'ASR.

```json
{
  "schema_version": "1.0",
  "lesson_id": "test_lezione",
  "audio_duration_seconds": 4732.0,
  "segments": [
    {
      "id": "seg_000184",
      "index": 184,
      "start_seconds": 2190.0,
      "end_seconds": 2228.0,
      "start_formatted": "36:30",
      "end_formatted": "37:08",
      "text_raw": "Il proprio lipo A viene processato dal nostro organismo.",
      "source_file": "trascritto grezzo.md",
      "speaker": null,
      "confidence": null,
      "flags": []
    }
  ]
}
```

---

## 2. `Outline` e `outline.json`

Struttura didattica gerarchica. **I timestamp sono espressi unicamente tramite gli ID dei segmenti**.

```json
{
  "schema_version": "1.0",
  "lesson_title": "Catabolismo dei Trigliceridi e Beta-Ossidazione",
  "macro_sections": [
    {
      "id": "5",
      "title": "Metabolismo degli acidi grassi a catena dispari",
      "units": [
        {
          "id": "5.1",
          "title": "Origine e destino del propionil-CoA",
          "start_segment_id": "seg_000184",
          "end_segment_id": "seg_000202",
          "key_concepts": [
            "propionil-CoA",
            "metilmalonil-CoA",
            "succinil-CoA"
          ]
        }
      ]
    }
  ]
}
```

---

## 3. `Draft` e `draft.json`

Testo rielaborato con **provenance esplicita** (`source_segment_ids`).

```json
{
  "schema_version": "1.0",
  "lesson_id": "test_lezione",
  "units": [
    {
      "unit_id": "5.1",
      "title": "Origine e destino del propionil-CoA",
      "start_segment_id": "seg_000184",
      "end_segment_id": "seg_000202",
      "source_segment_ids": [
        "seg_000184",
        "seg_000185",
        "seg_000186"
      ],
      "content": "La beta-ossidazione degli acidi grassi con numero dispari di atomi di carbonio genera come prodotto terminale una molecola di propionil-CoA...",
      "generated_at": "2026-09-05T20:30:00.000Z"
    }
  ]
}
```

---

## 4. `ASRIssue` e `asr_issues.json`

Ambiguità fonetiche con Confidence Gating a tre livelli.

```json
[
  {
    "id": "asr_000031",
    "segment_id": "seg_000186",
    "source_text": "licorolo finansi",
    "candidate": "glicerolo chinasi",
    "confidence": 0.91,
    "level": "YELLOW",
    "reason": "Correzione fonetica coerente con la fosforilazione iniziale del glicerolo",
    "status": "pending"
  }
]
```

---

## 5. `ScienceIssue` e `science_issues.json`

Critica scientifica avversaria per distinguere errori del docente da errori della rielaborazione.

```json
[
  {
    "id": "sci_000012",
    "type": "ERR_DOCENTE",
    "severity": "high",
    "unit_id": "5.1",
    "segment_id": "seg_000186",
    "claim": "I sarcomeri sono presenti nel muscolo liscio per estrarre energia.",
    "source_quote": "nei muscoli lisci ci sono sarcomeri ben evidenti",
    "reason": "I sarcomeri sono l'unità contrattile tipica del muscolo striato (scheletrico e cardiaco), assenti nel muscolo liscio.",
    "suggested_fix": "Correggere in muscolo striato scheletrico",
    "diplomatic_question": "Professore, quando parlava dell'organizzazione sarcomerica intendeva il muscolo striato scheletrico?",
    "status": "pending"
  }
]
```

---

## 6. `ReviewDecision` e `review_decisions.json`

Decision Ledger persistito e immutabile.

```json
{
  "schema_version": "1.0",
  "decisions": [
    {
      "issue_id": "asr_000031",
      "decision": "accepted",
      "resolved_text": "glicerolo chinasi",
      "resolved_by": "user",
      "timestamp": "2026-09-05T20:45:00.000Z",
      "notes": "Confermato da ascolto audio"
    }
  ]
}
```

---

## 7. `Manifest` e `manifest.json`

Registro di riproducibilità tecnica della lezione.

```json
{
  "schema_version": "1.0",
  "workflow_version": "2.0.0",
  "lesson_id": "test_lezione",
  "lesson_dir": "/percorso/cartella",
  "date": "2026-09-05",
  "subject": "BIOCHIMICA",
  "topics": "Lipidi",
  "audio_file": "BIOCHIMICA, 14 maggio.m4a",
  "audio_duration_seconds": 4732.0,
  "segment_count": 499,
  "current_state": "completato",
  "created_at": "2026-09-05T17:18:33.000Z",
  "updated_at": "2026-09-05T20:40:00.000Z",
  "model_info": {
    "provider": "openrouter",
    "model": "deepseek/deepseek-chat"
  },
  "coverage_stats": {
    "total_segments": 499,
    "coverage_percentage": 100.0
  }
}
```
