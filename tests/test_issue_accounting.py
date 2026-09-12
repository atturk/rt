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
    # 7 auto_applied (decisioni automatiche)
    for i in range(7):
        record_decision(lesson_dir, f"sci_auto_{i}", "accepted", notes="auto applied", resolved_by="cli_auto")
    # 1 science issue risolta dall'utente
    record_decision(lesson_dir, "sci_d_0", "riformula", notes="manual rewrite note", resolved_by="user")

    from types import SimpleNamespace
    args = SimpleNamespace(lesson_dir=lesson_dir, issues=True)
    cmd_status(args)
    captured = capsys.readouterr().out

    assert "Science Issues (7 totali):" in captured
    assert "ERR_DOCENTE:                2" in captured
    assert "ERR_RECONSTRUCTION:         4" in captured
    assert "SCIENCE_CHECK:              1" in captured

    assert "Decision Ledger (8 registrate):" in captured
    assert "auto-applied:               7" in captured
    assert "user/manual:                1" in captured

    assert "Totale issue rilevate:      7" in captured
    assert "Decisioni archiviate:       8" in captured
    assert "Anomalie pendenti:          6 (Science: 6)" in captured
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
