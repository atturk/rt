"""
Test per Voce 1: Il revisore consulta le fonti prima di segnalare.
"""

import os
from unittest.mock import MagicMock, patch

from rt.core.config import load_config
from rt.core.models import DraftUnit, ScienceIssue, ScienceSeverity, ScienceType
from rt.llm.client import LLMClient
from rt.llm.prompts import (
    ReviewFindingList,
    SecondPassReviewResponse,
    build_science_review_user_prompt,
)
from rt.pipeline.review import _review_unit
from rt.services.source_index import (
    IndexedPage,
    SourceIndex,
    SourcePageMatch,
    normalize_text,
)


def test_normalization_equals():
    """La normalizzazione rende uguali «w + 1» e «(w+1)»."""
    assert normalize_text("w + 1") == normalize_text("(w+1)")
    assert normalize_text("w + 1") == normalize_text("w+1")
    assert normalize_text("\\mathrm{w + 1}") == normalize_text("w+1")
    assert normalize_text("\\left(w + 1\\right)") == normalize_text("w+1")
    assert normalize_text("w + 1") != normalize_text("w - 1")


def test_search_attached_first_then_all():
    """La ricerca trova la pagina giusta prima tra quelle agganciate, poi in tutto il PDF."""
    index = SourceIndex.__new__(SourceIndex)
    index.lesson_dir = "/dummy"

    # Pagina 1 agganciata a unit 1.1, contiene testo comune
    # Pagina 2 agganciata a unit 1.1, contiene target "ottimizzazione vincolata"
    # Pagina 3 NON agganciata, contiene target "algoritmo simplex"
    page1 = IndexedPage(
        source_id="mat1",
        source_file="dispense.pdf",
        page_number=1,
        pdf_text="Introduzione al corso di matematica generale.",
        desc_text="",
        combined_text="Introduzione al corso di matematica generale.",
        tokens=["introduzione", "al", "corso", "di", "matematica", "generale"],
        attached_unit_ids={"1.1"},
    )
    page2 = IndexedPage(
        source_id="mat1",
        source_file="dispense.pdf",
        page_number=2,
        pdf_text="Teoria dell'ottimizzazione vincolata con passo w+1.",
        desc_text="",
        combined_text="Teoria dell'ottimizzazione vincolata con passo w+1.",
        tokens=["teoria", "dell", "ottimizzazione", "vincolata", "con", "passo", "w+1"],
        attached_unit_ids={"1.1"},
    )
    page3 = IndexedPage(
        source_id="mat1",
        source_file="dispense.pdf",
        page_number=3,
        pdf_text="Trattazione estesa dell'algoritmo simplex passo passo.",
        desc_text="",
        combined_text="Trattazione estesa dell'algoritmo simplex passo passo.",
        tokens=["trattazione", "estesa", "dell", "algoritmo", "simplex", "passo", "passo"],
        attached_unit_ids={"1.2"},
    )
    index.pages = [page1, page2, page3]

    # Ricerca di "ottimizzazione vincolata" per unit 1.1: trovata nelle pagine agganciate
    matches_attached = index.search("ottimizzazione vincolata", unit_id="1.1")
    assert len(matches_attached) > 0
    assert matches_attached[0].pagina == 2

    # Ricerca di "algoritmo simplex" per unit 1.1: non è agganciata a 1.1, quindi cerca in tutte le pagine
    matches_all = index.search("algoritmo simplex", unit_id="1.1")
    assert len(matches_all) > 0
    assert matches_all[0].pagina == 3


def test_first_pass_prompt_contains_transcript_and_materials(tmp_path):
    """Il prompt della prima passata contiene trascritto e materiali."""
    lesson_dir = str(tmp_path)
    unit = DraftUnit(
        unit_id="1.1",
        title="Unità di prova",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="Testo dell'unità con formula w+1.",
    )
    seg_by_id = {
        "seg_000001": MagicMock(id="seg_000001", text_raw="Il docente spiega che w+1 è l'indice.")
    }

    prompt = build_science_review_user_prompt(
        unit_id=unit.unit_id,
        rewritten_content=unit.content,
        source_context="[seg_000001] Il docente spiega che w+1 è l'indice.",
        materials_context="[Fonte: slide.pdf, pag. 5]\nFormula: w+1",
    )
    assert "TRASCRITTO DEL DOCENTE:" in prompt
    assert "Il docente spiega che w+1 è l'indice." in prompt
    assert "MATERIALI DEL DOCENTE:" in prompt
    assert "[Fonte: slide.pdf, pag. 5]" in prompt


