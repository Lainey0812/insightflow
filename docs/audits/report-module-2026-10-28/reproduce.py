"""Offline audit probes. Scripted outputs are not real model quality measurements.
Run from repository root: .venv/bin/python docs/audits/report-module-2026-10-28/reproduce.py
"""
import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
from app.domain.analysis_report import InsightDraft
from app.domain.errors import AppError
from app.domain.models import FileInfo,SessionState,WorkflowError
from app.domain.enums import AnalysisMode
from app.planning.capabilities import CapabilityRegistry
from app.reporting.contracts import prepare
from app.reporting.evidence import EvidenceBuilder
from app.reporting.fact_validation import materialize
from app.reporting.visualization import VisualizationBuilder
from app.services.analysis_report import AnalysisReportService
from app.storage.database import Database
from app.storage.report_repository import ReportRepository
from app.storage.session_repository import SessionRepository
from planning_fixtures import step,task
from report_fixtures import ReportProvider,report_case

out={}
raw='城市,销售额\n济南,30\n南京,20\n上海,10\n'.encode()
candidate=task([step('group_aggregate',{'dimensions':['field_0001'],'metrics':[{'function':'sum','field':'field_0002','alias':'sales'}]})])
intent,validated,execution,profile=report_case([candidate],raw)
_,desc=prepare(intent,validated,execution,profile,CapabilityRegistry())
evidence=EvidenceBuilder().build(execution,profile,desc)
primary=next(e for e in evidence if e.evidence_type=='ranking')
tasks={t.task_id:t for t in validated.plan.tasks}
texts=[
 ('unsupported_profit','济南利润高于南京，可以增加投入。'),
 ('unsupported_cause','济南销售额源自当地促销补贴。'),
 ('unsupported_percentage_words','The profit share is ninety percent.'),
 ('supported_caution','销售额不能证明盈利能力。'),
 ('supported_pair_reference','两个分组值得继续比较。'),
]
results=[]
for name,text in texts:
 draft=InsightDraft.model_validate({'insights':[{'primary_evidence_id':primary.evidence_id,'evidence_refs':[primary.evidence_id],
   'finding_type':'highlight','implication':text,'recommendation':'结合业务资料继续核查。','limitations':[]}]})
 try:
  actual=materialize(draft,evidence,tasks)
  results.append({'case':name,'text':text,'accepted':True,'returned_implication':actual[0].implication})
 except AppError as error:results.append({'case':name,'text':text,'accepted':False,'error_code':error.error.code})
out['semantic_guard']=results
assert all(r['accepted'] for r in results[:3])
assert all(not r['accepted'] for r in results[3:])

# Execute real kernels through existing fixtures, including the approved ascending operation.
ascending=task([step('group_aggregate',{'dimensions':['field_0001'],'metrics':[{'function':'sum','field':'field_0002','alias':'sales'}]}),
 step('top_n',{'field':'sales','direction':'asc','n':3},'S02')])
ascending['title']='销售额最低的三个城市'
i,v,x,p=report_case([ascending],raw)
_,d=prepare(i,v,x,p,CapabilityRegistry());e=EvidenceBuilder().build(x,p,d)
c=VisualizationBuilder().build(x,d,e,{t.task_id:t for t in v.plan.tasks},i)[0]
out['ascending_top_n']={'actual_operation':ascending['steps'][-1], 'execution_rows':x.tasks[0].result.rows,
 'first_ranking_evidence':next(z.model_dump(mode='json') for z in e if z.evidence_type=='ranking'),
 'chart_spec':c.model_dump(mode='json')}
assert x.tasks[0].result.rows[0]['field_0001']=='上海'
assert next(z for z in e if z.evidence_type=='ranking').value['category']=='济南'
assert c.order=='value_desc'

