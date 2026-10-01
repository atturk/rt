import io
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rt.core.config import EnrichmentConfig, RTConfig
from rt.core.idempotency import compute_source_fingerprint
from rt.llm.jev_client import JevNoulAnswer, JevChoiceAnswer
from rt.services import enrichment_service as es


@pytest.fixture
def lesson(tmp_path, monkeypatch):
    rows = [{"id": "1.1", "macro_id": "1", "title": "Matrice", "content": "Matrice A: prima riga [1, 1, 0]."},
            {"id": "2.1", "macro_id": "2", "title": "Anatomia", "content": "La struttura anatomica descritta."}]
    monkeypatch.setattr(es, "units", lambda path: rows)
    cfg = RTConfig()
    monkeypatch.setattr(es, "load_config", lambda: cfg)
    return str(tmp_path), rows, cfg


def test_cap_is_maximum_not_quota_and_allows_multiple_per_unit(lesson):
    path, rows, cfg = lesson
    state = es.EnrichmentState(elements=[es.Element(id=str(i), unit_id="1.1", kind=kind,
        title=kind, description="Idea", prompt="Prompt", utility=score)
        for i, (kind, score) in enumerate([("visualization", .95), ("infographic", .9), ("visualization", .3)])])
    es._rank(state, cfg.enrichment, len(rows))
    assert [e.status for e in state.elements] == ["suggestion", "suggestion", "suppressed"]
    state.cap = es.Cap(mode="fixed", number=1)
    es._rank(state, cfg.enrichment, len(rows))
    assert sum(e.status == "suggestion" for e in state.elements) == 1
    state.elements[0].status = "dismissed"
    state.cap = es.Cap(mode="off")
    es._rank(state, cfg.enrichment, len(rows))
    assert state.elements[0].status == "dismissed"  # a new cap never reopens it
    assert state.elements[2].status == "suppressed"  # no ceiling still filters utility


def test_incremental_analysis_preserves_user_decisions_and_does_not_generate(lesson, monkeypatch):
    path, rows, cfg = lesson
    media = Mock(side_effect=AssertionError("analysis must not generate"))
    monkeypatch.setattr("rt.llm.enrichment_media.generate_media", media)
    before = compute_source_fingerprint(path, "build")
    es.analyze(path, mock=True)
    assert compute_source_fingerprint(path, "build") == before
    assert len(es.load(path).elements) == 2
    a, b = es.load(path).elements
    es.mutate(path, a.id, "dismiss")
    es.mutate(path, b.id, "edit", es.IdeaText(title="Titolo mio", description="Idea mia", prompt="Prompt mio"))
    rows[0]["content"] += " Testo aggiornato."
    es.analyze(path, mock=True)
    state = es.load(path)
    assert len(state.elements) == 2
    assert es.get_element(state, a.id).status == "dismissed"
    assert es.get_element(state, b.id).prompt == "Prompt mio"
    assert es.view(path)["elements"][0].stale
    media.assert_not_called()


def test_both_types_are_independently_decided_and_writer_gets_one_unit(lesson, monkeypatch):
    path, rows, cfg = lesson
    cfg.enrichment.cap_mode = "off"
    decide = Mock(return_value=SimpleNamespace(answers={k: JevNoulAnswer(noul=.95) for k in es.UTILITY}))
    monkeypatch.setattr(es, "decision", decide)
    writer = Mock(return_value=es.IdeaText(title="Schema", description="Comprendi la struttura", prompt="Rappresenta la fonte", mode="interactive"))
    monkeypatch.setattr("rt.llm.client.LLMClient.call_structured", writer)
    es.analyze(path)
    assert len(es.load(path).elements) == 4
    assert set(decide.call_args_list[0].args[1]) == {"infographic", "visualization"}
    for call in writer.call_args_list:
        prompt = call.kwargs["prompt"]
        assert ("Matrice A:" in prompt) != ("struttura anatomica" in prompt)
    es.analyze(path)
    assert decide.call_count == 2 and writer.call_count == 4  # cached


def test_generation_receives_one_unit_and_failed_regeneration_preserves_result(lesson, monkeypatch):
    path, rows, cfg = lesson
    item = es.create_manual(path, "1.1", "visualization", es.IdeaText(title="A", description="D", prompt="Matrice"))
    es.generate(path, item.id, mock=True)
    first = es.get_element(es.load(path), item.id)
    assert first.asset_html and first.asset_image
    blocks = es.document_blocks(path)["1.1"]
    assert first.asset_html in blocks[0] and first.asset_image in blocks[0]
    fail = Mock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr("rt.llm.enrichment_media.generate_media", fail)
    with pytest.raises(RuntimeError, match="offline"):
        es.generate(path, item.id)
    second = es.get_element(es.load(path), item.id)
    assert second.status == "error" and second.asset_image == first.asset_image
    assert fail.call_args.args[2] == rows[0]
    assert es.document_blocks(path) == {"1.1": blocks}
    es.mutate(path, item.id, "delete")
    assert es.document_blocks(path) == {}


