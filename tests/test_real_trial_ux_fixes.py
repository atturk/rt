import os
import json

from rt.core.models import SegmentsData, Segment, Draft, DraftUnit
from rt.pipeline.review import run_review
from rt.llm.prompts import SCIENCE_REVIEW_SYSTEM_PROMPT, build_science_review_user_prompt


def _setup_test_lesson(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="test.wav",
        total_duration=120.0,
        segment_count=3,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="La biochimica cellulare e la glicolisi."),
            Segment(id="seg_000002", index=2, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Il cofattore magnesio e l'esochinasi."),
            Segment(id="seg_000003", index=3, start_seconds=20.0, end_seconds=30.0, start_formatted="00:20", end_formatted="00:30", text_raw="La fosforilazione del glucosio.")
        ]
    )
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Introduzione alla glicolisi",
                content="La biochimica cellulare analizza le reazioni enzimatiche dei processi metabolici fondamentali negli organismi viventi.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000003",
                source_segment_ids=["seg_000001", "seg_000002", "seg_000003"],
                key_concepts=["biochimica", "glicolisi"]
            )
        ]
    )
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    from rt.core.models import Outline, OutlineMacro, OutlineUnit
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione di Biochimica",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Introduzione",
                units=[
                    OutlineUnit(
                        id="1.1",
                        title="Introduzione alla glicolisi",
                        start_segment_id="seg_000001",
                        end_segment_id="seg_000003",
                        key_concepts=["biochimica", "glicolisi"]
                    )
                ]
            )
        ]
    )
    with open(os.path.join(lesson_dir, "outline.json"), "w", encoding="utf-8") as f:
        json.dump(outline.model_dump(mode="json"), f)

    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("fase_corrente: draft_validato\nmateria: BIOCHIMICA\ndata: 2026-09-08\n")


def test_science_review_prompt_has_no_raw_transcript_access_and_ignores_asr_artifacts():
    """Il critic scientifico non riceve più la trascrizione grezza (causa di confusione
    reale riscontrata: citava frammenti ASR grezzi come se fossero affermazioni del
    docente). Il prompt deve dirglielo esplicitamente e istruirlo a ignorare anomalie
    isolate che potrebbero essere artefatti ASR non ancora corretti."""
    assert "Non hai accesso alla trascrizione grezza originale né all'audio" in SCIENCE_REVIEW_SYSTEM_PROMPT
    assert "review ASR" in SCIENCE_REVIEW_SYSTEM_PROMPT
    assert "source_quote" not in SCIENCE_REVIEW_SYSTEM_PROMPT

    import inspect
    sig = inspect.signature(build_science_review_user_prompt)
    assert "source_segments_text" not in sig.parameters


def test_mock_generation_rich_science(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    _setup_test_lesson(lesson_dir)

    res_sci = run_review(lesson_dir, force=True, force_mock=True)
    assert res_sci["total_science_issues"] == 10
    assert res_sci["concettuale_issues"] == 10


def test_mock_generation_bounded_across_many_units(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    _setup_test_lesson(lesson_dir)

    draft_path = os.path.join(lesson_dir, "draft.json")
    with open(draft_path, "r", encoding="utf-8") as f:
        draft_data = json.load(f)
    template_unit = draft_data["units"][0]
    draft_data["units"] = []
    for i in range(1, 13):
        unit = dict(template_unit)
        unit["unit_id"] = f"{i}.1"
        draft_data["units"].append(unit)
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(draft_data, f)

    res_sci = run_review(lesson_dir, force=True, force_mock=True)
    assert res_sci["total_science_issues"] == 10, (
        f"Atteso ~10 issue scientifiche totali indipendentemente dal numero di unità "
        f"(12 in questo test), trovate {res_sci['total_science_issues']}"
    )


