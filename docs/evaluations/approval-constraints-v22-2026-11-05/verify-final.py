"""Read-only verification of saved synthetic runs; no additional model calls.

Structured revalidation is not a substitute for the separate A–G agent review.
Each output path is exclusive; historical evaluation records are left intact.
"""
from pathlib import Path
import sys, json
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/scripts')]
from app.domain.analysis_report import AnalysisReport, Evidence
from app.domain.dataset_profile import DatasetProfile
from app.reporting.draft_v2 import InsightSelection
from app.reporting.materialize_v2 import materialize_selection
from app.reporting.recommendations import build_catalog
from app.domain.intent import ParsedIntent
from mvp_plan_scope_audit import audit_scope

SUITES=[ROOT/'docs/evaluations/mvp-product-v1-2026-11-04',ROOT/'docs/evaluations/mvp-reliability-holdout-2026-11-04',ROOT/'docs/evaluations/mvp-reliability-holdout2-2026-11-04',ROOT/'docs/evaluations/report-draft-v2-2026-11-05/independent',Path(__file__).parent/'independent']
rows=[]
for suite in SUITES:
    for case in json.loads((suite/'frozen/cases.json').read_text()):
        if case['case_id'] not in {'T04','U02','W03','W04'}: continue
        folder=suite/'runs/approvalv22-final'/case['case_id']
        row={'case_id':case['case_id'],'source_suite':suite.name,'result':json.loads((folder/'result.json').read_text())}
        state=json.loads((folder/('approval-response.json' if (folder/'approval-response.json').exists() else 'prepared-session.json')).read_text())
        profile=DatasetProfile.model_validate(state['profile'])
        oracle=folder/'goal-oracle.json'
        if case['kind'] in {'numeric','clarify'} and oracle.exists():
            plan=state['review_plan']['validated_plan']['plan']
            matches=json.loads(oracle.read_text()).get('matches',[])
            names={f.display_name:f.field_id for f in profile.fields}
            row['exact_scope']=[audit_scope(case,next(t for t in plan['tasks'] if t['task_id']==m['task_id']),names) for m in matches]
        if (folder/'analysis-report.json').exists():
            report=AnalysisReport.model_validate(json.loads((folder/'analysis-report.json').read_text()))
            request=next(json.loads(p.read_text()) for p in folder.glob('http-*-request.json') if 'recommendation_options' in p.read_text())
            payload=json.loads(request['messages'][1]['content'])
            response=folder/(next(p.name for p in folder.glob('http-*-request.json') if json.loads(p.read_text())==request).replace('request','response'))
            draft=InsightSelection.model_validate_json(json.loads(response.read_text())['text'])
            evidence=[Evidence.model_validate(v) for v in payload['evidence']]
            # Recreate server choices from actual profile/intent, rather than
            # trusting cached model-facing option descriptions.
            intent=ParsedIntent.model_validate({k:state['intent'][k] for k in ParsedIntent.model_fields})
            options=build_catalog(evidence,report.task_metadata,profile,intent)
            sent_option_ids = {v['option_id'] for v in payload['recommendation_options']}
            options = {key: option for key, option in options.items() if key in sent_option_ids}
            accepted,rejected=materialize_selection(draft,evidence,report.task_metadata,report.result_data,profile,options,payload['limitation_pool'])
            presentation=json.loads((folder/'presentation.json').read_text())
            row.update(draft_schema='insight-selection-v2',candidate_count=len(draft.insights),accepted_count=len(accepted),rejected=rejected,
                exact_saved_insights=accepted==report.insights,
                presentation_uses_saved_findings=[v['title'] for v in presentation['findings']]==[i.finding for i in report.insights],
                evidence_refs_valid=all(set(i.evidence_refs)<={e.evidence_id for e in report.evidence} for i in report.insights),
                important_evidence_available=len(evidence),important_evidence_used=len({ref for i in accepted for ref in i.evidence_refs}),
                multi_evidence_insights=sum(len(i.evidence_refs)>1 for i in accepted))
        rows.append(row)
with (Path(__file__).parent/'saved-verification-final.json').open('x') as handle:json.dump(rows,handle,ensure_ascii=False,indent=2)
print('Verified saved records:',len(rows))