def test_second_pass_definizione_del_corso_discards(tmp_path):
    """definizione_del_corso scarta la segnalazione."""
    lesson_dir = str(tmp_path)
    client = LLMClient(force_mock=True)

    unit = DraftUnit(
        unit_id="1.1",
        title="Unità di prova",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="Dato l'indice temporale w+1 per l'algoritmo.",
    )
    seg_by_id = {
        "seg_000001": MagicMock(id="seg_000001", text_raw="Spieghiamo l'indice w+1.", start_seconds=0.0, end_seconds=10.0)
    }

    mock_match = SourcePageMatch(
        fonte="slide.pdf",
        pagina=16,
        testo="Definizione: passo w+1.",
        da_descrizione=False,
        score=10.0,
    )

    with patch("rt.services.source_index.SourceIndex.search", return_value=[mock_match]), \
         patch.object(SourceIndex, "_build_index", lambda self: None), \
         patch("rt.pipeline.material_mapping.material_context_for_unit", return_value="[Fonte: slide.pdf, pag. 16]\nDefinizione: passo w+1."):

        # Il mock restituisce definizione_del_corso
        with patch.object(
            client,
            "call_structured",
            side_effect=[
                # Prima passata
                ReviewFindingList(
                    issues=[
                        {
                            "tipo": "concettuale",
                            "gravita": "alta",
                            "citazione": "w+1",
                            "motivazione": "L'indice corretto dovrebbe essere w-1.",
                            "sostituzione": "w-1",
                        }
                    ]
                ),
                # Seconda passata
                SecondPassReviewResponse(
                    classificazione="definizione_del_corso",
                    prova="slide 16: passo w+1",
                    nota=None,
                ),
            ],
        ):
            all_issues = []
            _review_unit(
                client=client,
                unit=unit,
                idx=1,
                total_units=1,
                seg_by_id=seg_by_id,
                st_issues_by_unit={},
                all_science_issues=all_issues,
                _cfg=load_config(),
                lesson_dir=lesson_dir,
                asr_llm=False,
                shadow_jev=True,
                skip_prefilter=True,
            )

            # La issue è stata scartata!
            assert len(all_issues) == 0


def test_second_pass_possibile_errore_docente_keeps_with_origin_no_fix(tmp_path):
    """possibile_errore_del_docente la tiene, con origine e senza correzione automatica."""
    lesson_dir = str(tmp_path)
    client = LLMClient(force_mock=True)

    unit = DraftUnit(
        unit_id="1.1",
        title="Elettromagnetismo",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="Tutta l'energia va nel condensatore.",
    )
    seg_by_id = {
        "seg_000001": MagicMock(id="seg_000001", text_raw="Tutta l'energia va nel condensatore.", start_seconds=0.0, end_seconds=10.0)
    }

    mock_match = SourcePageMatch(
        fonte="slide.pdf",
        pagina=8,
        testo="Circuito RC: energia nel condensatore.",
        da_descrizione=False,
        score=10.0,
    )

    with patch("rt.services.source_index.SourceIndex.search", return_value=[mock_match]), \
         patch.object(SourceIndex, "_build_index", lambda self: None), \
         patch("rt.pipeline.material_mapping.material_context_for_unit", return_value="[Fonte: slide.pdf, pag. 8]\nCircuito RC."):

        with patch.object(
            client,
            "call_structured",
            side_effect=[
                ReviewFindingList(
                    issues=[
                        {
                            "tipo": "concettuale",
                            "gravita": "alta",
                            "citazione": "Tutta l'energia va nel condensatore",
                            "motivazione": "Metà dell'energia viene dissipata nel resistore.",
                            "sostituzione": "Metà dell'energia va nel condensatore",
                        }
                    ]
                ),
                SecondPassReviewResponse(
                    classificazione="possibile_errore_del_docente",
                    prova="trascritto e slide 8",
                    nota="Il docente dice che tutta l'energia va nel condensatore; in generale vale che metà si dissipa nel resistore.",
                ),
            ],
        ):
            all_issues = []
            _review_unit(
                client=client,
                unit=unit,
                idx=1,
                total_units=1,
                seg_by_id=seg_by_id,
                st_issues_by_unit={},
                all_science_issues=all_issues,
                _cfg=load_config(),
                lesson_dir=lesson_dir,
                asr_llm=False,
                shadow_jev=True,
                skip_prefilter=True,
            )

            assert len(all_issues) == 1
            issue = all_issues[0]
            assert issue.origine == "docente"
            assert issue.suggested_fix is None  # Nessuna correzione automatica
            assert issue.prova == "trascritto e slide 8"
            assert issue.nota and "metà si dissipa nel resistore" in issue.nota
            assert issue.reason == "Metà dell'energia viene dissipata nel resistore."


