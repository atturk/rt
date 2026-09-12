"""
tests/test_science_grounding.py
Verifica della classificazione e del grounding conservativo per il Science Critic:
- ERR_DOCENTE richiede forte grounding nella sorgente (quote o parole chiave).
- Assenza di evidenza nella sorgente declassa ERR_DOCENTE a ERR_RECONSTRUCTION
  (evitando di attribuire al docente errori inventati dal modello in fase di riscrittura).
- Evidenza debole o parziale riclassifica in SCIENCE_CHECK per revisione umana.
"""

import pytest
from rt.pipeline.review import disambiguate_science_issue, check_text_grounding_score
from rt.core.models import ScienceType


def test_verbatim_quote_maintains_err_docente():
    """Se la citazione del docente è presente letteralmente nel trascritto grezzo, rimane ERR_DOCENTE."""
    source_text = "Il docente dice: 'La glicolisi produce 40 molecole di ATP per ogni glucosio'."
    issue_dict = {
        "id": "sci_01",
        "type": "ERR_DOCENTE",
        "severity": "CRITICAL",
        "source_quote": "La glicolisi produce 40 molecole di ATP",
        "claim": "La glicolisi produce 40 molecole di ATP per ogni glucosio",
        "correction": "Produce 2 ATP netti",
        "explanation": "Errore madornale del docente"
    }

    result = disambiguate_science_issue(issue_dict, source_text)
    assert result["type"] == ScienceType.ERR_DOCENTE.value
    assert "ERR_RECONSTRUCTION" not in result.get("explanation", "")


def test_grounded_reconstruction_reclassified_to_err_docente_via_claim_not_quote():
    """Se l'LLM classifica come ERR_RECONSTRUCTION (pensando di aver individuato
    un'invenzione del modello) ma il 'claim' (dal draft, sempre disponibile: il critic
    non ha più accesso alla trascrizione grezza per produrre un source_quote affidabile)
    è in realtà fortemente presente nella trascrizione originale, va riclassificato a
    ERR_DOCENTE: il docente l'ha detto per davvero, non è un'allucinazione del rewrite.
    La domanda diplomatica generata deve citare 'claim' (prosa pulita del draft), MAI
    'source_quote': anche se il modello ne produce comunque uno (nonostante le istruzioni,
    senza accesso alla trascrizione grezza non è affidabile e non va mai mostrato all'utente)."""
    source_text = "Oggi parliamo della beta-ossidazione e del ruolo della carnitina palmitoil transferasi nella membrana mitocondriale esterna."
    unreliable_quote = "cominciamo ad entrare allora gli spot del rey a differenza della seconda"
    issue_dict = {
        "id": "sci_05",
        "type": "ERR_RECONSTRUCTION",
        "severity": "MEDIUM",
        "source_quote": unreliable_quote,
        "claim": "il ruolo della carnitina palmitoil transferasi nella membrana mitocondriale esterna",
        "correction": "n/a",
        "explanation": "Sembra un dettaglio inventato dal modello",
    }

    result = disambiguate_science_issue(issue_dict, source_text)
    assert result["type"] == ScienceType.ERR_DOCENTE.value
    assert issue_dict["claim"] in result["diplomatic_question"]
    assert unreliable_quote not in result["diplomatic_question"]


def test_unsupported_claim_reclassified_to_err_reconstruction():
    """
    Se l'LLM segnala un presunto ERR_DOCENTE ma la frase o il concetto NON esistono minimamente
    nel trascritto del docente (invenzione o allucinazione durante il rewrite),
    il sistema non deve incolpare il docente ma riclassificare a ERR_RECONSTRUCTION.
    """
    source_text = "Oggi parliamo della beta-ossidazione e del ruolo della carnitina palmitoil transferasi."
    issue_dict = {
        "id": "sci_02",
        "type": "ERR_DOCENTE",
        "severity": "CRITICAL",
        "source_quote": "Il docente afferma che l'insulina stimola la lipolisi epatica",
        "claim": "L'insulina attiva la lipolisi",
        "correction": "L'insulina inibisce la lipolisi",
        "explanation": "Il docente ha sbagliato la regolazione"
    }

    result = disambiguate_science_issue(issue_dict, source_text)
    assert result["type"] == ScienceType.ERR_RECONSTRUCTION.value
    assert "[AUTO-RECLASSIFIED from ERR_DOCENTE to ERR_RECONSTRUCTION" in result["explanation"]


