"""Real configured report LLM, fixed synthetic nine-metric kernel result.

This is explicitly a standalone imported-result test, not a fabricated HITL run.
The real user's approved execution is independently recovered through the UI.
"""
from pathlib import Path
import sys,os,json,asyncio,runpy
ROOT=Path(__file__).resolve().parents[3]
runpy.run_path(str(ROOT/'backend/scripts/run_mvp_acceptance.py'))['load_environment']()
os.environ['INSIGHTFLOW_DATA_DIR']=str(ROOT/'var/verification/report-capacity-v1-fixed9')
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
from app.core.config import Settings
from app.llm.compatible_provider import CompatibleLLMProvider
from app.llm.capture import CallRecorder
from app.storage.prompt_registry import PromptRegistryRepository
from app.services.analysis_report import AnalysisReportService
from app.planning.capabilities import CapabilityRegistry
from app.reporting.presentation import build_presentation
from test_report_capacity import inputs

out=Path(__file__).parent/'fixed-nine-real01';out.mkdir(exist_ok=False)
def write(name,value):
    with (out/name).open('x') as handle:json.dump(value,handle,ensure_ascii=False,indent=2,default=str)
class Captured(CompatibleLLMProvider):
    index=0
    async def _send(self,payload):
        self.index+=1;index=self.index;write(f'http-{index:02}-request.json',payload)
        try:response=await super()._send(payload)
        except BaseException as error:
            write(f'http-{index:02}-error.json',{'code':getattr(getattr(error,'error',None),'code',type(error).__name__)})
            raise
        write(f'http-{index:02}-response.json',response.model_dump());return response
settings=Settings.from_env()
registry=PromptRegistryRepository(settings.data_dir/'prompt_registry')
provider=Captured(settings.llm_base_url,settings.llm_model,settings.llm_api_key,settings.llm_timeout_seconds,capture=CallRecorder(registry))
case=inputs(9)
write('input.json',{'intent':case[0].model_dump(),'validated_plan':case[1].model_dump(),'execution':case[2].model_dump(),'profile':case[3].model_dump()})
write('configuration.json',{'model':settings.llm_model,'timeout_seconds':settings.llm_timeout_seconds,'enable_thinking':settings.report_enable_thinking,'source':'synthetic_imported_kernel_result','prompt_version':'report-insights-v2.0','composition_version':'composition-v0.5-report-capacity-v1'})
try:
    report=asyncio.run(AnalysisReportService(provider,CapabilityRegistry(),settings.llm_timeout_seconds,settings.report_enable_thinking).generate(*case))
    write('report.json',report.model_dump());write('presentation.json',build_presentation(report,case[3]).model_dump())
    # Independent direct Pandas baseline for known synthetic input, no operation registry as oracle.
    import pandas as pd
    frame=pd.DataFrame({'field_0002':[100,200,300],'field_0003':[30,70,100]})
    expected={'rows':3}
    for field in frame:
        for fn in ['sum','avg','min','max']:expected[field+'_'+fn]=float(getattr(frame[field],'mean' if fn=='avg' else fn)())
    actual=report.result_data['R001'].rows[0]
    okay=all(abs(float(actual[k])-float(v))<1e-9 for k,v in expected.items())
    used={e.result_field for e in report.evidence if any(e.evidence_id in i.evidence_refs for i in report.insights)}
    write('verification.json',{'http_calls':provider.index,'report_status':report.report_status,'goal_coverage':report.goal_coverage,'expected':expected,'actual':actual,'matches_pandas':okay,'covered_metrics':sorted(used),'covered_all_nine':set(expected)<=used})
    print(json.dumps({'report_status':report.report_status,'calls':provider.index,'matches_pandas':okay,'covered_all_nine':set(expected)<=used}))
except Exception as error:
    write('failure.json',{'code':getattr(getattr(error,'error',None),'code',type(error).__name__)})
    raise
