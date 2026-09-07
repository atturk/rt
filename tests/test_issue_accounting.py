"""
tests/test_issue_accounting.py
Verifica che i conteggi e le statistiche di ASR Issues, Science Issues,
Decisioni e Pendenti siano rigorosamente dinamici e calcolati al 100% dal contenuto
degli artefatti, senza mai basarsi su conteggi hardcoded.
"""

import os
import json
import pytest

from rt.pipeline.ledger import record_decision, load_ledger
from rt.cli import cmd_status


def test_dynamic_accounting_math(tmp_path, capsys):
    """
    Testa il bilancio dinamico delle issues:
    Crea un set sintetico con numeri arbitrari di ASR issues, Science issues e Decisioni,
    e verifica che cmd_status --issues stampi esattamente i numeri calcolati dinamicamente.
    """
    lesson_dir = str(tmp_path / "[2026-09-05] TEST - Accounting")
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi
cartella: '[2026-09-05] TEST - Accounting'
file_audio: test_audio.m4a
fase_corrente: completed
stato: completed
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    # Creiamo N issue ASR: 7 green, 5 yellow, 3 red = 15 totali
    asr_issues = []
    for i in range(7):
        asr_issues.append({
            "id": f"asr_g_{i}", "segment_id": f"seg_{i}", "source_text": f"src_{i}",
            "candidate": f"cand_{i}", "confidence": 0.95, "level": "GREEN", "reason": "fonetica", "status": "pending"
        })
    for i in range(5):
        asr_issues.append({
            "id": f"asr_y_{i}", "segment_id": f"seg_{i+7}", "source_text": f"src_{i+7}",
            "candidate": f"cand_{i+7}", "confidence": 0.70, "level": "YELLOW", "reason": "ambiguo", "status": "pending"
        })
    for i in range(3):
        asr_issues.append({
            "id": f"asr_r_{i}", "segment_id": f"seg_{i+12}", "source_text": f"src_{i+12}",
            "candidate": f"cand_{i+12}", "confidence": 0.40, "level": "RED", "reason": "critico", "status": "pending"
        })

    with open(os.path.join(lesson_dir, "asr_issues.json"), "w", encoding="utf-8") as f:
        json.dump(asr_issues, f, indent=2)

    # Creiamo M science issues: 2 ERR_DOCENTE, 4 ERR_RECONSTRUCTION, 1 SCIENCE_CHECK = 7 totali
    sci_issues = []
    for i in range(2):
        sci_issues.append({
            "id": f"sci_d_{i}", "type": "ERR_DOCENTE", "severity": "high", "claim": f"claim_{i}", "reason": "errore docente", "status": "pending"
        })
    for i in range(4):
        sci_issues.append({
            "id": f"sci_r_{i}", "type": "ERR_RECONSTRUCTION", "severity": "medium", "claim": f"claim_{i+2}", "reason": "allucinazione", "status": "pending"
        })
    for i in range(1):
        sci_issues.append({
            "id": f"sci_c_{i}", "type": "SCIENCE_CHECK", "severity": "low", "claim": f"claim_{i+6}", "reason": "controllo fonti", "status": "pending"
        })

    with open(os.path.join(lesson_dir, "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump(sci_issues, f, indent=2)

    # Registriamo alcune decisioni:
    # 7 auto_green (tutti i green)
    for i in range(7):
        record_decision(lesson_dir, f"asr_g_{i}", "accetta", notes="auto green", resolved_by="auto_green")
    # 3 yellow accettati dall'utente
    for i in range(3):
        record_decision(lesson_dir, f"asr_y_{i}", "accetta", notes="manual user accept", resolved_by="user")
    # 1 science issue risolta dall'utente
    record_decision(lesson_dir, "sci_d_0", "riformula", notes="manual rewrite note", resolved_by="user")

    from types import SimpleNamespace
    args = SimpleNamespace(lesson_dir=lesson_dir, issues=True)
    cmd_status(args)
    captured = capsys.readouterr().out

    assert "ASR Issues (15 totali):" in captured
    assert "GREEN (auto-applicate):     7" in captured
    assert "YELLOW (coda di revisione): 5" in captured
    assert "RED (ascolto richiesto):    3" in captured

    assert "Science Issues (7 totali):" in captured
    assert "ERR_DOCENTE:                2" in captured
    assert "ERR_RECONSTRUCTION:         4" in captured
    assert "SCIENCE_CHECK:              1" in captured

    assert "Decision Ledger (11 registrate):" in captured
    assert "auto-applied:               7" in captured
    assert "user/manual:                4" in captured

    assert "Totale issue rilevate:      22" in captured
    assert "Decisioni archiviate:       11" in captured
    assert "Anomalie pendenti:          11 (ASR: 5, Science: 6)" in captured
    assert "phase_statuses" not in captured


def test_cmd_status_json_flag(tmp_path, capsys):
    """Verifica il comportamento del flag --json in cmd_status."""
    from types import SimpleNamespace
    lesson_dir = str(tmp_path / "[2026-09-05] TEST - StatusJSON")
    os.makedirs(lesson_dir, exist_ok=True)

    info_content = """data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi
cartella: '[2026-09-05] TEST - StatusJSON'
file_audio: test_audio.m4a
fase_corrente: completed
stato: completed
"""
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    # 1. Senza --json: human text presente, blocco JSON assente
    args_no_json = SimpleNamespace(lesson_dir=lesson_dir, issues=False, json=False)
    cmd_status(args_no_json)
    out_no_json = capsys.readouterr().out
    assert "Freschezza Fasi / Artefatti:" in out_no_json
    assert "STATO WORKFLOW RT 2.0:" in out_no_json
    assert "phase_statuses" not in out_no_json
    assert '"fase_corrente":' not in out_no_json

    # 2. Con --json: human text presente, blocco JSON presente
    args_with_json = SimpleNamespace(lesson_dir=lesson_dir, issues=False, json=True)
    cmd_status(args_with_json)
    out_with_json = capsys.readouterr().out
    assert "Freschezza Fasi / Artefatti:" in out_with_json
    assert "STATO WORKFLOW RT 2.0:" in out_with_json
    assert '"phase_statuses":' in out_with_json
    assert '"fase_corrente": "completed"' in out_with_json

    # 3. Con --issues e --json: sia breakdown diagnostico che breakdown nel JSON
    args_issues_json = SimpleNamespace(lesson_dir=lesson_dir, issues=True, json=True)
    cmd_status(args_issues_json)
    out_issues_json = capsys.readouterr().out
    assert "REPORT DIAGNOSTICO DETTAGLIATO ISSUE & DECISION LEDGER" in out_issues_json
    assert '"issues_breakdown":' in out_issues_json
    assert '"phase_statuses":' in out_issues_json
