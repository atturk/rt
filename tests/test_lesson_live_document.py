from rt.services.lesson_service import lesson_document
from rt.pipeline.rewrite import load_draft, save_draft
from tests.test_document_edit import _synthetic_lesson, root  # noqa: F401


def test_partial_checkpoint_replaces_old_final_in_live_document(root):
    lesson = _synthetic_lesson(root)
    draft = load_draft(lesson)
    draft.units = draft.units[:1]
    draft.units[0].content = "Nuova rielaborazione dal checkpoint."
    save_draft(draft, lesson)
    document = lesson_document(lesson)
    assert document["final"] is False
    assert "Nuova rielaborazione dal checkpoint." in document["markdown"]
    assert "Testo dell'unità 1.1." not in document["markdown"]
    assert "Testo dell'unità 1.2." not in document["markdown"]
    assert [s["unit_id"] for s in document["sections"]] == ["1.1"]