def test_generated_blocks_are_not_saved_as_canonical_unit_text(lesson):
    path, rows, cfg = lesson
    item = es.create_manual(path, "1.1", "visualization", es.IdeaText(title="A", description="D", prompt="P"))
    es.generate(path, item.id, mock=True)
    text = "### 1.1 Matrice\n00:00\n\nTesto originale.\n\n" + es.document_blocks(path)["1.1"][0]
    from rt.services.document_edit_service import _parse_structure
    macros, errors = _parse_structure("## 1. Macro\n" + text)
    assert not errors
    assert "assets/enrichment" not in "\n".join(line for _, line in macros[0].units[0].content_lines)


def test_export_references_both_poster_and_interactive_html(lesson):
    path, _, _ = lesson
    item = es.create_manual(path, "1.1", "visualization", es.IdeaText(title="A", description="D", prompt="P"))
    es.generate(path, item.id, mock=True)
    current = es.get_element(es.load(path), item.id)
    from rt.storage.export import referenced_assets
    refs = referenced_assets(es.document_blocks(path)["1.1"][0], {n: n for n in (current.asset_image, current.asset_html)})
    assert set(refs) == {current.asset_image, current.asset_html}


def test_macro_decision_sees_all_complete_units_one_image_at_a_time(lesson, monkeypatch):
    path, rows, _ = lesson
    from rt.pipeline import add_images as ai
    ai.save_image_descriptions(path, {"hash1": {"filename": "a.png", "alt_text": "prima"},
                                      "hash2": {"filename": "b.png", "alt_text": "seconda"}})
    outline = SimpleNamespace(macro_sections=[SimpleNamespace(id="1", title="Algebra"), SimpleNamespace(id="2", title="Medicina")])
    def answer(state, questions, **kwargs):
        assert rows[0]["content"] in state and rows[1]["content"] in state
        description = state.split("DESCRIZIONE DI UNA IMMAGINE", 1)[1]
        assert ("prima" in description) != ("seconda" in description)
        return SimpleNamespace(answers={"placement": JevChoiceAnswer(choice="macro_1", confidence=.9)})
    decide = Mock(side_effect=answer)
    monkeypatch.setattr(es, "decision", decide)
    assert ai.judge_images_by_macro(path, outline) == {"1": [], "2": ["hash1", "hash2"]}
    ai.judge_images_by_macro(path, outline)
    assert decide.call_count == 2
    rows[1]["content"] += " Correzione approvata."
    ai.judge_images_by_macro(path, outline)
    assert decide.call_count == 4


def test_macro_judge_rejects_unknown_labels(lesson, monkeypatch):
    path, _, _ = lesson
    from rt.pipeline import add_images as ai
    ai.save_image_descriptions(path, {"hash1": {"alt_text": "matrice"}})
    monkeypatch.setattr(es, "decision", lambda *a, **k: SimpleNamespace(answers={"placement": JevChoiceAnswer(choice="1.1", confidence=.9)}))
    with pytest.raises(ValueError, match="sconosciuta"):
        ai.judge_images_by_macro(path, SimpleNamespace(macro_sections=[SimpleNamespace(id=1, title="Macro")]))


def test_visualizer_policy_and_image_api_contract(lesson, monkeypatch):
    from rt.llm.enrichment_media import standalone, generate_image
    from rt.core.config import JobRoutingConfig, RouteConfig
    from PIL import Image
    path, _, cfg = lesson
    assert "connect-src 'none'" in standalone("<svg></svg>")
    with pytest.raises(ValueError):
        standalone('<script src="https://example.org/x.js"></script>')
    cfg.jobs["enrichment_image"] = JobRoutingConfig(primary=RouteConfig(provider="openrouter", model="image-model"))
    monkeypatch.setattr("rt.llm.enrichment_media.load_config", lambda: cfg)
    monkeypatch.setattr("rt.llm.enrichment_media.GLOBAL_CREDENTIALS.get_api_key", lambda _: "test-key")
    import base64
    output = io.BytesIO()
    Image.new("RGB", (20, 20)).save(output, format="PNG")
    response = Mock(status_code=200)
    response.json.return_value = {"data": [{"b64_json": base64.b64encode(output.getvalue()).decode()}], "usage": {"cost": .02}}
    post = Mock(return_value=response)
    monkeypatch.setattr("rt.llm.enrichment_media.requests.post", post)
    result = generate_image("Una matrice", path)
    assert result.startswith(b"\x89PNG")
    assert post.call_args.args[0] == "https://openrouter.ai/api/v1/images"
    assert post.call_args.kwargs["json"]["prompt"] == "Una matrice"


def test_snapshot_renders_initialized_interaction_without_network():
    import shutil
    from rt.llm.enrichment_media import standalone, snapshot
    if not (os.environ.get("RT_ENRICHMENT_CHROMIUM") or shutil.which("chromium")):
        pytest.skip("Chromium not installed in this test environment")
    html = standalone('<h2>Matrice dei vincoli</h2><svg width="300" height="100"><text x="10" y="30">[1, 1, 0]</text></svg><input type="range" aria-label="Parametro">')
    assert snapshot(html).startswith(b"\x89PNG")