def test_ambiguous_evidence_reclassified_to_science_check():
    """
    Se vi è una sovrapposizione parziale o debole (parole chiave presenti ma nessuna citazione certa),
    il sistema non accusa né il docente né liquida come errore di modello,
    ma riclassifica a SCIENCE_CHECK per sottoporlo all'attenzione umana.
    """
    source_text = "Parliamo di ormoni, lipolisi negli adipociti, glucosio ematico e insulina."
    # Qui abbiamo parole sparse ('lipolisi', 'insulina') ma la frase specifica non è presente
    issue_dict = {
        "id": "sci_03",
        "type": "ERR_DOCENTE",
        "severity": "WARNING",
        "source_quote": "Il docente sembrava confondere l'insulina con il glucagone",
        "claim": "Attivazione della lipolisi mediata",
        "correction": "Verificare il passaggio",
        "explanation": "Dubbio scientifico"
    }

    result = disambiguate_science_issue(issue_dict, source_text)
    assert result["type"] == ScienceType.SCIENCE_CHECK.value
    assert "[AUTO-RECLASSIFIED to SCIENCE_CHECK" in result["explanation"]


def test_paraphrase_without_exact_match_maintains_err_docente():
    """
    Dimostra che il sistema NON richiede una corrispondenza testuale esatta 1:1.
    Una parafrasi concettuale con le parole chiave del docente viene riconosciuta
    come supportata e mantiene la classificazione ERR_DOCENTE.
    """
    source_text = "Il docente spiega: la carnitina palmitoil transferasi uno agisce sulla membrana esterna sintetizzando acilcarnitina."
    # Frase parafrasata con sintassi differente
    issue_dict = {
        "id": "sci_04",
        "type": "ERR_DOCENTE",
        "severity": "CRITICAL",
        "source_quote": "sintesi di acilcarnitina mediante carnitina palmitoil transferasi sulla membrana esterna",
        "claim": "carnitina palmitoil transferasi sintetizza acilcarnitina",
        "correction": "Ruolo corretto",
        "explanation": "Lapsus terminologico spiegato"
    }

    # Verifica che non sia una sottostringa esatta
    assert issue_dict["source_quote"] not in source_text

    result = disambiguate_science_issue(issue_dict, source_text)
    assert result["type"] == ScienceType.ERR_DOCENTE.value
    assert "ERR_RECONSTRUCTION" not in result.get("explanation", "")


def test_localize_claim_segment():
    from rt.pipeline.review import _localize_claim_segment
    from rt.core.models import Segment, DraftUnit

    seg1 = Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=60.0, start_formatted="00:00", end_formatted="01:00", text_raw="Primo segmento.")
    seg2 = Segment(id="seg_000002", index=2, start_seconds=60.0, end_seconds=120.0, start_formatted="01:00", end_formatted="02:00", text_raw="Secondo segmento.")
    seg3 = Segment(id="seg_000003", index=3, start_seconds=120.0, end_seconds=180.0, start_formatted="02:00", end_formatted="03:00", text_raw="Terzo segmento.")
    seg_by_id = {"seg_000001": seg1, "seg_000002": seg2, "seg_000003": seg3}

    unit_content = (
        "Inizio della lezione introducendo concetti base. " * 5 +
        "Nella parte centrale discutiamo di meccanismi intermedi. " * 5 +
        "Alla fine della lezione si afferma che l'enzima X inibisce il processo Y in modo irreversibile."
    )
    unit = DraftUnit(
        unit_id="U1",
        title="Unità Didattica",
        content=unit_content,
        start_segment_id="seg_000001",
        end_segment_id="seg_000003",
        source_segment_ids=["seg_000001", "seg_000002", "seg_000003"],
        key_concepts=[]
    )

    # 1. Claim vicino alla fine dell'unità -> stima seg_000003 (non il primo seg_000001)
    claim_end = "l'enzima X inibisce il processo Y"
    loc_seg = _localize_claim_segment(claim_end, unit, seg_by_id)
    assert loc_seg == "seg_000003"

    # 2. Claim non rintracciabile -> None
    loc_none = _localize_claim_segment("affermazione totalmente assente", unit, seg_by_id)
    assert loc_none is None

    # 3. Unità con un solo segmento sorgente -> quel segmento
    unit_single = DraftUnit(
        unit_id="U2",
        title="Unità Singolo Seg",
        content=unit_content,
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        key_concepts=[]
    )
    loc_single = _localize_claim_segment(claim_end, unit_single, seg_by_id)
    assert loc_single == "seg_000001"


