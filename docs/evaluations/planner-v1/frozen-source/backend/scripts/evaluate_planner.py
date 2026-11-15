"""Opt-in real Planner evaluation; never calls Intent Parser or Analysis Engine."""
import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings
from app.domain.analysis_plan import AnalysisPlan
from app.domain.errors import AppError
from app.domain.intent import ParsedIntent
from app.llm.factory import create_provider
from app.planning.capabilities import CapabilityRegistry
from app.planning.evaluation import score, signature, summarize, SCORER_VERSION
from app.planning.output import request_schema
from app.planning.prompt import SYSTEM_PROMPT, PROMPT_VERSION
from app.profiling.profiler import build_profile
from app.services.analysis_planner import AnalysisPlannerService
from scripts.evaluate_intent import EvaluationRecorder

ROOT=Path(__file__).resolve().parents[2]


async def evaluate(args):
    if args.output.exists():
        raise ValueError('Output exists; refusing to overwrite evaluation history')
    suite=json.loads(args.cases.read_text())
    settings=Settings.from_env()
    profiles={name:build_profile(d['csv'].encode(),'.csv','planner_eval_'+name,d['filename']) for name,d in suite['datasets'].items()}
    registry=CapabilityRegistry()
    payload={'run_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'status':'running',
        'prompt_version':PROMPT_VERSION,'system_prompt':SYSTEM_PROMPT,
        'schema_version':'Existing AnalysisPlan/PlannerDraft V1; unchanged domain contract',
        'model':settings.llm_model,'enable_thinking':settings.planner_enable_thinking,
        'timeout_seconds':settings.llm_timeout_seconds,'max_attempts':settings.planner_max_attempts,
        'sampling_parameters':'temperature/top_p/max_tokens omitted; provider defaults',
        'scorer_version':SCORER_VERSION,'suite_sha256':hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        'domain_schema_sha256':hashlib.sha256(json.dumps(AnalysisPlan.model_json_schema(),sort_keys=True).encode()).hexdigest(),
        'provider_schema_sha256':hashlib.sha256(json.dumps(request_schema(registry),sort_keys=True).encode()).hexdigest(),
        'human_reviewed_labels':suite['human_reviewed'],'input_source':'Frozen annotated IntentResult fixtures, not freshly parsed by LLM; actual Profiler metadata from synthetic CSV',
        'dataset_contexts':{},'records':[],'repeat_records':[],'acceptance_passed':False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        text=json.dumps(payload,ensure_ascii=False,indent=2)
        if settings.llm_api_key:text=text.replace(settings.llm_api_key,'[REDACTED]')
        args.output.write_text(text+'\n')
    async def run(case,index):
        recorder=EvaluationRecorder(create_provider(settings),settings.llm_api_key)
        planner=AnalysisPlannerService(recorder,registry,settings.llm_timeout_seconds,
            max_attempts=settings.planner_max_attempts,enable_thinking=settings.planner_enable_thinking)
        intent=ParsedIntent.model_validate(case['intent']);output=None;error=None
        try:output=await planner.plan(intent,profiles[case['dataset']])
        except AppError as exc:error=exc.error.model_dump(mode='json')
        result={'case_id':case['id'],'repeat':index,'dataset':case['dataset'],'query':case['query'],
            'intent':case['intent'],'expected':case['expected'],
            'output':output.model_dump(mode='json',by_alias=True) if output else None,
            'error':error,'attempts':recorder.attempts,
            'signature':signature(output) if output else None,
            'assessment':score(case,output,profiles[case['dataset']],error)}
        if output and output.llm.is_mock:raise ValueError('Mock is forbidden in live evaluation')
        from app.planning.context import planner_context
        if intent.next_action=='proceed':
            ctx,_=planner_context(intent,profiles[case['dataset']],registry)
            payload['dataset_contexts'][case['dataset']]=ctx['profile']
        print(json.dumps({'case':case['id'],'repeat':index,'passed':result['assessment']['passed'],
                          'failures':result['assessment']['failures']},ensure_ascii=False),flush=True)
        return result
    save()
    for case in suite['cases']:
        payload['records'].append(await run(case,1));payload['summary']=summarize(payload['records']);save()
    for case_id in suite['repeat_case_ids']:
        case=next(c for c in suite['cases'] if c['id']==case_id)
        for index in range(1,args.repeats+1):
            payload['repeat_records'].append(await run(case,index));save()
    stability=[]
    for case_id in suite['repeat_case_ids']:
        records=[r for r in payload['repeat_records'] if r['case_id']==case_id]
        stability.append({'case_id':case_id,'runs':len(records),'valid_runs':sum(r['output'] is not None for r in records),
            'task_priority_operation_stable':all(r['signature'] is not None for r in records) and len({json.dumps(r['signature']) for r in records})==1,
            'all_reference_checks_pass':all(r['assessment']['passed'] for r in records)})
    payload.update(status='completed',summary=summarize(payload['records']),repeat_summary=summarize(payload['repeat_records']),
        stability=stability,bad_cases=[r for r in payload['records']+payload['repeat_records'] if not r['assessment']['passed']],
        provider_attempt_count=sum(len(r['attempts']) for r in payload['records']+payload['repeat_records']))
    save();print(json.dumps({'summary':payload['summary'],'stability':stability},ensure_ascii=False,indent=2))
    return 0 if all(r['assessment']['passed'] for r in payload['records']+payload['repeat_records']) else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--cases',type=Path,default=ROOT/'backend/evaluation/planner_cases_v1.json')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/evaluations/planner-v1/live.json')
    parser.add_argument('--repeats',type=int,default=3,choices=range(2,6))
    args=parser.parse_args()
    if not args.live:parser.error('--live is required for real network calls')
    return asyncio.run(evaluate(args))

if __name__=='__main__':raise SystemExit(main())
