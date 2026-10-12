from types import SimpleNamespace

from rt.core.sources import add_source
from rt.core.state import update_info_yaml
from rt.core.lesson_paths import lesson_path
from rt.pipeline.outline import load_outline
from rt.pipeline.material_attachments import attach_material_pages
from rt.pipeline.image_placement import images_for_document, save_image_placement
from rt.pipeline.add_images import save_image_descriptions
from rt.pipeline.build import render_lesson_documents
from rt.llm.jev_client import JevChoiceAnswer
from tests.test_checkpointing import multi_unit_lesson
from tests.test_materials import pdf_bytes


def test_clip_attaches_images_never_ocr_and_off_preserves_existing_images(multi_unit_lesson):
    lesson = multi_unit_lesson
    from rt.pipeline.rewrite import _run_rewrite
    _run_rewrite(lesson, force=True, force_mock=True)
    add_source(lesson, 'materiale', 'doc.pdf', pdf_bytes('OCR SECRET CONTEXT'))
    outline = load_outline(lesson)
    mid = str(outline.macro_sections[0].id)
    save_image_descriptions(lesson, {'old': {'filename': 'assets/images/old.png', 'alt_text': 'Existing'}})
    save_image_placement(lesson, {mid: ['old']}, False)
    attach_material_pages(lesson, outline, mock=True)
    attached, _ = images_for_document(lesson, outline)
    assert len(attached[mid]) == 2
    assert all('ocr_text' not in image for image in attached[mid])
    docs = render_lesson_documents(lesson)
    # OCR resta contesto, non compare in didascalie o allegati del documento.
    assert 'OCR SECRET CONTEXT' not in str(docs)
    update_info_yaml(lesson_path(lesson, 'info.yaml'), {'allega_materiali': False})
    attach_material_pages(lesson, outline, mock=True)
    assert images_for_document(lesson, outline)[0][mid] == [{'filename': 'assets/images/old.png', 'alt_text': 'Existing'}]


def test_classifier_none_and_decision_cache(multi_unit_lesson, monkeypatch):
    lesson = multi_unit_lesson
    from rt.pipeline.rewrite import _run_rewrite
    _run_rewrite(lesson, force=True, force_mock=True)
    add_source(lesson, 'materiale', 'doc.pdf', pdf_bytes('PAGE TO CLASSIFY'))
    outline = load_outline(lesson)
    monkeypatch.setattr('rt.llm.client.LLMClient', lambda **kwargs: SimpleNamespace(force_mock=False))
    calls = []
    def decision(prompt, questions, **kwargs):
        calls.append(prompt)
        assert 'PAGE TO CLASSIFY' in prompt and 'LEZIONE COMPLETA' in prompt
        assert 'none' in questions['placement'].criteria
        return SimpleNamespace(answers={'placement': JevChoiceAnswer(choice='none', confidence=1)})
    monkeypatch.setattr('rt.services.enrichment_service.decision', decision)
    attach_material_pages(lesson, outline)
    attach_material_pages(lesson, outline)
    assert len(calls) == 1
    assert images_for_document(lesson, outline)[0] == {}
