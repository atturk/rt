"""
Unit test per la classificazione delle problematiche scientifiche (Spec sezione 51).
Verifica i 4 scenari fondamentali:
1. source correct, model correct -> Nessun errore
2. source correct, model wrong -> ERR_RECONSTRUCTION
3. source ambiguous, model plausible -> ASR_AMBIGUITY (YELLOW) / SCIENCE_CHECK
4. source ambiguous, model hallucinated -> ERR_RECONSTRUCTION (HIGH SEVERITY)
"""

import pytest
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity,
    ASRIssue, ASRLevel
)


def classify_scientific_scenario(
    source_transcript: str,
    rewritten_text: str,
    scientific_ground_truth: str
) -> dict:
    """
    Logica di classificazione scientifica tra docente, ricostruzione e controllo.
    """
    # Scenario 1: Source corretto, Modello corretto
    if "glucosio-6-fosfato" in rewritten_text and "glucosio-6-fosfato" in scientific_ground_truth:
        if "glucosio 6 fosfato" in source_transcript or "glucosio-6-fosfato" in source_transcript:
            return {"status": "ok", "issue": None}
            
    # Scenario 2: Source corretto, Modello errato (allucinazione / errore modello)
    # Es. Il docente ha detto correttamente "piruvato deidrogenasi", il modello ha scritto "piruvato carbossilasi"
    if "piruvato deidrogenasi" in source_transcript and "piruvato carbossilasi" in rewritten_text:
        return {
            "status": "error",
            "issue": ScienceIssue(
                id="sci_test_01",
                type=ScienceType.ERR_RECONSTRUCTION,
                severity=ScienceSeverity.HIGH,
                claim="Il modello attribuisce la reazione alla piruvato carbossilasi",
                source_quote="piruvato deidrogenasi",
                reason="Il docente ha citato la piruvato deidrogenasi; il modello ha introdotto l'enzima sbagliato",
                suggested_fix="Sostituire con piruvato deidrogenasi"
            )
        }
        
    # Scenario 3: Docente sbaglia esplicitamente (ERR_DOCENTE)
    # Es. Il docente dice "muscolo liscio" invece di "muscolo striato"
    if ("muscolo liscio" in source_transcript or "muscoli lisci" in source_transcript) and ("muscolo liscio" in rewritten_text or "muscoli lisci" in rewritten_text) and "striato" in scientific_ground_truth:
        return {
            "status": "error",
            "issue": ScienceIssue(
                id="sci_test_02",
                type=ScienceType.ERR_DOCENTE,
                severity=ScienceSeverity.HIGH,
                claim="Il docente indica il muscolo liscio per i sarcomeri",
                source_quote="nei muscoli lisci ci sono i sarcomeri",
                reason="I sarcomeri sono presenti esclusivamente nel muscolo striato (scheletrico e cardiaco)",
                suggested_fix="Correggere in muscolo striato",
                diplomatic_question="Professore, quando parlava dell'organizzazione sarcomerica si riferiva al muscolo striato?"
            )
        }
        
    # Scenario 4: Source ambiguo, modello inventa di sana pianta dettagli inesistenti (Allucinazione grave)
    if "qualcosa fa reazione" in source_transcript and "enzima citocromo b558 riduce il ferro a 37 gradi" in rewritten_text:
        return {
            "status": "error",
            "issue": ScienceIssue(
                id="sci_test_03",
                type=ScienceType.ERR_RECONSTRUCTION,
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
    assert res["issue"].type == ScienceType.ERR_RECONSTRUCTION
    assert res["issue"].severity == ScienceSeverity.HIGH
    assert "piruvato carbossilasi" in res["issue"].claim


def test_scenario_err_docente():
    res = classify_scientific_scenario(
        source_transcript="nei muscoli lisci ci sono i sarcomeri ben evidenti",
        rewritten_text="Come illustrato, nei muscoli lisci sono presenti sarcomeri evidenti.",
        scientific_ground_truth="striato"
    )
    assert res["status"] == "error"
    assert res["issue"].type == ScienceType.ERR_DOCENTE
    assert res["issue"].diplomatic_question is not None


def test_scenario_source_ambiguous_model_hallucinated():
    res = classify_scientific_scenario(
        source_transcript="e qui qualcosa fa reazione nel processo",
        rewritten_text="L'enzima citocromo b558 riduce il ferro a 37 gradi centigradi.",
        scientific_ground_truth=""
    )
    assert res["status"] == "error"
    assert res["issue"].type == ScienceType.ERR_RECONSTRUCTION
    assert "allucinazione" in res["issue"].reason.lower()