def test_second_pass_requests_image_when_from_description(tmp_path):
    """se la prova viene solo dalla descrizione, viene chiesta l'immagine."""
    lesson_dir = str(tmp_path)
    client = LLMClient(force_mock=True)

    unit = DraftUnit(
        unit_id="1.1",
        title="Unità con figura",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="Il diagramma illustra il ciclo.",
    )
    seg_by_id = {
        "seg_000001": MagicMock(id="seg_000001", text_raw="Vediamo il diagramma.", start_seconds=0.0, end_seconds=10.0)
    }

    mock_match = SourcePageMatch(
        fonte="foto_lavagna.jpg",
        pagina=1,
        testo="Diagramma con ciclo termodinamico",
        da_descrizione=True,  # Match proveniente solo da descrizione/OCR
        score=10.0,
    )

    recorded_calls = []

    def mock_call_structured(**kwargs):
        recorded_calls.append(kwargs)
        if kwargs.get("response_model") == ReviewFindingList:
            return ReviewFindingList(
                issues=[
                    {
                        "tipo": "concettuale",
                        "gravita": "media",
                        "citazione": "diagramma",
                        "motivazione": "Possibile incongruenza nel diagramma.",
                        "sostituzione": "schema",
                    }
                ]
            )
        return SecondPassReviewResponse(
            classificazione="errore_della_rielaborazione",
            prova="foto_lavagna pag. 1",
            nota=None,
        )

    with patch("rt.services.source_index.SourceIndex.search", return_value=[mock_match]), \
         patch.object(SourceIndex, "_build_index", lambda self: None), \
         patch.object(SourceIndex, "render_page_png", return_value=b"fake-png-bytes"), \
         patch("rt.pipeline.material_mapping.material_context_for_unit", return_value=""):

        with patch.object(client, "call_structured", side_effect=mock_call_structured):
            all_issues = []
            _review_unit(
                client=client,
                unit=unit,
                idx=1,
                total_units=1,
                seg_by_id=seg_by_id,
                st_issues_by_unit={},
                all_science_issues=all_issues,
                _cfg=load_config(),
                lesson_dir=lesson_dir,
                asr_llm=False,
                shadow_jev=True,
                skip_prefilter=True,
            )

            # La seconda chiamata structured deve aver ricevuto image_data_url e usato job_name review!
            assert len(recorded_calls) == 2
            second_call = recorded_calls[1]
            assert second_call.get("job_name") == "review"
            assert second_call.get("image_data_url") is not None
            assert len(second_call["image_data_url"]) > 0
            assert "data:image/png;base64," in second_call["image_data_url"][0]


def test_second_pass_image_failure_falls_back_without_image(tmp_path):
    """se la chiamata con immagine fallisce, prosegue senza immagine con job_name review."""
    lesson_dir = str(tmp_path)
    client = LLMClient(force_mock=True)

    unit = DraftUnit(
        unit_id="1.1",
        title="Unità con figura",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="Il diagramma illustra il ciclo.",
    )
    seg_by_id = {
        "seg_000001": MagicMock(id="seg_000001", text_raw="Vediamo il diagramma.", start_seconds=0.0, end_seconds=10.0)
    }

    mock_match = SourcePageMatch(
        fonte="foto_lavagna.jpg",
        pagina=1,
        testo="Diagramma con ciclo termodinamico",
        da_descrizione=True,
        score=10.0,
    )

    recorded_calls = []

    def mock_call_structured(**kwargs):
        recorded_calls.append(kwargs)
        if kwargs.get("response_model") == ReviewFindingList:
            return ReviewFindingList(
                issues=[
                    {
                        "tipo": "concettuale",
                        "gravita": "media",
                        "citazione": "diagramma",
                        "motivazione": "Possibile incongruenza nel diagramma.",
                        "sostituzione": "schema",
                    }
                ]
            )
        if kwargs.get("image_data_url"):
            raise RuntimeError("Vision model call failed")
        return SecondPassReviewResponse(
            classificazione="errore_della_rielaborazione",
            prova="foto_lavagna pag. 1",
            nota=None,
        )

    with patch("rt.services.source_index.SourceIndex.search", return_value=[mock_match]), \
         patch.object(SourceIndex, "_build_index", lambda self: None), \
         patch.object(SourceIndex, "render_page_png", return_value=b"fake-png-bytes"), \
         patch("rt.pipeline.material_mapping.material_context_for_unit", return_value=""):

        with patch.object(client, "call_structured", side_effect=mock_call_structured):
            all_issues = []
            _review_unit(
                client=client,
                unit=unit,
                idx=1,
                total_units=1,
                seg_by_id=seg_by_id,
                st_issues_by_unit={},
                all_science_issues=all_issues,
                _cfg=load_config(),
                lesson_dir=lesson_dir,
                asr_llm=False,
                shadow_jev=True,
                skip_prefilter=True,
            )

            # 3 chiamate: finding list, fallita con review con immagini, fallback con review senza immagini
            assert len(recorded_calls) == 3
            assert recorded_calls[1].get("job_name") == "review"
            assert recorded_calls[1].get("image_data_url") is not None
            assert recorded_calls[2].get("job_name") == "review"
            assert recorded_calls[2].get("image_data_url") is None
            assert len(all_issues) == 1
