"""Validate model selections, then express only controlled, source-bound content."""
from app.domain.analysis_report import Insight
from app.domain.errors import AppError
from . import claims
from .fact_validation import COMPATIBLE, validate_comparison, semantic_key
from .recommendations import NO_RECOMMENDATION, render_option

IMPLICATIONS = {
    'highlight': '该发现对应当前统计指标，仅说明已返回数据的数值位置，不代表经营优劣，也未验证其原因。',
    'difference': '该比较展示同一统计口径下已返回对象的差异；不能据此判断差异原因、人员绩效或经营效率。',
    'concentration': '该构成结论仅适用于证据明确的分母范围，不能直接外推整体市场或未覆盖的数据。',
    'trend': '该结果仅比较证据中的已返回时间点，不能认定期间持续变化，也不能预测未来。',
    'coverage': '有效样本与数据覆盖决定本次结论的适用范围；不能据此认定未覆盖记录具有相同特征。',
}


def materialize_selection(draft, evidence, tasks, tables, profile, recommendations,
                          limitation_pool, *, observer=None, repairs=None):
    by_id = {e.evidence_id: e for e in evidence}
    accepted, rejected, seen = [], [], set()
    first_error = None
    def observe(**payload):
        if observer:
            try:
                observer(payload)
            except Exception:
                pass  # Observation remains fail-open.
    for index, choice in enumerate(draft.insights):
        try:
            # Exact repeated identifiers are a format defect, not new facts.
            # Keep the raw choice intact and still validate every remaining binding.
            refs = list(dict.fromkeys(choice.evidence_refs))
            if not set(refs) <= by_id.keys() or choice.primary_evidence_id not in refs:
                raise AppError('REPORT_INVALID_EVIDENCE_REFERENCE', '洞察必须引用合法、唯一且包含主证据的集合。', 502,
                               details={'rule': 'V2_EVIDENCE_IDS'})
            primary = by_id[choice.primary_evidence_id]
            selected = [by_id[ref] for ref in refs]
            claims.compatible(primary, selected)
            if primary.evidence_type not in COMPATIBLE[choice.finding_type]:
                raise AppError('REPORT_INVALID_EVIDENCE_TYPE', '发现类型与主证据不匹配。', 502)
            if choice.finding_type == 'concentration' and primary.evidence_type == 'comparison' and primary.value.get('comparison_kind') != 'returned_concentration':
                raise AppError('REPORT_INVALID_EVIDENCE_TYPE', '构成发现缺少对应分母证据。', 502)
            for item in selected:
                claims.validate_source(item, tables, tasks)
                validate_comparison(item, tables)
            keys = {semantic_key(e) for e in selected}
            if len(choice.limitation_refs) != len(set(choice.limitation_refs)) or not set(choice.limitation_refs) <= limitation_pool.keys():
                raise AppError('REPORT_INVALID_LIMITATION_REFERENCE', '局限必须引用已验证且唯一的局限ID。', 502)
            if choice.recommendation_id == 'none':
                recommendation = NO_RECOMMENDATION
            else:
                option = recommendations.get(choice.recommendation_id)
                if option is None:
                    raise AppError('REPORT_INVALID_RECOMMENDATION', '建议选项不存在。', 502)
                recommendation = render_option(option, primary, tasks, profile)
            finding = claims.compose(selected, tables)
            fact = claims.fact_details(selected)
            if len(finding) > 1800 or len(fact) > 2000:
                raise AppError('REPORT_FACT_COMPOSITION_TOO_LARGE', '证据组合过长。', 502)
            if refs != choice.evidence_refs:
                repair = {'candidate_index': index, 'rule_id': 'EXACT_DUPLICATE_REFERENCE',
                    'original_refs': list(choice.evidence_refs), 'normalized_refs': refs, 'validated': True}
                if repairs is not None:
                    repairs.append(repair)
                observe(candidate_index=index, candidate_status='format_repaired',
                        primary_evidence_id=choice.primary_evidence_id, evidence_refs=refs,
                        rule_ids=['EXACT_DUPLICATE_REFERENCE'])
            # Validate every source, operand, type, recommendation and limitation
            # before classifying a candidate as harmless redundancy. A repeated
            # primary with additional verified facts is not a duplicate.
            if keys <= seen:
                redundant = {'candidate_index': index, 'primary_evidence_id': choice.primary_evidence_id,
                    'error_code': 'REPORT_DUPLICATE_FINDING', 'details': {'rule': 'ALREADY_COVERED_FACTS'},
                    'disposition': 'redundant', 'validated': True}
                rejected.append(redundant)
                observe(candidate_index=index, candidate_status='redundant', primary_evidence_id=choice.primary_evidence_id,
                        evidence_refs=refs, rule_ids=['ALREADY_COVERED_FACTS'], error_code='REPORT_DUPLICATE_FINDING')
                continue
            limitations = [limitation_pool[ref] for ref in choice.limitation_refs]
            limitations.append('本报告未验证差异原因或业务效果；后续建议尚未执行。')
            accepted.append(Insight(insight_id=f'I{len(accepted)+1:03d}', task_id=primary.task_id,
                fact=fact, finding=finding, implication=IMPLICATIONS[choice.finding_type],
                recommendation=recommendation, evidence_refs=refs, limitations=limitations))
            seen.update(keys)
            observe(candidate_index=index, candidate_status='accepted', primary_evidence_id=choice.primary_evidence_id,
                    evidence_refs=refs, recommendation_id=choice.recommendation_id,
                    limitation_refs=choice.limitation_refs)
        except AppError as error:
            first_error = first_error or error
            rejected.append({'candidate_index': index, 'primary_evidence_id': choice.primary_evidence_id,
                             'error_code': error.error.code, 'details': dict(error.error.details)})
            observe(candidate_index=index, candidate_status='rejected', primary_evidence_id=choice.primary_evidence_id,
                    evidence_refs=choice.evidence_refs, error_code=error.error.code,
                    rule_ids=[error.error.details.get('rule', error.error.code)])
    observe(candidate_count=len(draft.insights), accepted_count=len(accepted), rejected_count=len(rejected))
    if not accepted:
        if first_error:
            first_error.error.details['rejected_candidates'] = rejected
            raise first_error
        raise AppError('REPORT_NO_VALID_INSIGHTS', '没有可保存的有效洞察。', 502)
    missing_tasks = {e.task_id for e in evidence if tasks[e.task_id].priority == 'P0'} - {i.task_id for i in accepted}
    if missing_tasks:
        raise AppError('REPORT_CORE_FINDINGS_MISSING', '核心任务尚无有效发现，计算结果保留。', 502,
                       details={'task_ids': sorted(missing_tasks)})
    return sorted(accepted, key=lambda i: (tasks[i.task_id].priority, i.insight_id)), rejected


def invalid_candidates(candidates):
    """Only validator-produced, fully checked redundancy is non-degrading."""
    return [c for c in candidates if not (c.get('error_code') == 'REPORT_DUPLICATE_FINDING'
        and c.get('disposition') == 'redundant' and c.get('validated') is True)]
