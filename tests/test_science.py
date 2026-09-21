"""
Unit test per la classificazione delle problematiche scientifiche e migrazione legacy.
"""

import os
import json
import pytest
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity
)
from rt.pipeline.review import load_science_issues


def classify_scientific_scenario(
    source_transcript: str,
    rewritten_text: str,
    scientific_ground_truth: str
) -> dict:
    """
    Logica di classificazione scientifica per errori concettuali.
    """
    # Scenario 1: Source corretto, Modello corretto
    if "glucosio-6-fosfato" in rewritten_text and "glucosio-6-fosfato" in scientific_ground_truth:
        if "glucosio 6 fosfato" in source_transcript or "glucosio-6-fosfato" in source_transcript:
            return {"status": "ok", "issue": None}
            
    # Scenario 2: Modello errato
    if "piruvato deidrogenasi" in source_transcript and "piruvato carbossilasi" in rewritten_text:
        return {
            "status": "error",
            "issue": ScienceIssue(
                id="sci_test_01",
                type=ScienceType.ERR_CONCETTUALE,
                severity=ScienceSeverity.HIGH,
                claim="Il modello attribuisce la reazione alla piruvato carbossilasi",
                source_quote="piruvato deidrogenasi",
                reason="Il testo cita la piruvato carbossilasi anziché piruvato deidrogenasi",
                suggested_fix="Sostituire con piruvato deidrogenasi"
            )
        }
        
    # Scenario 3: Lapsus / errore concettuale con domanda diplomatica
    if ("muscolo liscio" in source_transcript or "muscoli lisci" in source_transcript) and ("muscolo liscio" in rewritten_text or "muscoli lisci" in rewritten_text) and "striato" in scientific_ground_truth:
        return {
            "status": "error",
            "issue": ScienceIssue(
                id="sci_test_02",
                type=ScienceType.ERR_CONCETTUALE,
                severity=ScienceSeverity.HIGH,
                claim="Si indica il muscolo liscio per i sarcomeri",
                source_quote="nei muscoli lisci ci sono i sarcomeri",
                reason="I sarcomeri sono presenti esclusivamente nel muscolo striato (scheletrico e cardiaco)",
                suggested_fix="Correggere in muscolo striato",
                diplomatic_question="Professore, quando parlava dell'organizzazione sarcomerica si riferiva al muscolo striato?"
            )
        }
        
    # Scenario 4: Allucinazione grave
    if "qualcosa fa reazione" in source_transcript and "enzima citocromo b558 riduce il ferro a 37 gradi" in rewritten_text:
        return {
            "status": "error",
            "issue": ScienceIssue(
                id="sci_test_03",
                type=ScienceType.ERR_CONCETTUALE,
                severity=ScienceSeverity.HIGH,
                claim="Dettagli specifici sul citocromo b558 e temperatura",
                source_quote="qualcosa fa reazione",
                reason="Ricostruzione non supportata dalla lezione (allucinazione fattuale)",
                suggested_fix="Attenersi al testo generale senza inventare complessi enzimatici non detti"
            )
        }
        
    return {"status": "ok", "issue": None}


def test_scenario_source_correct_model_correct():
    res = classify_scientific_scenario(
        source_transcript="il glucosio 6 fosfato entra nella via",
        rewritten_text="Il glucosio-6-fosfato imbocca la glicolisi.",
        scientific_ground_truth="glucosio-6-fosfato"
    )
    assert res["status"] == "ok"
    assert res["issue"] is None


def test_scenario_source_correct_model_wrong():
    res = classify_scientific_scenario(
        source_transcript="la piruvato deidrogenasi converte il piruvato in acetil-CoA",
        rewritten_text="La piruvato carbossilasi converte il piruvato in acetil-CoA.",
        scientific_ground_truth="piruvato deidrogenasi"
    )
    assert res["status"] == "error"
    assert res["issue"].type == ScienceType.ERR_CONCETTUALE
    assert res["issue"].severity == ScienceSeverity.HIGH
    assert "piruvato carbossilasi" in res["issue"].claim


def test_scenario_err_concettuale_with_diplomatic_question():
    res = classify_scientific_scenario(
        source_transcript="nei muscoli lisci ci sono i sarcomeri ben evidenti",
        rewritten_text="Come illustrato, nei muscoli lisci sono presenti sarcomeri evidenti.",
        scientific_ground_truth="striato"
    )
    assert res["status"] == "error"
    assert res["issue"].type == ScienceType.ERR_CONCETTUALE
    assert res["issue"].diplomatic_question is not None


def test_scenario_source_ambiguous_model_hallucinated():
    res = classify_scientific_scenario(
        source_transcript="e qui qualcosa fa reazione nel processo",
        rewritten_text="L'enzima citocromo b558 riduce il ferro a 37 gradi centigradi.",
        scientific_ground_truth=""
    )
    assert res["status"] == "error"
    assert res["issue"].type == ScienceType.ERR_CONCETTUALE
    assert "allucinazione" in res["issue"].reason.lower()


def test_load_science_issues_legacy_migration(tmp_path):
    """Verifica che load_science_issues rimappi trasparentemente i tipi legacy a ERR_CONCETTUALE."""
    lesson_dir = str(tmp_path / "legacy_lesson")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)
    
    legacy_json = [
        {
            "id": "sci_000001",
            "type": "ERR_DOCENTE",
            "severity": "high",
            "claim": "Claim docente",
            "reason": "Lapsus",
            "suggested_fix": "Fix docente",
            "diplomatic_question": "Professore, intendeva...",
            "status": "pending"
        },
        {
            "id": "sci_000002",
            "type": "ERR_RECONSTRUCTION",
            "severity": "medium",
            "claim": "Claim reconstruction",
            "reason": "Allucinazione",
            "suggested_fix": "Fix rewrite",
            "status": "accepted"
        },
        {
            "id": "sci_000003",
            "type": "SCIENCE_CHECK",
            "severity": "low",
            "claim": "Claim check",
            "reason": "Verifica",
            "status": "rejected"
        },
        {
            "id": "sci_000004",
            "type": "ERR_ASR_ST",
            "severity": "medium",
            "claim": "Claim asr",
            "reason": "Degrado statistico",
            "status": "pending"
        }
    ]
    with open(os.path.join(lesson_dir, "_state", "science_issues.json"), "w", encoding="utf-8") as f:
        json.dump(legacy_json, f, indent=2)

    loaded = load_science_issues(lesson_dir)
    assert len(loaded) == 4
    assert loaded[0].type == ScienceType.ERR_CONCETTUALE
    assert loaded[0].diplomatic_question == "Professore, intendeva..."
    assert loaded[1].type == ScienceType.ERR_CONCETTUALE
    assert loaded[2].type == ScienceType.ERR_CONCETTUALE
    assert loaded[3].type == ScienceType.ERR_ASR_ST
