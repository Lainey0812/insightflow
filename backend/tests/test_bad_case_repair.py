from fastapi.testclient import TestClient
from test_bad_cases import application, body, WRITE
from test_report_workflow import run
from test_trace_closure_c2 import AUTH


def setup_case(client):
    _,_,session=run(client)
    return client.post('/admin/bad-cases',headers=WRITE,json=body(session['workflow_id'])).json()


def attribution(sequence=1,node='intent_parser'):
    return {'cause':'prompt','node_id':node,'explanation':'增加明确的边界说明。','annotator':'tester','expected_sequence':sequence}


def test_attribution_repair_roundtrip_and_immutable_evidence(tmp_path):
    app=application(tmp_path)
    with TestClient(app) as client:
        case=setup_case(client);base=app.state.intent_parser.prompt_source.snapshot
        uri='/admin/bad-cases/'+case['case_id']
        assert client.post(uri+'/attribution',headers=AUTH,json=attribution()).status_code==403
        updated=client.post(uri+'/attribution',headers=WRITE,json=attribution()).json()
        assert updated['status']=='in_progress' and updated['sequence']==2
        listing=client.get('/admin/bad-cases?status=in_progress',headers=AUTH).json()
        assert listing['items'][0]['attribution']['node_id']=='intent_parser'
        draft_body={'base_snapshot_id':base.template_snapshot_id,'system_prompt':base.system_template+'\n测试修复边界。','expected_sequence':2}
        draft=client.post(uri+'/repair-draft',headers=WRITE,json=draft_body)
        assert draft.status_code==200,draft.text
        template=draft.json()
        command={'template_snapshot_id':template['template_snapshot_id'],'annotator':'tester','expected_sequence':2,'note':'提交草稿等待验证'}
        result=client.post(uri+'/repair-completion',headers=WRITE,json=command)
        assert result.status_code==200,result.text
        saved=result.json()
        assert saved['status']=='pending_verification' and saved['sequence']==3
        assert saved['evidence']==case['evidence'] and saved['evidence_sha256']==case['evidence_sha256']
        assert [e['kind'] for e in saved['events']]==['created','attribution_submitted','repair_submitted']
        assert client.post(uri+'/repair-completion',headers=WRITE,json=command).status_code==409
        assert app.state.intent_parser.prompt_source.snapshot==base
        assert app.state.llm_captures.repository.template(base.template_snapshot_id)==base
    with TestClient(application(tmp_path)) as client:
        assert client.get(uri,headers=AUTH).json()['status']=='pending_verification'


def test_wrong_node_no_change_and_stale_attribution_reject(tmp_path):
    app=application(tmp_path)
    with TestClient(app) as client:
        case=setup_case(client);uri='/admin/bad-cases/'+case['case_id']
        a=attribution();a['node_id']=None
        assert client.post(uri+'/attribution',headers=WRITE,json=a).status_code==422
        assert client.post(uri+'/attribution',headers=WRITE,json=attribution()).status_code==200
        assert client.post(uri+'/attribution',headers=WRITE,json=attribution()).status_code==409
        base=app.state.intent_parser.prompt_source.snapshot
        unchanged={'base_snapshot_id':base.template_snapshot_id,'system_prompt':base.system_template,'expected_sequence':2}
        assert client.post(uri+'/repair-draft',headers=WRITE,json=unchanged).status_code==422
        planner=app.state.analysis_planner.prompt_source.snapshot
        mismatch={**unchanged,'base_snapshot_id':planner.template_snapshot_id,'system_prompt':'different'}
        assert client.post(uri+'/repair-draft',headers=WRITE,json=mismatch).status_code==422
        assert client.post(uri+'/events',headers=WRITE,json={'status':'pending_verification','annotator':'tester','expected_sequence':2}).status_code==422
        assert client.get(uri,headers=AUTH).json()['status']=='in_progress'


def test_changed_attribution_prevents_old_completion(tmp_path):
    app=application(tmp_path)
    with TestClient(app) as client:
        case=setup_case(client);uri='/admin/bad-cases/'+case['case_id']
        client.post(uri+'/attribution',headers=WRITE,json=attribution())
        base=app.state.intent_parser.prompt_source.snapshot
        draft=client.post(uri+'/repair-draft',headers=WRITE,json={'base_snapshot_id':base.template_snapshot_id,'system_prompt':'changed test','expected_sequence':2}).json()
        client.post(uri+'/attribution',headers=WRITE,json=attribution(2,'analysis_planner'))
        command={'template_snapshot_id':draft['template_snapshot_id'],'annotator':'tester','expected_sequence':2}
        assert client.post(uri+'/repair-completion',headers=WRITE,json=command).status_code==409
        command['expected_sequence']=3
        assert client.post(uri+'/repair-completion',headers=WRITE,json=command).status_code==422
