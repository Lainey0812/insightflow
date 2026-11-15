"""Controlled fixtures for contracts; live historic examples are documented separately."""
from contextlib import closing
import copy
import json
import pytest
from fastapi.testclient import TestClient
from app.domain.models import now
from app.domain.tracing import RunManifest, TraceRun, TraceSpan, TraceEvent, TraceSnapshot
from app.main import create_app
from app.observability.comparison import align_spans, compare, artifacts
from app.observability.provenance import digest, git_snapshot
from app.observability.recorder import TraceRecorder
from app.observability.snapshots import evidence_projection, llm_projection
from app.storage.trace_repository import TraceRepository
from test_workflow_trace import settings, headers, listing, CandidateProvider
from test_report_workflow import Provider, run

class NoReports:
    def get(self, _): raise KeyError('missing')


def record(repo, key, hashes=True):
    manifest=RunManifest(schema_version='workflow-trace-v0.3',capture_scope='report_generation',
        input_sha256={k:digest(k) for k in ('dataset','profile','user_goal','intent','approved_plan','execution')} if hashes else {},
        versions={k:'fixture-v1' for k in ('prompt_version','generation_version','schema_version','validation_version','registry_version','prompt_sha256','fact_validator_sha256')},
        model_config_snapshot={'provider':'Fixture','model':'fixture-only','timeout_seconds':30,'enable_thinking':False})
    r=repo.create(TraceRun(run_id=key,session_id='session_fixture',execution_id='exec_'+key,attempt=1,
        owner_instance='fixture',status='queued',queued_at=now(),manifest=manifest))
    if hashes:
        repo.event(TraceEvent(event_id='evt_'+key,run_id=key,sequence=1,event_type='inputs.verified',
                             recorded_at=now(),payload={'inputs_match':True}))
    return r


def span(key, run='r', name='x', parent=None, node=None, attempt=None):
    return TraceSpan(span_id=key,run_id=run,parent_span_id=parent,name=name,
                     node_key=node,node_attempt=attempt,status='complete',started_at=now())


def test_exact_input_hashes_and_model_versions_are_visible_without_claiming_causality(tmp_path):
    repo=TraceRepository(tmp_path);a=record(repo,'left');b=record(repo,'right')
    b.manifest.versions['prompt_version']='changed-fixture'
    value=compare(repo,NoReports(),a,b)
    assert value['comparability']['status']=='comparable'
    assert next(c for c in value['comparability']['versions'] if c['key']=='prompt_version')['status']=='different'
    assert value['comparability']['git']['status']=='unknown'
    assert '不能直接归因' in value['comparability']['notice']
    assert next(c for c in value['comparability']['models'] if c['key']=='temperature')['status']=='unknown'


@pytest.mark.parametrize('key',['dataset','profile','user_goal','intent','approved_plan','execution'])
def test_different_inputs_are_not_declared_identical(tmp_path,key):
    repo=TraceRepository(tmp_path);a=record(repo,'left');b=record(repo,'right')
    b.manifest.input_sha256[key]=digest('different')
    value=compare(repo,NoReports(),a,b)['comparability']
    assert value['status']=='partially_comparable'
    assert next(c for c in value['checks'] if c['key']==key)['status']=='different'


def test_missing_information_stays_unknown_and_no_current_configuration_backfill(tmp_path):
    repo=TraceRepository(tmp_path);a=record(repo,'left',False);b=record(repo,'right',False)
    a.manifest=RunManifest();b.manifest=RunManifest()
    value=compare(repo,NoReports(),a,b)
    assert value['comparability']['status']=='unknown'
    assert all(c['status']=='unknown' for c in value['comparability']['checks'])
    assert not value['left'].manifest.versions
    assert all(v['availability']=='unknown' for v in value['artifacts']['left'].values())
    a.manifest.bindings={'execution_id':'same'};b.manifest.bindings={'execution_id':'same'}
    assert compare(repo,NoReports(),a,b)['comparability']['status']=='partially_comparable'


def test_queue_fingerprint_without_consumption_verification_is_not_comparable(tmp_path):
    repo=TraceRepository(tmp_path);a=record(repo,'left');b=record(repo,'right')
    with closing(repo.connect()) as conn,conn:conn.execute('DELETE FROM trace_events WHERE run_id=?',('right',))
    assert compare(repo,NoReports(),a,b)['comparability']['status']=='unknown'


