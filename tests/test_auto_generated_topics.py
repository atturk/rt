"""
tests/test_auto_generated_topics.py
Test per la generazione automatica degli argomenti di lezione via LLM (Task 80)
quando omessi dall'utente in fase di ingest, e loro propagazione in build e info.yaml.
"""
import json
import os
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from rt.core.models import (
    Draft,
    DraftUnit,
    LessonTopics,
    Outline,
    OutlineMacro,
    OutlineUnit,
    Segment,
    SegmentsData,
)
from rt.core.state import read_info_yaml
from rt.pipeline.build import render_pre_elaborato_md, render_rielaborato_md, run_build
from rt.pipeline.outline import load_outline, run_outline


def _create_mock_lesson(
    lesson_dir: str,
    argomenti: str = "",
    generated_topics: Optional[List[str]] = None,
) -> None:
    state_dir = os.path.join(lesson_dir, "_state")
    os.makedirs(state_dir, exist_ok=True)

    info_content = f"data: '2026-03-14'\nmateria: BIOCHIMICA\nargomenti: '{argomenti}'\n"
    with open(os.path.join(state_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    seg1 = Segment(
        id="seg_000001",
        index=1,
        start_seconds=0.0,
        end_seconds=10.0,
        start_formatted="00:00",
        end_formatted="00:10",
        text_raw="Introduzione alla biochimica cellulare e ai processi metabolici.",
    )
    seg2 = Segment(
        id="seg_000002",
        index=2,
        start_seconds=10.0,
        end_seconds=20.0,
        start_formatted="00:10",
        end_formatted="00:20",
        text_raw="Adattamento cellulare e vie enzimatiche principali.",
    )
    segments_data = SegmentsData(schema_version="1.0", segments=[seg1, seg2])
    with open(os.path.join(state_dir, "segments.json"), "w", encoding="utf-8") as f:
        f.write(segments_data.model_dump_json(indent=2))

    outline = Outline(
        schema_version="1.0",
        lesson_title="Biochimica Cellulare",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Basi del metabolismo",
                units=[
                    OutlineUnit(
                        id="1.1",
                        title="Introduzione ai processi",
                        start_segment_id="seg_000001",
                        end_segment_id="seg_000002",
                        key_concepts=["Metabolismo", "Enzimi"],
                    )
                ],
            )
        ],
        generated_topics=generated_topics,
    )
    with open(os.path.join(state_dir, "outline.json"), "w", encoding="utf-8") as f:
        f.write(outline.model_dump_json(indent=2))

    draft = Draft(
        schema_version="1.0",
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Introduzione ai processi",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
                content="La biochimica cellulare studia i processi metabolici e le reazioni enzimatiche.",
            )
        ],
    )
    with open(os.path.join(state_dir, "draft.json"), "w", encoding="utf-8") as f:
        f.write(draft.model_dump_json(indent=2))


class TestOutlineTopicsAutoGeneration:
    def test_run_outline_auto_generates_topics_when_argomenti_empty(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson_empty_topics")
        _create_mock_lesson(lesson_dir, argomenti="")

        base_outline = Outline(
            schema_version="1.0",
            lesson_title="Biochimica Generale",
            macro_sections=[
                OutlineMacro(
                    id="1",
                    title="Sezione 1",
                    units=[
                        OutlineUnit(
                            id="1.1",
                            title="Unità 1",
                            start_segment_id="seg_000001",
                            end_segment_id="seg_000002",
                            key_concepts=["Concetto"],
                        )
                    ],
                )
            ],
        )
        mock_topics = LessonTopics(
            argomenti=[
                "Metabolismo glucidico",
                "Vie enzimatiche",
                "Regolazione allosterica",
            ]
        )

        with patch("rt.pipeline.outline.LLMClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.call_structured.side_effect = [base_outline, mock_topics]

            res = run_outline(lesson_dir, force=True)
            assert res["status"] == "outline_validated"

            assert mock_client.call_structured.call_count == 2
            # Seconda chiamata per LessonTopics
            second_call_kwargs = mock_client.call_structured.call_args_list[1][1]
            assert second_call_kwargs["response_model"] == LessonTopics
            assert second_call_kwargs["job_name"] == "outline"

            saved_outline = load_outline(lesson_dir)
            assert saved_outline.generated_topics == [
                "Metabolismo glucidico",
                "Vie enzimatiche",
                "Regolazione allosterica",
            ]

    def test_run_outline_skips_topics_generation_when_argomenti_non_empty(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson_with_topics")
        _create_mock_lesson(lesson_dir, argomenti="Argomento Esplicito Utente")

        base_outline = Outline(
            schema_version="1.0",
            lesson_title="Biochimica Generale",
            macro_sections=[
                OutlineMacro(
                    id="1",
                    title="Sezione 1",
                    units=[
                        OutlineUnit(
                            id="1.1",
                            title="Unità 1",
                            start_segment_id="seg_000001",
                            end_segment_id="seg_000002",
                            key_concepts=["Concetto"],
                        )
                    ],
                )
            ],
        )

        with patch("rt.pipeline.outline.LLMClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.call_structured.return_value = base_outline

            res = run_outline(lesson_dir, force=True)
            assert res["status"] == "outline_validated"

            # 1 sola chiamata LLM per l'outline, nessuna per i topics
            assert mock_client.call_structured.call_count == 1

            saved_outline = load_outline(lesson_dir)
            assert saved_outline.generated_topics is None


class TestBuildGeneratedTopicsIntegration:
    def test_run_build_propagates_generated_topics_to_md_and_info_yaml(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson_build_topics")
        _create_mock_lesson(
            lesson_dir,
            argomenti="",
            generated_topics=["Ciclo di Krebs", "Fosforilazione ossidativa", "ATP sintasi"],
        )

        run_build(lesson_dir, force=True, rename_folder=False)

        # Verifica info.yaml
        info = read_info_yaml(os.path.join(lesson_dir, "_state", "info.yaml"))
        assert info.get("argomenti") == "Ciclo di Krebs, Fosforilazione ossidativa, ATP sintasi"

        # Verifica rielaborato.md frontmatter
        with open(os.path.join(lesson_dir, "_state", "rielaborato.md"), "r", encoding="utf-8") as f:
            rielab_content = f.read()

        assert "argomenti:" in rielab_content
        assert "- 'Ciclo di Krebs'" in rielab_content
        assert "- 'Fosforilazione ossidativa'" in rielab_content
        assert "- 'ATP sintasi'" in rielab_content

    def test_run_build_preserves_user_topics(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson_user_topics")
        _create_mock_lesson(
            lesson_dir,
            argomenti="Argomento Scritto a Mano",
            generated_topics=["Topic Generato 1", "Topic Generato 2"],
        )

        run_build(lesson_dir, force=True, rename_folder=False)

        info = read_info_yaml(os.path.join(lesson_dir, "_state", "info.yaml"))
        assert info.get("argomenti") == "Argomento Scritto a Mano"

        with open(os.path.join(lesson_dir, "_state", "rielaborato.md"), "r", encoding="utf-8") as f:
            rielab_content = f.read()

        assert "- 'Argomento Scritto a Mano'" in rielab_content
        assert "Topic Generato 1" not in rielab_content
