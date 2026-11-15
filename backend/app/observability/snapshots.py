"""Bounded controlled projections. No raw dataset, prompt, output prose or credentials."""
from app.observability.provenance import digest


def evidence_projection(items):
    return {'count': len(items), 'items': [dict(evidence_id=e.evidence_id, task_id=e.task_id,
        data_ref=e.data_ref, result_field=e.result_field, evidence_type=e.evidence_type,
        value={k: v if type(v) in (int, float, bool) or v is None else {'text_sha256': digest(v)}
               for k, v in e.value.items()}, scope_sha256=digest(e.scope),
        calculation_sha256=digest(e.calculation), source_row_indices=e.source_row_indices,
        related_result_refs=e.related_result_refs) for e in items[:100]],
        'truncated': len(items) > 100}


def draft_projection(draft):
    return {'count': len(draft.insights), 'items': [dict(primary_evidence_id=i.primary_evidence_id,
        evidence_refs=i.evidence_refs, finding_type=i.finding_type,
        implication_sha256=digest(i.implication), recommendation_sha256=digest(i.recommendation),
        limitations_sha256=digest(i.limitations)) for i in draft.insights]}


def report_projection(report):
    return {'report_id': report.report_id, 'report_status': report.report_status,
        'goal_coverage': report.goal_coverage, 'insight_count': len(report.insights),
        'summary_sha256': digest(report.summary),
        'insights': [dict(insight_id=i.insight_id, task_id=i.task_id, evidence_refs=i.evidence_refs,
            fact_sha256=digest(i.fact), finding_sha256=digest(i.finding),
            implication_sha256=digest(i.implication), recommendation_sha256=digest(i.recommendation))
            for i in report.insights[:8]],
        'uncompleted_task_ids': [t.task_id for t in report.uncompleted_tasks],
        'chart_count': len(report.charts), 'limitations_sha256': digest(report.limitations)}


def llm_projection(response):
    from app.domain.analysis_report import InsightDraft
    from app.reporting.draft_v2 import InsightSelection
    from app.services.intent_parser import strict_json
    result={'output_bytes':len(response.text.encode()),'provider':response.provider,
            'model':response.model, 'parsed':False}
    if len(response.text.encode()) > 64*1024:
        return result
    try:
        data = strict_json(response.text)
        # This is a read-only projection, not runtime acceptance or a fallback.
        if any('recommendation_id' in item for item in data.get('insights', [])):
            draft = InsightSelection.model_validate(data)
            result.update(parsed=True, draft_schema_version='insight-selection-v2',
                count=len(draft.insights), items=[dict(primary_evidence_id=i.primary_evidence_id,
                evidence_refs=i.evidence_refs, finding_type=i.finding_type,
                recommendation_id=i.recommendation_id, limitation_refs=i.limitation_refs)
                for i in draft.insights])
        else:
            result.update(draft_projection(InsightDraft.model_validate(data)),parsed=True)
    except (ValueError,TypeError,AttributeError):
        pass
    return result