def test_identity_and_retry_alignment_does_not_use_list_order():
    left=[span('l1',node='root',attempt=1),span('l2',node='root',attempt=2),span('lc',node='other',attempt=1)]
    right=[span('rc',node='other',attempt=1),span('r2',node='root',attempt=2),span('r1',node='root',attempt=1)]
    rows=align_spans(left,right)
    assert {(r['left'].span_id,r['right'].span_id) for r in rows}=={('l1','r1'),('l2','r2'),('lc','rc')}
    assert {r['node_attempt'] for r in rows}=={1,2}


def test_legacy_unique_paths_match_but_repeated_ancestors_do_not():
    a=[span('a',name='parent'),span('ac',name='child',parent='a')]
    b=[span('bc',name='child',parent='b'),span('b',name='parent')]
    rows=align_spans(a,b)
    assert all(row['left'] and row['right'] and row['match_basis']=='legacy_unique_path' for row in rows)
    a.append(span('a2',name='parent'))
    rows=align_spans(a,b)
    assert not any(row['left'] and row['right'] for row in rows)


def test_mixed_new_legacy_matching_and_missing_parent_or_cycle():
    rows=align_spans([span('old',name='node')],[span('new',name='node',node='node',attempt=1)])
    assert rows[0]['left'] and rows[0]['right'] and rows[0]['match_basis']=='legacy_unique_path'
    rows=align_spans([span('a',parent='b'),span('b',parent='a')],[span('c',parent='missing')])
    assert len(rows)==3 and all(row['match_basis']=='ambiguous_or_missing' for row in rows)


def test_nested_retried_parent_identity_keeps_child_retries_separate(tmp_path):
    repo=TraceRepository(tmp_path);record(repo,'r');ctx=TraceRecorder(repo).start('exec_r',1)
    with ctx.span('parent'):
        with ctx.span('child'):pass
    with ctx.span('parent'):
        with ctx.span('child'):pass
    children=[s for s in repo.spans('r') if s.name=='child']
    assert [s.node_key for s in children]==['parent#1/child','parent#2/child']
    assert all(s.node_attempt==1 for s in children)


def test_snapshots_are_immutable_scoped_and_survive_reopening(tmp_path):
    repo=TraceRepository(tmp_path);record(repo,'r');record(repo,'other')
    s=span('s',run='r');repo.save_span(s)
    snap=TraceSnapshot(snapshot_id='snap',run_id='r',span_id='s',kind='evidence',captured_at=now(),
                       content_sha256=digest('private content'),projection={'count':0})
    repo.save_snapshot(snap);repo.save_snapshot(snap)
    with pytest.raises(ValueError):repo.save_snapshot(snap.model_copy(update={'projection':{'count':1}}))
    with pytest.raises(ValueError):repo.save_snapshot(snap.model_copy(update={'run_id':'other','snapshot_id':'bad'}))
    assert TraceRepository(tmp_path).snapshots('r')==[snap]


def test_git_unknown_without_repo_and_actual_commit_when_available(tmp_path):
    import subprocess
    assert git_snapshot(tmp_path)=={}
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    # Only a disposable test directory; never initialize the user's project Git.
    subprocess.run(['git','-C',str(tmp_path),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                    'commit','--allow-empty','-qm','fixture'],check=True)
    info=git_snapshot(tmp_path)
    assert len(info['commit'])==40 and info['dirty'] is False
    (tmp_path/'fixture.txt').write_text('changed')
    assert git_snapshot(tmp_path)['dirty'] is True


def test_real_workflow_observation_snapshots_auth_and_restart(tmp_path,monkeypatch):
    monkeypatch.setattr('app.observability.recorder.git_snapshot',lambda _: {})
    app=create_app(settings(tmp_path),Provider())
    with TestClient(app) as client:
        _,execution,_=run(client);a=listing(client)[0]
        assert set(a['manifest']['input_sha256'])=={'dataset','profile','user_goal','intent','approved_plan','execution'}
        assert a['manifest']['git']=={} # actual project has no Git, no fake SHA
        path='/admin/runs/'+a['run_id']+'/snapshots'
        assert client.get(path).status_code==403
        output=client.get(path,headers=headers()).json()['artifacts']
        assert all(v['availability']=='available' for v in output.values())
        assert output['llm_output']['projection']['parsed'] is True
        encoded=json.dumps(output,ensure_ascii=False)
        assert '济南' not in encoded and '华东' not in encoded and 'api_key' not in encoded
        assert 'text_sha256' in encoded
        assert client.get('/admin/comparison',params={'left':a['run_id'],'right':a['run_id']},headers=headers()).status_code==422
        assert client.get('/admin/comparison?left=a&right=b').status_code==403
        assert client.get('/admin/comparison?left=a&right=b',headers=headers()).status_code==404
    with TestClient(create_app(settings(tmp_path),Provider())) as client:
        assert client.get(path,headers=headers()).json()['artifacts']==output
        assert listing(client)[0]['manifest']==a['manifest']


