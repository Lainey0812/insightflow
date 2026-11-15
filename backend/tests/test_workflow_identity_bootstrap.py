"""Identity authority and observation fault isolation, without switching business state."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.models import SessionState, Message
from app.main import create_app
from app.observability.workflow import preparation_context
from workflow_v1_fixtures import ControlledWorkflowProvider, create_real


def app_for(path):
    return create_app(Settings(path), ControlledWorkflowProvider())


def saved(app,client):
    state = create_real(client)
    return app.state.repository.get(state['id'])


def initial(state):
    result=state.model_copy(deep=True)
    # Only immutable upload/origin information participates in the create digest.
    result.workflow_id=result.root_run_id=None
    return result


def row(app,state):
    with closing(app.state.repository.database.connect()) as conn:
        return dict(conn.execute('SELECT * FROM business_workflows WHERE session_id=?',(state.id,)).fetchone())


def test_atomic_identity_source_links_and_replay(tmp_path):
    app=app_for(tmp_path)
    with TestClient(app) as client:
        state=saved(app,client);identity=app.state.workflow.identity(state);record=row(app,state)
        assert (record['workflow_id'],record['root_run_id'])==(identity.workflow_id,identity.root_run_id)
        assert record['control_status']=='CREATED' and state.status.value=='AWAITING_APPROVAL'
        identities=app.state.workflow.identities
        assert identities.create(initial(state),'prepare:'+state.id)==state
        with pytest.raises(AppError,match='单流程身份'):
            identities.create(initial(state),'different-key')
        bad=initial(state);bad.user_goal='changed'
        with pytest.raises(AppError):identities.create(bad,'prepare:'+state.id)
        with closing(app.state.repository.database.connect()) as conn:
            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
            assert conn.execute('SELECT workflow_id FROM session_messages WHERE session_id=?',(state.id,)).fetchone()[0]==identity.workflow_id
            for column in ('workflow_id','root_run_id'):
                with pytest.raises(Exception,match='immutable'):
                    conn.execute(f'UPDATE business_workflows SET {column}=?,revision=revision+1 WHERE workflow_id=?',('changed',identity.workflow_id))


def test_concurrent_create_single_identity(tmp_path):
    app=app_for(tmp_path)
    with TestClient(app) as client:
        source=saved(app,client)
    candidate=SessionState(title="测试",analysis_mode="goal_driven",file=source.file,user_goal='新目标',workflow_kind='real_v1',messages=[Message(role='user',content='新目标')])
    repo=app.state.workflow.identities
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _: repo.create(candidate.model_copy(deep=True),'same-key'),range(8)))
    assert len({(s.workflow_id,s.root_run_id) for s in results})==1
    other=candidate.model_copy(deep=True)
    with pytest.raises(AppError):repo.create(other,'different-key')


def test_conflict_rolls_back_session_and_source_facts(tmp_path):
    app=app_for(tmp_path)
    with TestClient(app) as client:source=saved(app,client)
    bad=SessionState(title="测试",analysis_mode="goal_driven",file=source.file.model_copy(update={'name':'different.csv'}),user_goal='新目标',workflow_kind='real_v1',messages=[Message(role='user',content='新目标')])
    with pytest.raises(AppError):app.state.workflow.identities.create(bad,'conflict')
    with closing(app.state.repository.database.connect()) as conn:
        assert conn.execute('SELECT 1 FROM sessions WHERE id=?',(bad.id,)).fetchone() is None


def test_explicit_root_and_flat_nodes_and_reentry_no_duplicates(tmp_path,monkeypatch):
    app=app_for(tmp_path)
    with TestClient(app) as client:
        # This lookup is forbidden for the preparation identity path.
        monkeypatch.setattr(app.state.traces.repository,'workflow',lambda _: (_ for _ in ()).throw(AssertionError('Session inference')))
        state=saved(app,client);identity=app.state.workflow.identity(state);repo=app.state.traces.repository
        spans=repo.spans(identity.root_run_id)
        assert len(spans)==5 and {s.name for s in spans}=={'data_profiler','intent_parser','analysis_planner','plan_validator'}
        assert all(s.parent_span_id is None and s.attributes['workflow_id']==identity.workflow_id for s in spans)
        assert [s.node_attempt for s in spans if s.name=='plan_validator']==[1,2]
        assert asyncio.run(app.state.workflow.prepare_real(state.id,identity)).id==state.id
        assert {s.span_id for s in repo.spans(identity.root_run_id)}=={s.span_id for s in spans}
        with closing(repo.connect()) as conn:
            link=conn.execute('SELECT * FROM trace_workflow_links WHERE run_id=?',(identity.root_run_id,)).fetchone()
            assert link['workflow_id']==identity.workflow_id


def test_root_missing_repaired_before_preparation(tmp_path,monkeypatch):
    app=app_for(tmp_path);repo=app.state.traces.repository;create=repo.create_registered_root
    count=0
    def flaky(*args):
        nonlocal count
        count+=1
        if count==1:raise OSError('temporary trace outage')
        return create(*args)
    monkeypatch.setattr(repo,'create_registered_root',flaky)
    with TestClient(app) as client:
        state=saved(app,client);assert state.status.value=='AWAITING_APPROVAL'
        assert count==2 and len(repo.spans(state.root_run_id))==5


def test_trace_database_unavailable_business_success_then_repair(tmp_path,monkeypatch):
    app=app_for(tmp_path);repo=app.state.traces.repository;connect=repo.connect
    with TestClient(app) as client:
        monkeypatch.setattr(repo,'connect',lambda: (_ for _ in ()).throw(OSError('trace down')))
        state=saved(app,client);assert state.status.value=='AWAITING_APPROVAL' and row(app,state)
        monkeypatch.setattr(repo,'connect',connect)
        root=app.state.workflow.trace_created(state)
        assert root.run_id==state.root_run_id
        assert repo.spans(root.run_id)==[]  # No fabricated historical node activity.


def test_identity_mismatch_rejected_before_business_changes(tmp_path):
    app=app_for(tmp_path)
    with TestClient(app) as client:
        state=saved(app,client);identity=app.state.workflow.identity(state)
        for bad in (replace(identity,workflow_id='other'),replace(identity,root_run_id='other'),replace(identity,session_id='other')):
            with pytest.raises(AppError):asyncio.run(app.state.workflow.prepare_real(state.id,bad))
        assert app.state.repository.get(state.id)==state


def test_restart_reads_same_identity_and_root(tmp_path):
    app=app_for(tmp_path)
    with TestClient(app) as client:state=saved(app,client)
    restarted=app_for(tmp_path)
    with TestClient(restarted):
        loaded=restarted.state.repository.get(state.id)
        assert restarted.state.workflow.identity(loaded)==app.state.workflow.identity(state)
        assert restarted.state.workflow.trace_created(loaded).run_id==state.root_run_id
        assert len(restarted.state.traces.repository.spans(state.root_run_id))==5


def test_missing_explicit_ids_not_inferred_from_session(tmp_path):
    app=app_for(tmp_path)
    with TestClient(app) as client:state=saved(app,client)
    broken=state.model_copy(update={'workflow_id':None,'root_run_id':None})
    with pytest.raises(AppError):app.state.workflow.identity(broken)


def test_multiple_candidates_rejected_without_silent_choice(tmp_path):
    app=app_for(tmp_path)
    with TestClient(app) as client:state=saved(app,client)
    with closing(app.state.repository.database.connect()) as conn,conn:
        columns=[r[1] for r in conn.execute('PRAGMA table_info(business_workflows)')]
        data=row(app,state)
        data.update(workflow_id='wf_conflicting_candidate',root_run_id='run_other',creation_request_id='other')
        conn.execute(f'INSERT INTO business_workflows ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',[data[c] for c in columns])
    with pytest.raises(AppError):app.state.workflow.identity(state)


def test_blank_goal_returns_explicit_error_and_no_partial_session(tmp_path):
    app=app_for(tmp_path)
    with TestClient(app) as client:
        response=client.post('/api/v1/sessions',data={'real_workflow':'true','goal':''},files={'file':('emptygoal.csv',b'city,sales\nA,1\n')})
        assert response.status_code==422
        assert app.state.repository.list()==[]
