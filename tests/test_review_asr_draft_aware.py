"""
tests/test_review_asr_draft_aware.py
La review ASR ora vede anche il draft (non solo la trascrizione grezza): il modello di
rewrite può aver già corretto, parzialmente o del tutto, le ambiguità fonetiche per conto
proprio. Le issue riguardano il testo come compare ORA nel draft, non la trascrizione
grezza in sé (bug reale riscontrato: un reject applicato a un'issue ASR il cui candidate
combaciava per puro caso col testo già corretto dal rewrite ha sostituito un testo corretto
con l'errore ASR originale — vedi tests/test_ledger.py per il fix su quel fronte; qui si
copre il fatto che la review ASR ora ha visibilità sul draft per evitare di generare quelle
issue "fantasma" fin dall'inizio).
"""
import os
import json
import pytest
from unittest.mock import patch

from rt.core.models import SegmentsData, Segment, Draft, DraftUnit
from rt.pipeline.rewrite import save_draft
from rt.pipeline.review_asr import run_review_asr
from rt.llm.prompts import build_asr_review_user_prompt
from rt.core.idempotency import UPSTREAM_DEPENDENCIES


def test_build_asr_review_user_prompt_includes_draft_context_block():
    prompt = build_asr_review_user_prompt("[seg_000001] testo grezzo", "[Unità 1.1 - Titolo]\ntesto del draft")
    assert "TRASCRIZIONE GREZZA ASR" in prompt
    assert "testo grezzo" in prompt
    assert "DRAFT RIELABORATO" in prompt
    assert "testo del draft" in prompt


def test_build_asr_review_user_prompt_without_draft_has_explicit_fallback():
    prompt = build_asr_review_user_prompt("[seg_000001] testo grezzo")
    assert "Nessun draft disponibile" in prompt


def test_review_asr_depends_on_rewrite_in_dependency_graph():
    assert "rewrite" in UPSTREAM_DEPENDENCIES["review_asr"]


@pytest.fixture
def lesson_with_draft(tmp_path):
    lesson_dir = str(tmp_path)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("data: '2026-09-10'\nmateria: TEST\nargomenti: Prova\nfase_corrente: draft_validato\nstato: draft_validato\n")
    segs = [
        Segment(id=f"seg_{i:06d}", index=i, start_seconds=float(i * 10), end_seconds=float(i * 10 + 8),
                start_formatted=f"00:{i*10:02d}", end_formatted=f"00:{i*10+8:02d}",
                text_raw=f"Testo grezzo del segmento {i} con università menzionata.")
        for i in range(1, 3)
    ]
    seg_data = SegmentsData(schema_version="1.0", audio_file="a.mp3", audio_duration_seconds=20.0, segments=segs)
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    draft = Draft(schema_version="1.0", units=[
        DraftUnit(
            unit_id="1.1", title="Unità di prova",
            start_segment_id="seg_000001", end_segment_id="seg_000002",
            source_segment_ids=["seg_000001", "seg_000002"],
            content="Il testo del draft usa già la parola sequenze corretta, non l'errore ASR.",
        )
    ])
    save_draft(draft, lesson_dir)
    return lesson_dir


def test_run_review_asr_prompt_includes_both_raw_and_draft_text(lesson_with_draft):
    captured = {}

    def fake_call_structured(self, prompt, system_prompt, response_model, **kwargs):
        captured["prompt"] = prompt
        class Empty:
            issues = []
        return Empty()

    with patch("rt.llm.client.LLMClient.call_structured", fake_call_structured):
        run_review_asr(lesson_with_draft, force_mock=False, batch_size=40)

    prompt = captured["prompt"]
    assert "università menzionata" in prompt  # trascrizione grezza
    assert "Unità 1.1 - Unità di prova" in prompt  # contesto draft
    assert "già la parola sequenze corretta" in prompt  # contenuto reale del draft


def test_run_review_asr_requires_draft_to_exist(tmp_path):
    """review_asr dipende ora da rewrite: senza draft.json deve fallire con un errore
    chiaro, non proseguire silenziosamente ignorando il draft."""
    lesson_dir = str(tmp_path)
    segs = [Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=8.0,
                     start_formatted="00:00", end_formatted="00:08", text_raw="Testo.")]
    seg_data = SegmentsData(schema_version="1.0", audio_file="a.mp3", audio_duration_seconds=8.0, segments=segs)
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    with pytest.raises(FileNotFoundError):
        run_review_asr(lesson_dir, force_mock=True)
