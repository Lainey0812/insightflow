"""Opt-in real report-only evaluation. Frozen deterministic inputs; no mock model fallback."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app.core.config import Settings
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.analysis_report import InsightDraft
from app.domain.dataset_profile import DatasetProfile
from app.domain.execution import ExecutionResultV1,ApprovedExecutionSnapshot
from app.domain.intent import ParsedIntent
from app.domain.errors import AppError
from app.llm.factory import create_provider
from app.planning.capabilities import CapabilityRegistry
from app.reporting.presentation import build_presentation
from app.reporting.export import render_report_v1
from app.reporting.prompt import PROMPT_VERSION
from app.services.analysis_report import AnalysisReportService


def load_env(path):
    # Read configuration only into this process. Never print env, headers, keys or exception reprs.
    if not path.exists():return
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        key,value=line.removeprefix('export ').split('=',1)
        if not key.startswith('INSIGHTFLOW_'):continue
        values=shlex.split(value,comments=True)
        if values:os.environ.setdefault(key,values[0])


async def main(args):
    if args.output.exists():raise ValueError('Refusing to overwrite real evaluation history')
    load_env(args.env_file)
    settings=Settings.from_env()
    if settings.llm_model!='qwen3.8-flash':raise ValueError('Expected existing qwen3.8-flash configuration')
    suite=json.loads(args.inputs.read_text())
    result={'started_at':datetime.now(timezone.utc).isoformat(),'prompt_version':PROMPT_VERSION,
      'model':settings.llm_model,'enable_thinking':False,'timeout_seconds':settings.llm_timeout_seconds,
      'sampling':'temperature/top_p not explicitly set; server default unknown','schema_version':'analysis-report-v1',
      'inputs_sha256':hashlib.sha256(args.inputs.read_bytes()).hexdigest(),'status':'running','records':[]}
    result['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [*list((ROOT/'backend/app/reporting').glob('*.py')),ROOT/'backend/app/services/analysis_report.py']}
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if settings.llm_api_key:text=text.replace(settings.llm_api_key,'[REDACTED]')
        args.output.write_text(text+'\n')
    save()
    class Recorder:
        def __init__(self):self.delegate=create_provider(settings);self.calls=[]
        async def generate(self,request):
            c={'system_prompt':request.system_prompt,'response_schema':request.response_schema,'input':json.loads(request.instruction),
               'purpose':request.purpose,'enable_thinking':request.enable_thinking,'status':'calling'}
            self.calls.append(c);start=time.perf_counter()
            try:
                response=await self.delegate.generate(request)
                if response.is_mock:raise ValueError('Mock rejected')
                c.update(status='returned',raw_output=response.text,model=response.model,is_mock=False)
                return response
            except AppError as e:c.update(status='failed',error_code=e.error.code);raise
            finally:c['duration_seconds']=round(time.perf_counter()-start,4)
    for case in suite:
        rec=Recorder();inputs=case['input'];report=None;error=None;presentation=None
        try:
            kwargs={}
            if inputs.get('approved_snapshot'):kwargs['approved_snapshot']=ApprovedExecutionSnapshot.model_validate(inputs['approved_snapshot'])
            if inputs.get('original_query'):kwargs['original_query']=inputs['original_query']
            report=await AnalysisReportService(rec,CapabilityRegistry(),settings.llm_timeout_seconds,False).generate(
                ParsedIntent.model_validate(inputs['intent']),ValidatedAnalysisPlan.model_validate(inputs['validated']),
                ExecutionResultV1.model_validate(inputs['execution']),DatasetProfile.model_validate(inputs['profile']),**kwargs)
            presentation=build_presentation(report,DatasetProfile.model_validate(inputs['profile']))
        except AppError as e:error=e.error.model_dump(mode='json')
        except Exception as e:error={'code':'EVALUATION_ERROR','type':type(e).__name__}
        entry={'case_id':case['case_id'],'split':case['split'],'domain':case['domain'],'query':case['query'],
           'calls':rec.calls,'error':error,'analysis_report':report.model_dump(mode='json') if report else None,
           'presentation':presentation.model_dump(mode='json') if presentation else None}
        if report:
            dest=args.output.parent/(args.output.stem+'-html');dest.mkdir(exist_ok=True)
            (dest/(case['case_id']+'.html')).write_text(render_report_v1(report,presentation))
        result['records'].append(entry);save()
        print(json.dumps({'case':case['case_id'],'calls':len(rec.calls),'report':bool(report),'error':error and error.get('code')},ensure_ascii=False),flush=True)
    result.update(status='completed',finished_at=datetime.now(timezone.utc).isoformat());save()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--inputs',type=Path,default=ROOT/'docs/evaluations/insight-generator-v1.1/frozen-inputs-v2.json')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--env-file',type=Path,default=ROOT/'backend/.env')
    a=p.parse_args()
    if not a.live:p.error('--live required')
    asyncio.run(main(a))
