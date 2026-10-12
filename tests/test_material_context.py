from rt.core.sources import add_source
from rt.pipeline.rewrite import context_for_usage, _run_rewrite
from rt.llm.client import LLMClient
from tests.test_checkpointing import multi_unit_lesson
from tests.test_materials import pdf_bytes


def test_materials_enter_prefix_before_previous_units_and_are_cached(multi_unit_lesson, monkeypatch):
    lesson = multi_unit_lesson
    add_source(lesson, 'materiale', 'doc.pdf', pdf_bytes('MATERIAL CONTEXT'))
    captured = []
    original = LLMClient.call_structured
    def call(self, **kwargs):
        captured.append(kwargs)
        return original(self, **kwargs)
    monkeypatch.setattr(LLMClient, 'call_structured', call)
    _run_rewrite(lesson, force=True, force_mock=True)
    rewrites = [r for r in captured if r['job_name'] == 'rewrite']
    assert rewrites and all('MATERIAL CONTEXT' in r['prompt_prefix'] for r in rewrites)
    assert rewrites[1]['prompt_prefix'].index('MATERIAL CONTEXT') < rewrites[1]['prompt_prefix'].index('UNITÀ PRECEDENTI')
    assert all('image_data_url' not in r for r in rewrites)
    monkeypatch.setattr('rt.core.materials._extract', lambda _: (_ for _ in ()).throw(AssertionError('cached')))
    _run_rewrite(lesson, force=True, force_mock=True)


def test_trim_previous_before_materials_without_token_estimates():
    usage = {'prompt_tokens': 90, 'completion_tokens': 20}
    units, materials = context_for_usage(['old', 'new'], ['page1', 'page2'], 100, usage)
    assert units == ['new'] and materials == ['page1', 'page2']
    units, materials = context_for_usage([], materials, 100, usage)
    assert units == [] and materials == ['page2']
    assert context_for_usage([], materials, None, usage) == ([], materials)
    assert context_for_usage([], materials, 100, None) == ([], materials)
