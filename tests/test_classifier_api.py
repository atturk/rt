"""Snapshot risolto, correzioni consigliate e job per cella."""
import json
from unittest.mock import patch
from rt.core.config import RTConfig, ClassifierConfig
from rt.services import classifier_view, unit_relevance, question_types, section_labels
from tests.api_support import isolated_workspace, make_lesson


def fixture_lesson(api_client, tmp_path, monkeypatch):
    root = isolated_workspace(tmp_path,monkeypatch)
    path = make_lesson(root)
    from rt.pipeline.rewrite import save_draft
    from rt.core.models import Draft, DraftUnit
    unit = DraftUnit(unit_id='1.1',title='Titolo',content='Una nozione',start_segment_id='seg_000001',end_segment_id='seg_000001',source_segment_ids=['seg_000001'])
    save_draft(Draft(units=[unit]),path)
    cfg = RTConfig(mock_llm=True,classifier=ClassifierConfig())
    monkeypatch.setattr("rt.core.config.load_config",lambda:cfg)
    for service in (classifier_view,unit_relevance,question_types,section_labels):
        monkeypatch.setattr(service,'load_config',lambda:cfg)
    from rt.services.lesson_service import lesson_id_for_dir
    return path,lesson_id_for_dir(path),unit,cfg


def test_cells_and_manual_question_type_used_by_recall(api_client,rt_db,tmp_path,monkeypatch):
    path,id,unit,cfg=fixture_lesson(api_client,tmp_path,monkeypatch)
    base=f'/api/v1/lessons/{id}/classifier'
    result=api_client.get(base)
    assert result.status_code == 200,result.text
    data=result.json()
    assert set(data['jobs']) == set(classifier_view.JOBS)
    assert data['units'][0]['section_id']=='1'
    assert data['jobs']['question_types']['cells'][0]['state']=='missing'
    result=api_client.put(base+'/question_types/1.1',json={'value':'quiz'})
    assert result.status_code==200,result.text
    cell=result.json()['jobs']['question_types']['cells'][0]
    assert (cell['source'],cell['value'],cell['state'])==('manual','quiz','fresh')
    assert question_types.suggestions(path)['1.1']=='quiz'
    assert api_client.put(base+'/question_types/1.1',json={'value':'inventato'}).status_code==422
    assert api_client.put(base+'/question_types/9',json={'value':'quiz'}).status_code==404
    reset=api_client.put(base+'/question_types/1.1',json={'value':None}).json()
    assert reset['jobs']['question_types']['cells'][0]['source']=='classifier'


def test_resolved_relevance_and_run_payload(api_client,rt_db,tmp_path,monkeypatch):
    path,id,unit,cfg=fixture_lesson(api_client,tmp_path,monkeypatch)
    unit_relevance.refresh(path,force_mock=True,view='resolved')
    unit_relevance.set_override(path,'1.1','organizational',view='resolved')
    base=f'/api/v1/lessons/{id}/classifier'
    cell=api_client.get(base).json()['jobs']['relevance']['cells'][0]
    assert cell['value']=='organizational' and cell['source']=='manual'
    with patch('rt.api.jobs.enqueue_job',return_value={'job_id':'test','type':'classifier','state':'queued','worker_available':False}) as enqueue:
        result=api_client.post(base+'/question_types/run',json={'force':True,'unit_ids':['1.1']})
        assert result.status_code==202,result.text
        assert enqueue.call_args.args[2]['unit_ids']==['1.1']
        assert enqueue.call_args.args[2]['job']=='question_types'
        assert api_client.post(base+'/run',json={'force':False}).status_code==202
    assert api_client.post(base+'/unknown/run',json={}).status_code==422


def test_draft_classification_is_used_without_resolved_cache(api_client,rt_db,tmp_path,monkeypatch):
    path,id,unit,cfg=fixture_lesson(api_client,tmp_path,monkeypatch)
    unit_relevance.refresh(path,force_mock=True)
    cell=api_client.get(f'/api/v1/lessons/{id}/classifier').json()['jobs']['relevance']['cells'][0]
    assert cell['value']=='didactic' and cell['state']=='fresh'


def test_enrichment_analysis_error_is_a_cell(api_client,rt_db,tmp_path,monkeypatch):
    from rt.services import enrichment_service as es
    path,id,unit,cfg=fixture_lesson(api_client,tmp_path,monkeypatch)
    cfg.mock_llm=False
    monkeypatch.setattr(es,'load_config',lambda:cfg)
    monkeypatch.setattr(es,'units',lambda _: [{'id':unit.unit_id,'title':unit.title,'content':unit.content,'macro_id':'1'}])
    with patch.object(es,'decision',side_effect=ValueError('Modello non disponibile')):
        import pytest
        with pytest.raises(ValueError):
            es.analyze(path)
    job=api_client.get(f'/api/v1/lessons/{id}/classifier').json()['jobs']['enrichment']
    assert job['cells'][0]['state']=='error' and job['errors']==1
    assert job['last_run_at']
