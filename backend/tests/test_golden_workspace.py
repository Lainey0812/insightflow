import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.core.config import Settings
from app.domain.errors import AppError
from app.main import create_app
from app.services.golden_workspace import GoldenWorkspace, GoldenDocument, SaveDraft, PublishDraft

SOURCE=Path(__file__).resolve().parents[2]/'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json'


def changed(document):
    new=json.loads(json.dumps(document));new['cases'][0]['pass_rule']+='；人工复核新规则。'
    return GoldenDocument.model_validate(new)


def test_bootstrap_save_publish_and_restart_preserve_versions(tmp_path):
    raw=SOURCE.read_bytes();store=GoldenWorkspace(tmp_path/'golden',SOURCE)
    v1=store.view()['selected'];draft=store.draft()
    assert v1['frozen'] and v1['version']==1 and v1['case_count']==5
    saved=store.save(SaveDraft(document=changed(draft['document']),expected_revision=1,annotator='tester'))
    assert store.view()['current_version']==1 and saved['revision']==2
    published=store.publish(PublishDraft(expected_revision=2,base_version=1,annotator='tester',change_summary='更新通过规则'))
    assert published['version']==2 and store.draft()['base_version']==2
    assert store.view(1)['selected']==v1
    assert SOURCE.read_bytes()==raw
    restarted=GoldenWorkspace(tmp_path/'golden',SOURCE)
    assert restarted.view()['current_version']==2 and len(restarted.view()['versions'])==2
    with store.connect() as c:
        for statement in ['DELETE FROM golden_versions','UPDATE golden_draft_history SET record=record']:
            with pytest.raises(sqlite3.IntegrityError):c.execute(statement)


def test_stale_noop_empty_and_identity_are_rejected(tmp_path):
    store=GoldenWorkspace(tmp_path/'golden',SOURCE);draft=store.draft()
    with pytest.raises(AppError):store.publish(PublishDraft(expected_revision=1,base_version=1,annotator='a',change_summary='no change'))
    doc=changed(draft['document']);store.save(SaveDraft(document=doc,expected_revision=1,annotator='a'))
    with pytest.raises(AppError):store.save(SaveDraft(document=doc,expected_revision=1,annotator='b'))
    with pytest.raises(AppError):store.publish(PublishDraft(expected_revision=2,base_version=2,annotator='a',change_summary='stale base'))
    other=doc.model_copy(update={'set_id':'other'})
    with pytest.raises(AppError):store.save(SaveDraft(document=other,expected_revision=2,annotator='a'))
    empty=doc.model_copy(update={'case_count':0,'cases':[]})
    store.save(SaveDraft(document=empty,expected_revision=2,annotator='a'))
    with pytest.raises(AppError):store.publish(PublishDraft(expected_revision=3,base_version=1,annotator='a',change_summary='empty'))
    assert store.view()['current_version']==1


def test_concurrent_publish_has_one_winner(tmp_path):
    store=GoldenWorkspace(tmp_path/'golden',SOURCE)
    store.save(SaveDraft(document=changed(store.draft()['document']),expected_revision=1,annotator='a'))
    body=PublishDraft(expected_revision=2,base_version=1,annotator='a',change_summary='once')
    def publish():
        try:return store.publish(body)['version']
        except AppError:return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:publish(),range(2)))
    assert sorted(map(str,results))==['2','stale']
    assert len(store.view()['versions'])==2


@pytest.mark.parametrize('bad',['duplicate','row','boolean','count'])
def test_dataset_contract_validation(bad):
    doc=json.loads(SOURCE.read_text())
    if bad=='duplicate':doc['cases'][1]['case_id']=doc['cases'][0]['case_id']
    elif bad=='row':doc['rows'][0]['fake_column']='x'
    elif bad=='boolean':doc['cases'][0]['oracle']={'上海':True}
    else:doc['case_count']=99
    with pytest.raises(ValidationError):GoldenDocument.model_validate(doc)


def test_admin_auth_and_publish_contract(tmp_path):
    app=create_app(Settings(tmp_path,admin_read_token='read',admin_annotation_token='write',evaluation_golden_dataset=SOURCE))
    with TestClient(app) as client:
        read={'X-Admin-Token':'read'};write={**read,'X-Admin-Annotation-Token':'write'}
        assert client.get('/admin/golden-set').status_code==403
        initial=client.get('/admin/golden-set',headers=read).json()
        body={'document':changed(initial['selected']['document']).model_dump(exclude_none=True),'expected_revision':1,'annotator':'a'}
        assert client.post('/admin/golden-set/draft',headers=read,json=body).status_code==403
        assert client.post('/admin/golden-set/draft',headers=write,json=body).status_code==200
        result=client.post('/admin/golden-set/publish',headers=write,json={'expected_revision':2,'base_version':1,'annotator':'a','change_summary':'rule update'})
        assert result.status_code==200,result.text
        assert client.get('/admin/golden-set?version=1',headers=read).json()['selected']==initial['selected']
        assert client.get('/admin/golden-set?version=99',headers=read).status_code==404
        assert client.put('/admin/golden-set?version=1',headers=write,json=body).status_code==405
