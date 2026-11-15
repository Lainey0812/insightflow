"""Independently authorized metadata API. Raw snapshots and Bad Case writes each need a separate token."""
import secrets
import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from app.domain.errors import AppError
from pydantic import BaseModel
from app.domain.tracing import TraceRun, TraceSpan, TraceEvent

class RunPage(BaseModel):
    items: list[TraceRun]
    total: int
    limit: int
    offset: int
    coverage_notice: str
    collector_degraded: bool
    retention: dict

class RunDetail(BaseModel):
    run: TraceRun
    business_source: dict
    coverage_notice: str
    collector_degraded: bool

class SpanPage(BaseModel):
    items: list[TraceSpan]

class EventPage(BaseModel):
    items: list[TraceEvent]
    limit: int
    offset: int

NOTICE='Trace is best-effort; missing observations do not imply no business runs or failures.'

def create_admin_router(traces, reports, token, captures=None, snapshot_token='', runtime_templates=None, *, local_test_mode=False, lifecycle=None, workflow_trace=None, workflow_observability=None, bad_cases=None, annotation_token='', regression_runs=None, replay_runs=None):
    cookie_name='insightflow_admin_read'
    session_seconds=8*60*60
    def signature(value):
        return hmac.new(token.encode(), ('admin-read-v1:'+value).encode(), hashlib.sha256).hexdigest()
    def cookie_allowed(value):
        try:
            expires,nonce,sig=value.split('.')
            timestamp=int(expires)
            return (time.time()<timestamp<=time.time()+session_seconds and len(nonce)==32 and
                    secrets.compare_digest(sig,signature(expires+'.'+nonce)))
        except (ValueError,TypeError,AttributeError):return False
    def require_config():
        if not token:raise AppError('ADMIN_NOT_CONFIGURED','管理员只读接口尚未配置。',503)
    def valid_header(value):return bool(value) and secrets.compare_digest(value.encode(),token.encode())
    def authorize(request:Request,response:Response,x_admin_token: str = Header(default='')):
        response.headers['Cache-Control']='no-store'
        if local_test_mode:
            from app.api.local_admin_access import require_local_request
            require_local_request(request)
            response.headers['X-InsightFlow-Admin-Access']='local_test'
            return
        require_config()
        if not (valid_header(x_admin_token) if x_admin_token else cookie_allowed(request.cookies.get(cookie_name,''))):
            raise AppError('ADMIN_ACCESS_DENIED','缺少有效的管理员只读凭证。',403)

    router=APIRouter(prefix='/admin',tags=['Admin Trace V0.3'])
    protected=[Depends(authorize)]

    @router.post('/access')
    def access(request:Request,response:Response,x_admin_token:str=Header(default='')):
        if local_test_mode:
            authorize(request,response)
            return {'access':'local_test','expires_in_seconds':0}
        require_config()
        if not valid_header(x_admin_token):raise AppError('ADMIN_ACCESS_DENIED','管理员只读凭证无效。',403)
        value=str(int(time.time())+session_seconds)+'.'+secrets.token_hex(16)
        response.set_cookie(cookie_name,value+'.'+signature(value),max_age=session_seconds,
            httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/')
        response.headers['Cache-Control']='no-store'
        return {'access':'read_only','expires_in_seconds':session_seconds}

    @router.delete('/access',status_code=204)
    def clear_access(response:Response,x_admin_request:str=Header(default='')):
        if x_admin_request!='1':raise AppError('ADMIN_ACCESS_DENIED','请通过管理页面退出访问。',403)
        response.delete_cookie(cookie_name,path='/',httponly=True,samesite='strict')
        response.status_code=204
        response.headers['Cache-Control']='no-store'
        return response
    def read(action):
        try:return action()
        except AppError:raise
        except Exception:raise AppError('TRACE_UNAVAILABLE','追踪查询暂不可用。',503) from None
    def find_run(run_id):
        run=read(lambda:traces.repository.get(run_id))
        if not run:raise AppError('TRACE_RUN_NOT_FOUND','追踪记录不存在。',404)
        return run
    def find_span(span_id):
        span=read(lambda:traces.repository.span(span_id))
        if not span:raise AppError('TRACE_SPAN_NOT_FOUND','追踪阶段不存在。',404)
        return span

    if workflow_observability:
        from app.domain.lifecycle import LifecycleStatus
        @router.get('/workflow-observability',dependencies=protected)
        def workflow_list(workflow_id:str|None=Query(None,min_length=1,max_length=120),
                          session_id:str|None=Query(None,min_length=1,max_length=120),
                          status:LifecycleStatus|None=None,failure_category:str|None=Query(None,min_length=1,max_length=40),
                          limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
            return read(lambda:workflow_observability.list(workflow_id=workflow_id,session_id=session_id,status=status,
                failure_category=failure_category,limit=limit,offset=offset))
        @router.get('/workflow-observability/{workflow_id}',dependencies=protected)
        def workflow_observability_detail(workflow_id:str):
            return read(lambda:workflow_observability.get(workflow_id))

    if workflow_trace:
        @router.get('/workflow-traces/{workflow_id}',dependencies=protected)
        def workflow_trace_detail(workflow_id:str):
            return read(lambda:workflow_trace.get(workflow_id))

    @router.get('/runs',response_model=RunPage,dependencies=protected)
    def runs(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000),
             status:Literal['queued','running','waiting_input','waiting_approval','complete','partial','unavailable','failed','interrupted']|None=None,
             kind:Literal['workflow','report_generation']='report_generation',
             from_time:datetime|None=None,to_time:datetime|None=None,
             node:str|None=Query(None,min_length=1,max_length=128),version:str|None=Query(None,min_length=1,max_length=160)):
        if any(t is not None and t.tzinfo is None for t in (from_time,to_time)):
            raise AppError('TRACE_INVALID_TIME','时间筛选必须包含时区。',422)
        if from_time and to_time and from_time>to_time:
            raise AppError('TRACE_INVALID_TIME','开始时间不能晚于结束时间。',422)
        items,total=read(lambda:traces.repository.runs(limit,offset,status,
            from_time=from_time.astimezone(timezone.utc).isoformat() if from_time else None,
            to_time=to_time.astimezone(timezone.utc).isoformat() if to_time else None,node=node,version=version,kind=kind))
        return {'items':items,'total':total,'limit':limit,'offset':offset,'coverage_notice':NOTICE,
            'collector_degraded':traces.degraded,
            'retention':{'metadata':'keep_until_explicit_policy_change','raw_content':'not_collected',
                'max_events_per_run':256,'max_event_payload_bytes':8192}}

    @router.get('/workflows/{session_id}',dependencies=protected)
    def workflow_root(session_id:str):
        root=read(lambda:traces.repository.workflow(session_id))
        return {'availability':'available' if root else 'not_collected','run':root,
                'observation_gap':True if session_id in traces.workflow_gaps else None,
                'coverage_notice':'Preparation only in V0.3.1; historical sessions are not backfilled.'}

    from app.domain.lifecycle import LifecycleReadModel

    @router.get('/workflows/{session_id}/lifecycle',response_model=LifecycleReadModel,dependencies=protected)
    def workflow_lifecycle(session_id:str):
        if lifecycle is None:
            raise AppError('LIFECYCLE_UNAVAILABLE','生命周期只读查询尚未配置。',503)
        return read(lambda:lifecycle.get(session_id))

    @router.get('/runs/{run_id}/events',dependencies=protected)
    def run_events(run_id:str,limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
        find_run(run_id)
        events=read(lambda:traces.repository.run_events(run_id))
        return {'items':events[offset:offset+limit],'limit':limit,'offset':offset}

    @router.get('/comparison',dependencies=protected)
    def comparison(left:str=Query(min_length=1,max_length=160),right:str=Query(min_length=1,max_length=160)):
        from app.observability.comparison import compare
        a,b=find_run(left),find_run(right)
        if left==right:raise AppError('TRACE_DISTINCT_RUNS_REQUIRED','请选择两次不同运行。',422)
        return read(lambda:compare(traces.repository,reports,a,b))

    @router.get('/runs/{run_id}/snapshots',dependencies=protected)
    def snapshots(run_id:str):
        from app.observability.comparison import artifacts
        record=find_run(run_id)
        return {'artifacts':read(lambda:artifacts(traces.repository,reports,record))}

    @router.get('/runs/{run_id}',response_model=RunDetail,dependencies=protected)
    def run(run_id:str):
        record=find_run(run_id)
        source={'available':False,'latest_attempt':None,'status':None,'same_attempt':False,'report_status':None,'goal_coverage':None}
        try:
            generation=reports.generation(record.execution_id)
            if generation:
                source.update(available=True,latest_attempt=generation.attempt,status=generation.status,
                              same_attempt=generation.attempt==record.attempt)
            if record.report_id:
                report=reports.get(record.report_id)
                source.update(report_status=report.report_status,goal_coverage=report.goal_coverage)
        except Exception:pass
        return {'run':record,'business_source':source,'coverage_notice':NOTICE,'collector_degraded':traces.degraded}

    @router.get('/runs/{run_id}/spans',response_model=SpanPage,dependencies=protected)
    def spans(run_id:str):
        find_run(run_id)
        return {'items':read(lambda:traces.repository.spans(run_id))}

    @router.get('/spans/{span_id}/events',response_model=EventPage,dependencies=protected)
    def events(span_id:str,limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
        find_span(span_id)
        return {'items':read(lambda:traces.repository.events(span_id,limit,offset)),'limit':limit,'offset':offset}

    def registry():
        if not captures or not captures.repository:
            raise AppError('LLM_SNAPSHOT_UNAVAILABLE','模型调用快照存储不可用。',503)
        return captures.repository

    def prompt_queries():
        from app.services.prompt_registry_query import PromptRegistryQuery
        return PromptRegistryQuery(registry(),runtime_templates,traces.repository)

    @router.get('/prompts',dependencies=protected)
    def prompts(node:Literal['intent_parser','analysis_planner','insight_generator']|None=None):
        return read(lambda:prompt_queries().catalog(node))

    @router.get('/prompts/compare',dependencies=protected)
    def prompt_compare(left:str=Query(min_length=1,max_length=160),right:str=Query(min_length=1,max_length=160)):
        return read(lambda:prompt_queries().compare(left,right))

    @router.get('/prompts/{node}/versions',dependencies=protected)
    def prompt_history(node:str,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
        return read(lambda:prompt_queries().history(node,limit,offset))

    @router.get('/prompts/{node}/versions/{snapshot_id}',dependencies=protected)
    def prompt_version(node:str,snapshot_id:str):
        return read(lambda:prompt_queries().detail(node,snapshot_id))

    @router.get('/prompts/{node}/versions/{snapshot_id}/calls',dependencies=protected)
    def prompt_version_calls(node:str,snapshot_id:str,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
        return read(lambda:prompt_queries().calls(node,snapshot_id,limit,offset))

    @router.get('/llm-calls/{call_id}/summary',dependencies=protected)
    def llm_call_summary(call_id:str):
        return read(lambda:prompt_queries().call_summary(call_id))

    @router.get('/runs/{run_id}/llm-calls',dependencies=protected)
    def run_calls(run_id:str):
        find_run(run_id)
        items=read(lambda:registry().calls(run_id=run_id))
        return {'availability':'available' if items else 'unavailable','items':items,
            'notice':'No historical request reconstruction. Empty calls can mean skipped or not collected.'}

    @router.get('/spans/{span_id}/llm-calls',dependencies=protected)
    def span_calls(span_id:str):
        find_span(span_id)
        items=read(lambda:registry().calls(span_id=span_id))
        return {'availability':'available' if items else 'unavailable','items':items}

    @router.get('/llm-calls/{call_id}',dependencies=protected)
    def llm_call(call_id:str):
        record=read(lambda:registry().call(call_id))
        if not record:raise AppError('LLM_CALL_NOT_FOUND','模型调用记录不存在。',404)
        snapshot=read(lambda:registry().snapshot(record.request_snapshot_id))
        return {'call':record,'request_snapshot':snapshot,'raw_content':'requires_separate_authorization'}

    def require_snapshot_token(token):
        if not local_test_mode and (not snapshot_token or not secrets.compare_digest(token.encode(),snapshot_token.encode())):
            raise AppError('SNAPSHOT_ACCESS_DENIED','完整模型请求与返回需要额外的快照读取凭证。',403)

    @router.get('/llm-calls/{call_id}/response',dependencies=protected)
    def response_content(call_id:str,x_admin_snapshot_token:str=Header(default='')):
        require_snapshot_token(x_admin_snapshot_token)
        record=read(lambda:registry().call(call_id))
        if not record:raise AppError('LLM_CALL_NOT_FOUND','模型调用记录不存在。',404)
        stored=read(lambda:registry().response(call_id))
        if stored is None:
            raise AppError('LLM_RESPONSE_UNAVAILABLE','模型返回未保留：早于本功能、无响应（如超时）或已过期；哈希与调用记录仍保留。',410)
        return {'call_id':call_id,'call_status':record.status,'error_code':record.error_code,**stored}

    @router.get('/llm-calls/{call_id}/request',dependencies=protected)
    def request_content(call_id:str,x_admin_snapshot_token:str=Header(default='')):
        require_snapshot_token(x_admin_snapshot_token)
        record=read(lambda:registry().call(call_id))
        if not record:raise AppError('LLM_CALL_NOT_FOUND','模型调用记录不存在。',404)
        payload=read(lambda:registry().payload(record.request_snapshot_id))
        if payload is None:raise AppError('LLM_REQUEST_UNAVAILABLE','原始请求未保留或已过期；哈希与调用记录仍保留。',410)
        return {'request_snapshot_id':record.request_snapshot_id,'payload':payload}

    @router.get('/prompt-templates/{snapshot_id}',dependencies=protected)
    def prompt_template(snapshot_id:str):
        record=read(lambda:registry().template(snapshot_id))
        if not record:raise AppError('PROMPT_TEMPLATE_NOT_FOUND','模板快照不存在。',404)
        return record

    from app.domain.bad_case import BadCaseCategory, BadCaseCreate, BadCaseStatus, BadCaseTransition
    def bad_case_service():
        if bad_cases is None:raise AppError('BAD_CASES_UNAVAILABLE','Bad Case 存储未配置。',503)
        return bad_cases
    def require_annotation_token(token):
        if local_test_mode:return
        if not annotation_token:raise AppError('ANNOTATION_NOT_CONFIGURED','未配置标注凭证（INSIGHTFLOW_ADMIN_ANNOTATION_TOKEN），Admin 只读。',503)
        if not secrets.compare_digest(token.encode(),annotation_token.encode()):
            raise AppError('ANNOTATION_ACCESS_DENIED','保存或修改 Bad Case 需要有效的标注凭证。',403)

    @router.get('/bad-cases',dependencies=protected)
    def list_bad_cases(workflow_id:str|None=Query(None,min_length=1,max_length=120),status:BadCaseStatus|None=None,
                       category:BadCaseCategory|None=None,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
        return bad_case_service().list(workflow_id=workflow_id,status=status,category=category,limit=limit,offset=offset)

    @router.get('/bad-cases/{case_id}',dependencies=protected)
    def get_bad_case(case_id:str):
        return bad_case_service().get(case_id)

    @router.post('/bad-cases',dependencies=protected,status_code=201)
    def create_bad_case(body:BadCaseCreate,x_admin_annotation_token:str=Header(default='')):
        require_annotation_token(x_admin_annotation_token)
        return bad_case_service().create(body)

    @router.post('/bad-cases/{case_id}/events',dependencies=protected,status_code=201)
    def transition_bad_case(case_id:str,body:BadCaseTransition,x_admin_annotation_token:str=Header(default='')):
        require_annotation_token(x_admin_annotation_token)
        return bad_case_service().transition(case_id,body)

    def regression_service():
        if regression_runs is None:raise AppError('REGRESSION_UNAVAILABLE','回归结果目录未配置。',503)
        return regression_runs

    @router.get('/regression-runs',dependencies=protected)
    def list_regression_runs():
        return regression_service().list()

    @router.get('/regression-compare',dependencies=protected)
    def compare_regression_runs(left:str=Query(min_length=1,max_length=80),right:str=Query(min_length=1,max_length=80)):
        return regression_service().compare(left,right)

    @router.get('/regression-runs/{run_id}',dependencies=protected)
    def get_regression_run(run_id:str):
        return regression_service().get(run_id)

    def replay_service():
        if replay_runs is None:raise AppError('REPLAY_UNAVAILABLE','回放结果目录未配置。',503)
        return replay_runs

    @router.get('/replay-runs',dependencies=protected)
    def list_replay_runs():
        return replay_service().list()

    @router.get('/replay-runs/{run_id}',dependencies=protected)
    def get_replay_run(run_id:str):
        return replay_service().get(run_id)
    return router