# Constraints are retained in Intent; prove that the model input does not receive them.
i.constraints.analysis_limits=[{'raw_text':'不要分析利润','validation_status':'unverified'}]
# Reparse so the audit does not depend on unvalidated Pydantic assignment.
i=type(i).model_validate(i.model_dump())
provider=ReportProvider()
report=asyncio.run(AnalysisReportService(provider,CapabilityRegistry()).generate(i,v,x,p))
payload=json.loads(provider.requests[0].instruction)
out['llm_context']={'constraint':'不要分析利润','payload_keys':list(payload),'constraint_present_in_request': '不要分析利润' in provider.requests[0].instruction,
 'constraint_retained_as_report_limitation':any('不要分析利润' in s for s in report.limitations)}
# In this standalone path limitations contain constraint text. The trusted Workflow path
# omits those unconfirmed-constraint limitations, so use a matching internal approval below.
from app.domain.execution import ApprovedExecutionSnapshot
from app.domain.intent import ParsedIntent
v.intent_snapshot=ParsedIntent.model_validate(i.model_dump())
x.source='engine'; x.session_id='audit-session';x.approval_id='audit-approval'
approved=ApprovedExecutionSnapshot(approval_id='audit-approval',approved_at='audit',session_id=x.session_id,
 intent=i,validated_plan=v,constraints_confirmed=True)
provider=ReportProvider()
asyncio.run(AnalysisReportService(provider,CapabilityRegistry()).generate(i,v,x,p,approved_snapshot=approved,original_query='只比较城市销售额，不要分析利润。'))
payload=json.loads(provider.requests[0].instruction)
out['trusted_llm_context']={'original_query':'只比较城市销售额，不要分析利润。','confirmed_constraint':'不要分析利润',
 'payload_keys':list(payload),'boundary_present_in_request':'不要分析利润' in provider.requests[0].instruction,
 'original_query_present':'只比较城市销售额，不要分析利润。' in provider.requests[0].instruction}
assert not out['trusted_llm_context']['boundary_present_in_request']

# Retry keeps only the latest attempt, using an isolated temporary database.
with tempfile.TemporaryDirectory() as temp:
 db=Database(Path(temp)); sessions=SessionRepository(db);repo=ReportRepository(db)
 state=SessionState(title='audit only',file=FileInfo(id='audit-file',name='audit.csv',size=1,extension='.csv'),user_goal='audit',analysis_mode=AnalysisMode.GOAL_DRIVEN)
 sessions.create(state);first,_=repo.queue('audit-execution',state.id);repo.start(first.execution_id,1)
 repo.finish(first.execution_id,1,error=WorkflowError(code='AUDIT_FIRST_FAILURE',message='first failed'))
 before=repo.generation(first.execution_id);second,_=repo.queue(first.execution_id,state.id,1)
 out['retry_history']={'before':before.model_dump(mode='json'),'after':second.model_dump(mode='json'),
 'session_records':[j.model_dump(mode='json') for j in sessions.get(state.id).report_generations]}
 assert second.attempt==2 and second.error is None
 assert len(sessions.get(state.id).report_generations)==1

# Precision boundary: real integer group result vs the derived float total.
large_raw='城市,销售额\n济南,9007199254740993\n'.encode()
i,v,x,p=report_case([candidate],large_raw)
_,d=prepare(i,v,x,p,CapabilityRegistry());e=EvidenceBuilder().build(x,p,d)
metric=next(z for z in e if z.evidence_type=='metric')
out['integer_precision']={'execution_value':x.tasks[0].result.rows[0]['sales'], 'returned_group_total':metric.value['value'],'statement':metric.statement,
 'equal':x.tasks[0].result.rows[0]['sales']==metric.value['value']}
assert not out['integer_precision']['equal']

snapshot_files=['backend/app/reporting/evidence.py','backend/app/reporting/fact_validation.py','backend/app/reporting/visualization.py','backend/app/services/analysis_report.py','backend/app/storage/report_repository.py','backend/app/workflow/reporting.py','backend/app/api/reports.py','frontend/src/reporting/ReportPage.tsx','frontend/src/reporting/chartAdapter.ts']
out['source_sha256']={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in snapshot_files}
output=Path(__file__).with_name('reproduction-results.json');output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k!='source_sha256'},ensure_ascii=False,indent=2))
