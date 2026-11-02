"""
Test per Voce 2: La deriva della rielaborazione tiene conto dei materiali.
"""

from unittest.mock import MagicMock, patch

from rt.core.config import load_config, classifier_jev
from rt.core.models import DraftUnit
from rt.pipeline.review import run_jev_task_b


def test_task_b_state_with_materials(tmp_path):
    """Con un materiale che contiene la sigla usata nel testo, lo state inviato al classificatore la contiene."""
    lesson_dir = str(tmp_path)
    unit = DraftUnit(
        unit_id="1.1",
        title="Unità con sigla",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="In questa lezione analizziamo il protocollo RTPL per le reti.",
    )
    source_context = "[seg_000001] Parliamo di protocolli di rete avanzati."
    materials_context = "[Fonte: slide.pdf, pag. 4]\nProtocollo RTPL: Real-Time Packet Layer"

    cfg = load_config()
    jev_cfg = classifier_jev(cfg, "drift")

    called_state = None

    def mock_call_jev(state, **kwargs):
        nonlocal called_state
        called_state = state
        resp = MagicMock()
        resp.answers = {"unsupported_content": MagicMock(type="noul", noul=0.1)}
        return resp

    with patch("rt.pipeline.review.call_jev", side_effect=mock_call_jev):
        run_jev_task_b(
            unit,
            source_context,
            jev_cfg,
            lesson_dir,
            materials_context=materials_context,
            force=True,
        )

    assert called_state is not None
    assert "SEGMENTI GREZZI ASR:" in called_state
    assert "TESTO RIELABORATO:" in called_state
    assert "MATERIALI DEL DOCENTE (slide, foto):" in called_state
    assert "RTPL" in called_state
    assert "[Fonte: slide.pdf, pag. 4]" in called_state


def test_task_b_state_without_materials(tmp_path):
    """Lezione senza materiali: lo state resta come oggi."""
    lesson_dir = str(tmp_path)
    unit = DraftUnit(
        unit_id="1.1",
        title="Unità base",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="Testo rielaborato senza materiali.",
    )
    source_context = "[seg_000001] Testo parlato originale."

    cfg = load_config()
    jev_cfg = classifier_jev(cfg, "drift")

    called_state = None

    def mock_call_jev(state, **kwargs):
        nonlocal called_state
        called_state = state
        resp = MagicMock()
        resp.answers = {"unsupported_content": MagicMock(type="noul", noul=0.1)}
        return resp

    with patch("rt.pipeline.review.call_jev", side_effect=mock_call_jev):
        run_jev_task_b(
            unit,
            source_context,
            jev_cfg,
            lesson_dir,
            materials_context="",
            force=True,
        )

    expected_state = f"SEGMENTI GREZZI ASR:\n{source_context}\n\n---\n\nTESTO RIELABORATO:\n{unit.content}"
    assert called_state == expected_state
    assert "MATERIALI DEL DOCENTE" not in called_state
