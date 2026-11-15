from pathlib import Path
import os,sys,runpy,json,asyncio,time,hashlib
from dataclasses import replace
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');suite=root/'docs/evaluations/report-reliability-v2.1.1-2026-11-09'
base=root/'docs/evaluations/direction-first-acceptance-v1-2026-11-09/runs/frozen-baseline-01'
runpy.run_path(str(root/'backend/scripts/run_mvp_acceptance.py'))['load_environment']()
os.environ['INSIGHTFLOW_DATA_DIR']=str(root/'var/verification/report-reliability-v211-fixed-bootstrap')
sys.path.insert(0,str(root/'backend'))
from app.core.config import Settings
from app.main import create_app
from app.llm.compatible_provider import CompatibleLLMProvider
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.domain.execution import ExecutionResultV1,ApprovedExecutionSnapshot
from app.domain.intent import ParsedIntent
from app.reporting.presentation import build_presentation

def save(path,value):
 with path.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)

async def run(cid):
 out=suite/'fixed-upstream'/cid;out.mkdir(parents=True,exist_ok=False);source=base/cid
 runtime=root/'var/verification/report-reliability-v211-fixed'/cid
 settings=replace(Settings.from_env(),data_dir=runtime)
 assert settings.llm_model=='qwen3.8-flash' and settings.llm_api_key
 class Observed(CompatibleLLMProvider):
  counter=0
  async def generate(self,request):
   self.operations.append(request.call_binding.operation_id)
   return await super().generate(request)
  async def _send(self,payload):
   self.counter+=1;index=self.counter;save(out/f'http-{index:02d}-request.json',payload)
   try:response=await super()._send(payload)
   except BaseException as e:
    save(out/f'http-{index:02d}-error.json',{'code':getattr(getattr(e,'error',None),'code',type(e).__name__)});raise
   save(out/f'http-{index:02d}-response.json',response.model_dump(mode='json'));return response
 provider=Observed(settings.llm_base_url,settings.llm_model,settings.llm_api_key,settings.llm_timeout_seconds)
 provider.operations=[]
 app=create_app(settings,provider)
 state=json.loads((source/'prepared-session.json').read_text())
 approved=json.loads((source/'approval-response.json').read_text())['engine_approval']
 validated=ValidatedAnalysisPlan.model_validate(state['review_plan']['validated_plan']);intent=ParsedIntent.model_validate(validated.intent_snapshot.model_dump())
 execution=ExecutionResultV1.model_validate_json((source/'execution-complete.json').read_text());profile=DatasetProfile.model_validate_json((source/'profile.json').read_text())
 save(out/'input-manifest.json',{'source_case':str(source.relative_to(root)),'files':{f:hashlib.sha256((source/f).read_bytes()).hexdigest() for f in ['prepared-session.json','approval-response.json','execution-complete.json','profile.json']},'mode':'standalone report-only; no Workflow/Run invented','runtime':str(runtime)})
 started=time.perf_counter()
 try:
  report=await app.state.report_service.generate(intent,validated,execution,profile,approved_snapshot=ApprovedExecutionSnapshot.model_validate(approved),original_query=state['user_goal'])
  save(out/'analysis-report.json',report.model_dump(mode='json'));save(out/'presentation.json',build_presentation(report,profile).model_dump(mode='json'))
  meta=next(iter(report.execution_metadata.values()))
  result={'case_id':cid,'report_status':report.report_status,'goal_coverage':report.goal_coverage,'insight_count':len(report.insights),'uncompleted_tasks':[t.model_dump() for t in report.uncompleted_tasks], 'rejected':meta['rejected_insights'],'missing_directions':meta.get('missing_direction_ids',[])}
 except Exception as exc:
  result={'case_id':cid,'report_status':'failed','error':exc.error.model_dump(mode='json') if hasattr(exc,'error') else {'code':type(exc).__name__}}
 result.update(elapsed_seconds=round(time.perf_counter()-started,3),http_calls=provider.counter)
 calls=[c for operation in provider.operations for c in app.state.llm_captures.repository.calls(operation_id=operation)]
 save(out/'llm-calls.json',[c.model_dump(mode='json') for c in calls]);save(out/'result.json',result)
 print(json.dumps(result,ensure_ascii=False),flush=True)
 return result
async def main():
 results=[]
 for case in ['T01','P03','R05','T05']:results.append(await run(case))
 save(suite/'fixed-upstream-results.json',results)
asyncio.run(main())
