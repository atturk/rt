import os
from unittest.mock import MagicMock, patch
import pytest

from rt.core.sources import add_source, load_sources, update_source
from rt.core.source_selection import set_order
from rt.llm.client import LLMClient
from rt.llm.prompts import (
    SECOND_PASS_REVIEW_SYSTEM_PROMPT,
    SecondPassReviewResponse,
    build_science_review_user_prompt,
    build_second_pass_review_prompt,
)
from rt.core.models import DraftUnit, ScienceIssue, ScienceSeverity, ScienceType
from rt.pipeline.material_mapping import MaterialContext, material_context_for_unit
from rt.pipeline.review import _apply_second_pass_review, run_jev_task_b
from rt.services.source_index import SourcePageMatch


def test_prompts_with_normal_sources_match_snapshot():
    """Con sole fonti normali i prompt di prima passata, seconda passata e JEV sono uguali allo snapshot."""
    # Prima passata
    normal_ctx = MaterialContext(
        "[Fonte: slides.pdf, pag. 5]\nTesto della slide normale.",
        by_reliability={"normale": "[Fonte: slides.pdf, pag. 5]\nTesto della slide normale."},
    )
    prompt_pass1 = build_science_review_user_prompt(
        unit_id="1.1",
        rewritten_content="Contenuto rielaborato dell'unità.",
        source_context="Segmenti ASR del docente.",
        materials_context=normal_ctx,
    )
    assert "\n\n---\nMATERIALI DEL DOCENTE:\n[Fonte: slides.pdf, pag. 5]\nTesto della slide normale.\n---" in prompt_pass1
    assert "SLIDE E MATERIALI DEL DOCENTE (affidabilità alta)" not in prompt_pass1
    assert "APPUNTI DELLO STUDENTE" not in prompt_pass1

    # Seconda passata
    normal_match = SourcePageMatch(
        fonte="slides.pdf",
        pagina=5,
        testo="Testo della slide normale.",
        da_descrizione=False,
        score=10.0,
        affidabilita="normale",
    )
    prompt_pass2 = build_second_pass_review_prompt(
        claim="Claim da verificare",
        reason="Motivazione",
        suggested_fix=None,
        matched_pages_text=f"[Fonte: {normal_match.fonte}, pag. {normal_match.pagina}]\n{normal_match.testo}",
        source_context="Segmenti ASR",
    )
    assert "[Fonte: slides.pdf, pag. 5]\nTesto della slide normale." in prompt_pass2
    assert "affidabilità" not in prompt_pass2

    # JEV
    unit = DraftUnit(
        unit_id="1.1",
        title="Unità 1.1",
        start_segment_id="seg_1",
        end_segment_id="seg_1",
        source_segment_ids=["seg_1"],
        content="Contenuto rielaborato",
    )
    with patch("rt.pipeline.review.call_jev") as mock_call_jev:
        mock_resp = MagicMock()
        mock_resp.answers = {}
        mock_call_jev.return_value = mock_resp
        jev_cfg = MagicMock(model="mock", credential="mock", base_url="mock", timeout_seconds=10)
        run_jev_task_b(unit, "Segmenti grezzi", jev_cfg, "/tmp/fake_dir", materials_context=normal_ctx)
        assert mock_call_jev.called
        state = mock_call_jev.call_args[1]["state"]
        assert "\n\n---\n\nMATERIALI DEL DOCENTE (slide, foto):\n[Fonte: slides.pdf, pag. 5]\nTesto della slide normale." in state
        assert "SLIDE E MATERIALI DEL DOCENTE (affidabilità alta)" not in state
        assert "APPUNTI DELLO STUDENTE" not in state


def test_source_reliability_save_read_reorder(tmp_path):
    """Il campo affidabilita si salva, si legge e resta dopo il riordino."""
    (tmp_path / "info.yaml").write_text("materia: Test\n", encoding="utf-8")
    lesson_dir = str(tmp_path)

    # 1. Aggiunta con affidabilità alta
    s1 = add_source(lesson_dir, "materiale", "slide.pdf", b"pdf content", ordine=1, affidabilita="alta")
    assert s1.affidabilita == "alta"

    # 2. Aggiunta appunti con affidabilità bassa
    s2 = add_source(lesson_dir, "appunti", "appunti.txt", b"appunti studente", ordine=2, affidabilita="bassa")
    assert s2.affidabilita == "bassa"

    # 3. Aggiunta senza affidabilità (default None -> normale)
    s3 = add_source(lesson_dir, "materiale", "doc.pdf", b"doc content", ordine=3)
    assert s3.affidabilita is None

    # Verifica lettura da disco
    loaded = load_sources(lesson_dir)
    assert len(loaded) == 3
    assert loaded[0].affidabilita == "alta"
    assert loaded[1].affidabilita == "bassa"
    assert loaded[2].affidabilita is None

    # 4. Modifica affidabilità
    update_source(lesson_dir, s3.id, affidabilita="alta")
    loaded_after_update = load_sources(lesson_dir)
    assert loaded_after_update[2].affidabilita == "alta"

    # 5. Riordino
    set_order(lesson_dir, [s3.id, s1.id, s2.id])
    reordered = load_sources(lesson_dir)
    assert [s.id for s in reordered] == [s3.id, s1.id, s2.id]
    assert reordered[0].affidabilita == "alta"
    assert reordered[1].affidabilita == "alta"
    assert reordered[2].affidabilita == "bassa"


