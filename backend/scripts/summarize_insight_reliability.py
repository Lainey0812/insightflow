"""Objective audit of preserved V1.1.1 runs; manual A-G review is separate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from collections import Counter

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app.domain.analysis_report import AnalysisReport,InsightDraft
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.report_presentation import ReportPresentation
from app.domain.errors import AppError
from app.reporting.claims import validate_source
from app.reporting.fact_validation import validate_comparison,materialize_candidates
from app.reporting.presentation import build_presentation
from app.reporting.export import render_report_v1
from app.storage.database import Database
from app.storage.report_repository import ReportRepository

DEST=ROOT/'docs/evaluations/insight-generator-v1.1.1'
OLD=ROOT/'docs/evaluations/insight-generator-v1.1'


def save(path,obj):
    with path.open('x') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')


def state(r):
    return 'failed' if r['error'] else r['analysis_report']['report_status']


def main():
    runs={name:json.loads(path.read_text()) for name,path in {
        'old_v114':OLD/'baseline-live-network.json','old_v116':OLD/'final-live.json',
        'v117_experiment':DEST/'frozen-live-01.json','v118_rejected_experiment':DEST/'frozen-live-02.json',
        'final_frozen':DEST/'frozen-live-final.json','new_unseen':DEST/'new-unseen-live.json'}.items()}
    summary={};table=[]
    for name,run in runs.items():
        parts={}
        for split in sorted({r['split'] for r in run['records']}):
            rows=[r for r in run['records'] if r['split']==split]
            counts=Counter(state(r) for r in rows)
            parts[split]={key:counts[key] for key in ['complete','partial','failed','unavailable']}
            parts[split].update(cases=len(rows),calls=sum(len(r['calls']) for r in rows),
                returned=sum(c['status']=='returned' for r in rows for c in r['calls']),
                reports_available=counts['complete']+counts['partial'],
                expected_generatable=len(rows)-counts['unavailable'])
        summary[name]=parts
    fixtures={c['case_id']:c for path in [OLD/'frozen-inputs-v2.json',DEST/'new-unseen-inputs-v2.json']
              for c in json.loads(path.read_text())}
    # Load the unchanged old guard in a separate module; reuse the SAME new real
    # responses. This is an offline guard contrast, never an old-model live run.
    spec=importlib.util.spec_from_file_location('app.reporting.audit_old_guard',
        DEST/'before-source/backend/app/reporting/fact_validation.py')
    old_guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(old_guard)
    contrast=[]
    checks=[]
    db_dir=ROOT/'var/insight-generator-v111-verification-20261028'
    db_dir.mkdir(exist_ok=False)
    repo=ReportRepository(Database(db_dir))
    for group in ['final_frozen','new_unseen']:
        for record in runs[group]['records']:
            cid=record['case_id'];out=DEST/'cases'/cid;out.mkdir(parents=True,exist_ok=False)
            fixture=fixtures[cid]
            table.append({'case_id':cid,'group':group,'split':record['split'],'query':record['query'],
                'status':state(record),'goal_coverage':record['analysis_report']['goal_coverage'] if record['analysis_report'] else None,
                'error':record['error'],'rejected':next(iter(record['analysis_report']['execution_metadata'].values()))['rejected_insights'] if record['analysis_report'] else []})
            save(out/'record.json',record)
            if record['calls']:
                call=record['calls'][0];save(out/'llm-input.json',call['input'])
                (out/'raw-model.txt').write_text(call.get('raw_output',''))
            if record['analysis_report']:
                report=AnalysisReport.model_validate(record['analysis_report'])
                view=ReportPresentation.model_validate(record['presentation'])
                tasks=report.task_metadata
                for evidence in report.evidence:
                    validate_source(evidence,report.result_data,tasks)
                    validate_comparison(evidence,report.result_data)
                save(out/'analysis-report.json',report.model_dump(mode='json'))
                save(out/'presentation.json',view.model_dump(mode='json'))
                (out/'report.html').write_text(render_report_v1(report,view))
                repo.save(report,{'purpose':'isolated-real-llm-evaluation','case_id':cid})
                loaded=ReportRepository(Database(db_dir)).get(report.report_id)
                after=build_presentation(loaded)
                checks.append({'case_id':cid,'report_id':report.report_id,
                    'sqlite_roundtrip_equal':loaded==report,'public_presentation_valid':bool(view),
                    'saved_source_findings_equal':len(view.findings)==len(report.insights) and all(a.title==b.finding and a.body==b.implication for a,b in zip(view.findings,report.insights)),
                    'no_separate_view_evidence':after.evidence==[],
                    'evidence_validated_count':len(report.evidence)})
            if record['calls']:
                payload=record['calls'][0]['input'];draft=InsightDraft.model_validate_json(record['calls'][0]['raw_output'])
                from app.domain.analysis_report import Evidence
                from app.domain.execution import ExecutionResultV1
                evidence=[Evidence.model_validate(e) for e in payload['evidence']]
                plan=ValidatedAnalysisPlan.model_validate(fixture['input']['validated'])
                tasks={t.task_id:t for t in plan.plan.tasks}
                execution=ExecutionResultV1.model_validate(fixture['input']['execution'])
                tables={t.result.result_id:t.result for t in execution.tasks if t.status=='success'}
                item={'case_id':cid,'mode':'offline_same_real_candidates_not_new_model_calls'}
                for key,guard in [('v116_guard',old_guard),('final_guard',sys.modules['app.reporting.fact_validation'])]:
                    try:
                        good,bad=guard.materialize_candidates(draft,evidence,tasks,tables,payload['limitations'])
                        item[key]={'accepted':len(good),'rejected':bad}
                    except AppError as exc:item[key]={'error':exc.error.code}
                contrast.append(item)
    save(DEST/'status-summary.json',summary)
    save(DEST/'case-results.json',table)
    save(DEST/'persistence-verification.json',{'database':str(db_dir.relative_to(ROOT)/'insightflow.sqlite3'),'checks':checks})
    save(DEST/'same-candidates-old-new-guard.json',contrast)
    # An independent Pandas baseline uses the actual sales CSV. No LLM computes it.
    import pandas as pd
    source=Path('/Users/lainey/Downloads/insightflow_sales_orders_test.csv')
    df=pd.read_csv(source);dates=pd.to_datetime(df['订单日期'])
    selected=df[(dates>=pd.Timestamp('2026-01-01')) & (dates<pd.Timestamp('2027-01-01')) &
                (df['地区']=='华东') & (df['订单状态']=='已完成')]
    ranked=selected.groupby('城市')['销售额'].sum().sort_values(ascending=False).head(3)
    assert ranked.to_dict()=={'济南':21250,'南京':20250,'上海':5760}
    save(DEST/'independent-sales-check.json',{'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'dataset_rows':len(df),'effective_rows':len(selected),'top3':ranked.to_dict(),'returned_top3_sum':int(ranked.sum()),
        'report_generated_in_final_live_run':False,'notice':'Evidence is correct; final real S01 report generation failed. This is not presented as report success.'})
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
