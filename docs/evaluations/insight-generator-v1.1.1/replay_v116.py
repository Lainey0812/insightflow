import asyncio, json, sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root/'backend'))
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.execution import ExecutionResultV1,ApprovedExecutionSnapshot
from app.domain.intent import ParsedIntent
from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.llm.base import LLMResponse
from app.planning.capabilities import CapabilityRegistry
from app.services.analysis_report import AnalysisReportService
from app.reporting.presentation import build_presentation
p=root/'docs/evaluations/insight-generator-v1.1'
records={r['case_id']:r for r in json.loads((p/'final-live.json').read_text())['records']}
class Replay:
 def __init__(self,cid):self.cid=cid
 async def generate(self,request):return LLMResponse(text=records[self.cid]['calls'][0]['raw_output'],provider='offline-saved-real-response',model='qwen3.8-flash',is_mock=False)
async def main():
 results=[]
 for case in json.loads((p/'frozen-inputs-v2.json').read_text()):
  x=case['input'];kwargs={}
  if x.get('approved_snapshot'):kwargs['approved_snapshot']=ApprovedExecutionSnapshot.model_validate(x['approved_snapshot'])
  if x.get('original_query'):kwargs['original_query']=x['original_query']
  try:
   report=await AnalysisReportService(Replay(case['case_id']),CapabilityRegistry()).generate(ParsedIntent.model_validate(x['intent']),ValidatedAnalysisPlan.model_validate(x['validated']),ExecutionResultV1.model_validate(x['execution']),DatasetProfile.model_validate(x['profile']),**kwargs)
   entry={'case_id':case['case_id'],'status':report.report_status,'coverage':report.goal_coverage,'insights':len(report.insights),'report':report.model_dump(mode='json'),'presentation':build_presentation(report).model_dump(mode='json')}
   print(case['case_id'],report.report_status,report.goal_coverage,'accepted',len(report.insights),'reject',report.execution_metadata[next(iter(report.execution_metadata))]['rejected_insights'])
  except AppError as e:entry={'case_id':case['case_id'],'status':'failed','error':e.error.model_dump(mode='json')};print(case['case_id'],'ERROR',e.error.code,e.error.details)
  results.append(entry)
 dest=root/'docs/evaluations/insight-generator-v1.1.1/offline-v116-on-final-code.json'
 with dest.open('x') as f:json.dump({'mode':'offline_not_new_llm_evaluation','records':results},f,ensure_ascii=False,indent=2)
asyncio.run(main())