def test_labels_with_high_and_low_sources():
    """Una fonte alta e una bassa producono le etichette giuste nei tre prompt."""
    mixed_ctx = MaterialContext(
        "[Fonte: docente.pdf, pag. 1]\nDocente\n\n[Fonte: studente.pdf, pag. 2]\nStudente",
        by_reliability={
            "alta": "[Fonte: docente.pdf, pag. 1]\nDocente",
            "bassa": "[Fonte: studente.pdf, pag. 2]\nStudente",
        },
    )

    # 1. Prima passata
    prompt_pass1 = build_science_review_user_prompt(
        unit_id="1.1",
        rewritten_content="Contenuto rielaborato",
        materials_context=mixed_ctx,
    )
    assert "SLIDE E MATERIALI DEL DOCENTE (affidabilità alta):\n[Fonte: docente.pdf, pag. 1]\nDocente" in prompt_pass1
    assert "APPUNTI DELLO STUDENTE (affidabilità bassa: possono contenere errori):\n[Fonte: studente.pdf, pag. 2]\nStudente" in prompt_pass1
    assert "MATERIALI DEL DOCENTE:\n" not in prompt_pass1

    # 2. Seconda passata
    matches = [
        SourcePageMatch(fonte="docente.pdf", pagina=1, testo="Docente", da_descrizione=False, score=10.0, affidabilita="alta"),
        SourcePageMatch(fonte="studente.pdf", pagina=2, testo="Studente", da_descrizione=False, score=5.0, affidabilita="bassa"),
    ]
    def _match_label(m: SourcePageMatch) -> str:
        rel = getattr(m, "affidabilita", "normale") or "normale"
        if rel in ("alta", "bassa"):
            return f"[Fonte: {m.fonte}, pag. {m.pagina}, affidabilità {rel}]"
        return f"[Fonte: {m.fonte}, pag. {m.pagina}]"

    matched_text = "\n\n".join(f"{_match_label(m)}\n{m.testo}" for m in matches)
    prompt_pass2 = build_second_pass_review_prompt(
        claim="Claim",
        reason="Reason",
        suggested_fix=None,
        matched_pages_text=matched_text,
        source_context="Context",
    )
    assert "[Fonte: docente.pdf, pag. 1, affidabilità alta]\nDocente" in prompt_pass2
    assert "[Fonte: studente.pdf, pag. 2, affidabilità bassa]\nStudente" in prompt_pass2

    # 3. JEV
    unit = DraftUnit(
        unit_id="1.1",
        title="Unità 1.1",
        start_segment_id="seg_1",
        end_segment_id="seg_1",
        source_segment_ids=["seg_1"],
        content="Contenuto rielaborato",
    )
    with patch("rt.pipeline.review.call_jev") as mock_call_jev:
        mock_resp = MagicMock()
        mock_resp.answers = {}
        mock_call_jev.return_value = mock_resp
        jev_cfg = MagicMock(model="mock", credential="mock", base_url="mock", timeout_seconds=10)
        run_jev_task_b(unit, "Segmenti grezzi", jev_cfg, "/tmp/fake_dir", materials_context=mixed_ctx)
        assert mock_call_jev.called
        state = mock_call_jev.call_args[1]["state"]
        assert "SLIDE E MATERIALI DEL DOCENTE (affidabilità alta):\n[Fonte: docente.pdf, pag. 1]\nDocente" in state
        assert "APPUNTI DELLO STUDENTE (affidabilità bassa: possono contenere errori):\n[Fonte: studente.pdf, pag. 2]\nStudente" in state


def test_second_pass_low_reliability_alone_does_not_discard(tmp_path):
    """Seconda passata mock: con una sola pagina bassa come prova l'esito non è «definizione_del_corso»."""
    lesson_dir = str(tmp_path)
    client = LLMClient(force_mock=True)

    issue = ScienceIssue(
        id="iss_1",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        claim="Affermazione errata",
        reason="Motivo dell'errore",
        status="pending",
    )
    unit = DraftUnit(
        unit_id="1.1",
        title="Unità di prova",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="Contenuto unità",
    )

    mock_match = SourcePageMatch(
        fonte="appunti_studente.pdf",
        pagina=3,
        testo="Appunti dello studente con la convenzione.",
        da_descrizione=False,
        score=10.0,
        affidabilita="bassa",
    )

    with patch("rt.services.source_index.SourceIndex.search", return_value=[mock_match]), \
         patch("rt.services.source_index.SourceIndex._build_index", lambda self: None), \
         patch.object(
             client,
             "call_structured",
             return_value=SecondPassReviewResponse(
                 classificazione="definizione_del_corso",
                 prova="appunti 3: convenzione",
                 nota=None,
             ),
         ):
        final_issues = _apply_second_pass_review(
            client=client,
            findings=[issue],
            unit=unit,
            macro_id="",
            source_context="",
            lesson_dir=lesson_dir,
            unit_label="unit 1/1",
        )

        # Non deve essere scartata: resta nella lista
        assert len(final_issues) == 1
        assert final_issues[0].nota == "La conferma viene solo dagli appunti."
