"""
Unit test per la revisione multi-turno cache-friendly e l'auto-repair dell'outline.
"""

import pytest
from unittest.mock import MagicMock, patch
from rt.core.models import Outline, OutlineMacro, OutlineUnit
from rt.pipeline.validator import ValidationError
from rt.pipeline.outline import _generate_validated_outline, run_outline_revision
from rt.llm.prompts import OUTLINE_SYSTEM_PROMPT


def test_generate_validated_outline_auto_repair(tmp_path):
    """Verifica che _generate_validated_outline tenti l'auto-repair quando la validazione di dominio fallisce."""
    mock_client = MagicMock()

    # Primo tentativo: outline non valida (start_segment_id invalid / out of order)
    bad_outline = Outline(
        schema_version="1.0",
        lesson_title="Test Bad Outline",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Sec 1",
                units=[
                    OutlineUnit(id="1.1", title="U1", start_segment_id="seg_000010", end_segment_id="seg_000005", key_concepts=[])
                ]
            )
        ]
    )

    # Secondo tentativo: outline valida
    good_outline = Outline(
        schema_version="1.0",
        lesson_title="Test Good Outline",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Sec 1",
                units=[
                    OutlineUnit(id="1.1", title="U1", start_segment_id="seg_000001", end_segment_id="seg_000005", key_concepts=[])
                ]
            )
        ]
    )

    mock_client.call_structured.side_effect = [bad_outline, good_outline]

    segments_data = MagicMock()
    mock_report = {"valid": True}

    with patch("rt.pipeline.outline.validate_outline") as mock_validate:
        mock_validate.side_effect = [
            ValidationError("Unit 1.1 has start_segment_id index > end_segment_id index"),
            mock_report
        ]

        outline, report = _generate_validated_outline(
            client=mock_client,
            system_prompt=OUTLINE_SYSTEM_PROMPT,
            base_history=[],
            final_user_prompt="Initial prompt",
            segments_data=segments_data,
            lesson_dir=str(tmp_path),
            max_repair_attempts=2
        )

        assert outline.lesson_title == "Test Good Outline"
        assert report == mock_report
        assert mock_client.call_structured.call_count == 2

        # Verifica history passato al secondo tentativo
        second_call_kwargs = mock_client.call_structured.call_args_list[1][1]
        assert "history" in second_call_kwargs
        history = second_call_kwargs["history"]
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Initial prompt"
        assert history[1]["role"] == "assistant"
