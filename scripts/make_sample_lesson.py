#!/usr/bin/env python3
"""
Crea l'archivio di esempio rt/assets/esempio/lezione-esempio.rt.
Contiene una lezione già elaborata di materia «ESEMPIO» con trascrizione, rielaborato,
verifica e domande di autovalutazione, pronta per essere importata a costo zero.
"""
import json
import os
import shutil
import sys
import tempfile
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from rt.storage.export import export_zip

FOLDER_NAME = "[2026-10-01] ESEMPIO - Introduzione a RT"


def build_sample_lesson(output_path: str) -> str:
    temp_root = tempfile.mkdtemp(prefix="rt-sample-lesson-")
    lesson_dir = os.path.join(temp_root, FOLDER_NAME)
    os.makedirs(lesson_dir, exist_ok=True)
    state_dir = os.path.join(lesson_dir, "_state")
    os.makedirs(state_dir, exist_ok=True)

    try:
        # 1. info.yaml
        info = {
            "data": "2026-10-01",
            "materia": "ESEMPIO",
            "titolo": "Introduzione a RT",
            "docente": "Team RT",
            "anno": 2026,
            "durata": "00:45",
        }
        with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(info, f, allow_unicode=True, sort_keys=False)

        # 2. trascritto grezzo.md
        transcript = """---
data: '2026-10-01'
materia: ESEMPIO
titolo: Introduzione a RT
---

*00:00*
Benvenuti a questa lezione dimostrativa di RT. Oggi vediamo i principi fondamentali dello studio attivo.

*00:15*
RT suddivide automaticamente la lezione in unità logiche per facilitare la comprensione e il ripasso.

*00:30*
Ogni unità viene verificata rispetto alle fonti ufficiali fornite dal docente per correggere eventuali imprecisioni.
"""
        with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
            f.write(transcript)

        # 3. Documento finale Markdown
        final_md = """# Introduzione a RT

## 1. Principi di RT

### 1.1 Benvenuto e studio attivo
00:00

Benvenuti a questa lezione dimostrativa di RT. In questa sessione introduttiva esploriamo i principi fondamentali dello studio attivo, pensato per ottimizzare l'apprendimento e la memorizzazione a lungo termine.

### 1.2 Struttura a unità logiche
00:15

RT suddivide la trascrizione in unità logiche di studio. Ogni unità raccoglie un singolo concetto chiave o argomento trattato durante la spiegazione orale.

## 2. Verifica e memorizzazione

### 2.1 Verifica con le fonti
00:30

Il testo rielaborato viene confrontato automaticamente con le slide e i documenti del docente. Questo processo individua discrepanze ed errori prima che vengano memorizzati dallo studente.
"""
        with open(os.path.join(lesson_dir, f"{FOLDER_NAME}.md"), "w", encoding="utf-8") as f:
            f.write(final_md)

        # 4. _state/rielaborato.md
        with open(os.path.join(state_dir, "rielaborato.md"), "w", encoding="utf-8") as f:
            f.write(final_md)

        # 5. _state/outline.json
        outline = {
            "sections": [
                {
                    "id": "1",
                    "title": "Principi di RT",
                    "units": [
                        {"id": "1.1", "title": "Benvenuto e studio attivo", "start": 0, "end": 15},
                        {"id": "1.2", "title": "Struttura a unità logiche", "start": 15, "end": 30},
                    ],
                },
                {
                    "id": "2",
                    "title": "Verifica e memorizzazione",
                    "units": [
                        {"id": "2.1", "title": "Verifica con le fonti", "start": 30, "end": 45},
                    ],
                },
            ],
        }
        with open(os.path.join(state_dir, "outline.json"), "w", encoding="utf-8") as f:
            json.dump(outline, f, ensure_ascii=False, indent=2)

        # 6. _state/draft.json
        draft = {
            "1.1": "Benvenuti a questa lezione dimostrativa di RT. In questa sessione introduttiva esploriamo i principi fondamentali dello studio attivo.",
            "1.2": "RT suddivide la trascrizione in unità logiche di studio. Ogni unità raccoglie un singolo concetto chiave.",
            "2.1": "Il testo rielaborato viene confrontato automaticamente con le slide e i documenti del docente.",
        }
        with open(os.path.join(state_dir, "draft.json"), "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False, indent=2)

        # 7. _state/science_issues.json
        issues = [
            {
                "id": "sample-issue-1",
                "unit_id": "2.1",
                "anchor": {
                    "quote": "slide e i documenti del docente",
                    "prefix": "",
                    "suffix": "",
                    "start": 0,
                    "end": 31,
                },
                "type": "ERR_CONCETTUALE",
                "severity": "low",
                "claim": "Verifica rispetto alle fonti ufficiali",
                "reason": "Il docente raccomanda di verificare i dettagli terminologici sulle dispense ufficiali.",
                "status": "decided",
            }
        ]
        with open(os.path.join(state_dir, "science_issues.json"), "w", encoding="utf-8") as f:
            json.dump(issues, f, ensure_ascii=False, indent=2)

        # 8. _state/review_decisions.json
        decisions = {
            "sample-issue-1": {
                "decision": "accepted",
                "applied_at": "2026-10-01T10:00:00Z",
            }
        }
        with open(os.path.join(state_dir, "review_decisions.json"), "w", encoding="utf-8") as f:
            json.dump(decisions, f, ensure_ascii=False, indent=2)

        # 9. _state/recall_questions.json
        questions = {
            "questions": [
                {
                    "id": "sample-q1",
                    "unit_ids": ["1.1", "1.2"],
                    "type": "quiz",
                    "question_text": "In che modo RT organizza i contenuti della lezione per facilitare lo studio?",
                    "answer_text": "RT organizza i contenuti suddividendoli in unità logiche di studio incentrate su singoli concetti chiave.",
                    "difficulty": "facile",
                },
                {
                    "id": "sample-q2",
                    "unit_ids": ["2.1"],
                    "type": "quiz",
                    "question_text": "A cosa serve il confronto con le fonti del docente nella scheda Verifica?",
                    "answer_text": "Serve a rilevare discrepanze ed incongruenze tra il parlato e i materiali ufficiali prima della memorizzazione.",
                    "difficulty": "medio",
                },
            ],
            "answers": [],
            "last_question_number": 2,
        }
        with open(os.path.join(state_dir, "recall_questions.json"), "w", encoding="utf-8") as f:
            json.dump(questions, f, ensure_ascii=False, indent=2)

        # 10. Pacchetto .rt completo usando export_zip
        archive_bytes = export_zip(lesson_dir, scope="all")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(archive_bytes)

        size_kb = os.path.getsize(output_path) / 1024
        print(f"✅ Lezione di esempio creata con successo in {output_path} ({size_kb:.1f} KB)")
        if size_kb > 1024:
            raise ValueError(f"L'archivio supera 1 MB: {size_kb:.1f} KB")

        return output_path
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    target = os.path.join(ROOT_DIR, "rt", "assets", "esempio", "lezione-esempio.rt")
    build_sample_lesson(target)