def test_failed_candidates_still_have_controlled_evidence_and_llm_output(tmp_path):
    app=create_app(settings(tmp_path),CandidateProvider('bad'))
    with TestClient(app) as client:
        run(client);a=listing(client)[0]
        assert a['status']=='error'
        values=client.get('/admin/runs/'+a['run_id']+'/snapshots',headers=headers()).json()['artifacts']
        assert values['evidence']['availability']==values['llm_output']['availability']=='available'
        assert values['report']['availability']=='unknown'
        assert '盈利能力' not in json.dumps(values,ensure_ascii=False)


def test_snapshot_write_failure_is_fail_open(tmp_path,monkeypatch):
    app=create_app(settings(tmp_path),Provider())
    def broken(_):raise OSError('sensitive text')
    monkeypatch.setattr(app.state.traces.repository,'save_snapshot',broken)
    with TestClient(app) as client:
        _,execution,session=run(client)
        assert execution['execution_status']=='success' and session['report_generations'][0]['status']=='completed'
        assert listing(client)[0]['integrity']=='incomplete'


def test_historical_report_projection_must_match_exact_run_binding(tmp_path):
    app=create_app(settings(tmp_path),Provider())
    with TestClient(app) as client:
        run(client);a=app.state.traces.repository.runs()[0][0]
        with closing(app.state.traces.repository.connect()) as conn,conn:conn.execute('DELETE FROM trace_snapshots')
        before=a.manifest.model_dump()
        value=artifacts(app.state.traces.repository,app.state.reports,a)
        assert value['report']['source']=='immutable_saved_report_projection'
        assert value['evidence']['availability']=='available' and value['llm_output']['availability']=='unknown'
        a.manifest.bindings['dataset_version']='wrong'
        assert artifacts(app.state.traces.repository,app.state.reports,a)['report']['availability']=='unknown'
        assert app.state.traces.repository.get(a.run_id).manifest.model_dump()==before


def test_conflicting_consumption_verification_prevents_same_input_claim(tmp_path):
    repo=TraceRepository(tmp_path);a=record(repo,'left');b=record(repo,'right')
    repo.event(TraceEvent(event_id='conflict',run_id='right',sequence=2,event_type='inputs.verified',
                         recorded_at=now(),payload={'inputs_match':False}))
    assert compare(repo,NoReports(),a,b)['comparability']['status']=='unknown'


def test_distinct_rule_and_report_status_are_not_normalized_to_success(tmp_path):
    repo=TraceRepository(tmp_path);a=record(repo,'left');b=record(repo,'right')
    a.status='failed';a.error_code='REPORT_UNVERIFIED_FACT';b.status='partial'
    for rid,rule in [('left','ENDPOINT_NOT_INTERVAL_STABILITY'),('right','UNDEFINED_THRESHOLD')]:
        repo.event(TraceEvent(event_id='evt_rule_'+rid,run_id=rid,sequence=2,event_type='candidate.validated',
            recorded_at=now(),payload={'rule_ids':[rule],'candidate_status':'rejected'}))
    value=compare(repo,NoReports(),a,b)
    assert value['left'].status=='error' and value['right'].status=='error'
    assert value['diagnostics']['left'][1]['payload']['rule_ids'] != value['diagnostics']['right'][1]['payload']['rule_ids']


def test_legacy_child_does_not_guess_which_parent_retry_it_matches():
    legacy=[span('lroot',name='parent'),span('lchild',name='child',parent='lroot')]
    stable=[span('r1',name='parent',node='parent',attempt=1),
            span('r2',name='parent',node='parent',attempt=2),
            span('rc',name='child',parent='r1',node='parent#1/child',attempt=1)]
    assert not any(row['left'] and row['right'] for row in align_spans(legacy,stable))
