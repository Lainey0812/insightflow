"""Sequential calls of the existing selection node, followed by deterministic merge.

A batch owns complete task/result/metric evidence groups. There is no model
summary, cross-batch arithmetic, retry loop, new agent or independent Attempt.
"""
import asyncio
import json
from uuid import uuid4
from pydantic import ValidationError
from app.domain.errors import AppError
from app.domain.intent import LLMMetadata
from app.llm.base import LLMRequest
from app.observability.snapshots import llm_projection
from app.reporting.capacity import (GROUPS_PER_CALL, MAX_GROUPS, MAX_BATCHES,
                                    MAX_EVIDENCE, MAX_CONTEXT_BYTES, encoded_bytes)
from app.reporting.draft_v2 import InsightSelection, selection_schema, allowed_finding_types
from app.reporting.materialize_v2 import materialize_selection, invalid_candidates
from app.reporting.selection import select_evidence
from app.services.intent_parser import strict_json


def key(e):
    return e.task_id, e.data_ref, e.result_field


def required_groups(items, tasks):
    groups = {}
    for item in items:
        if tasks[item.task_id].priority == 'P0' and item.evidence_type != 'coverage':
            groups.setdefault(key(item), []).append(item.evidence_id)
    return [dict(task_id=t, data_ref=r, result_field=f, evidence_ids=ids)
            for (t, r, f), ids in groups.items()]


def payload_for(base, items, tasks, options, *, subset):
    data = dict(base)
    tids, keys = {e.task_id for e in items}, {key(e) for e in items}
    choices = {k: v for k, v in options.items()
               if (v['task_id'], v['data_ref'], v['result_field']) in keys}
    groups = {}
    for e in items:
        groups.setdefault(key(e), []).append(e.evidence_id)
    data.update(evidence=[e.model_dump() for e in items],
        required_core_groups=required_groups(items, tasks),
        required_metric_groups=[dict(task_id=t, data_ref=r, result_field=f, evidence_ids=ids)
                                for (t,r,f),ids in groups.items()],
        primary_evidence_options=[{'evidence_id':e.evidence_id,'finding_types':allowed_finding_types(e)} for e in items],
        evidence_groups=[dict(task_id=t, data_ref=r, result_field=f, evidence_ids=ids)
                         for (t, r, f), ids in groups.items()], recommendation_options=list(choices.values()))
    if subset:
        for name in ('tasks', 'scope_context', 'task_sample_context'):
            data[name] = [v for v in data[name] if v['task_id'] in tids]
    return data, choices


def partition(evidence, tasks, base, options):
    # Coverage is selected only when a task has no statistical evidence, just
    # like the original selector. All real metric groups are enumerated first.
    units = {}
    for task in sorted(tasks.values(), key=lambda t: (t.priority, t.task_id)):
        rows = [e for e in evidence if e.task_id == task.task_id]
        business = [e for e in rows if e.evidence_type != 'coverage']
        for item in business or rows:
            units.setdefault(key(item), []).append(item)
    if len(units) > MAX_GROUPS:
        raise AppError('REPORT_TOTAL_CAPACITY_EXCEEDED', '报告指标组超过总容量，计算结果保留，未删除核心指标。', 422)
    original = select_evidence(evidence, tasks)
    single, _ = payload_for(base, original, tasks, options, subset=False)
    if len(units) <= GROUPS_PER_CALL and {key(e) for e in original} == set(units) and encoded_bytes(single) <= MAX_CONTEXT_BYTES:
        return [original]
    batches, current = [], []
    for group in units.values():
        selected = select_evidence(group, tasks)
        proposal = current + selected
        payload, _ = payload_for(base, proposal, tasks, options, subset=True)
        if current and (len({key(e) for e in proposal}) > GROUPS_PER_CALL or len(proposal) > MAX_EVIDENCE or encoded_bytes(payload) > MAX_CONTEXT_BYTES):
            batches.append(current); current = []
        payload, _ = payload_for(base, current + selected, tasks, options, subset=True)
        if encoded_bytes(payload) > MAX_CONTEXT_BYTES or len(selected) > MAX_EVIDENCE:
            raise AppError('REPORT_CONTEXT_TOO_LARGE', '单个完整指标组的证据上下文过大，未拆散比较或删除指标；计算结果保留。', 422)
        current += selected
    if current:
        batches.append(current)
    if len(batches) > MAX_BATCHES:
        raise AppError('REPORT_TOTAL_CAPACITY_EXCEEDED', '实际证据需要的批次数超过总预算，未调用模型；计算结果保留。', 422)
    return batches


async def generate(service, trace, evidence, tasks, tables, profile, base, options, limitation_pool):
    from app.reporting.prompt import SYSTEM_PROMPT
    batches = partition(evidence, tasks, base, options)
    accepted, rejected, outcomes, outputs, responses = [], [], [], [], []
    first_error = None
    for index, items in enumerate(batches, 1):
        data, choices = payload_for(base, items, tasks, options, subset=len(batches) > 1)
        instruction = json.dumps(data, ensure_ascii=False)
        outcome = {'batch_index': index, 'group_refs': [list(k) for k in dict.fromkeys(key(e) for e in items)], 'status': 'failed'}
        outcomes.append(outcome)
        try:
            request = LLMRequest(purpose='report_insights_v1', system_prompt=SYSTEM_PROMPT,
                instruction=instruction, response_schema=selection_schema(items, choices, limitation_pool, data['required_metric_groups']),
                enable_thinking=service.enable_thinking)
            with trace.span('insight_generator', {'purpose': request.purpose, 'input_bytes': len(instruction.encode()),
                    'selected_evidence_count': len(items), 'evidence_refs': [e.evidence_id for e in items], 'candidate_count': None,
                    'batch_index': index, 'batch_count': len(batches),
                    'timeout_seconds': service.timeout_seconds, 'enable_thinking': service.enable_thinking}) as stage:
                if service.prompt_source:
                    request = request.model_copy(update={'call_binding': service.prompt_source.binding(uuid4().hex, trace=trace)})
                stage.event('llm.started', purpose=request.purpose, batch_index=index)
                try:
                    response = await asyncio.wait_for(service.provider.generate(request), timeout=service.timeout_seconds)
                except TimeoutError:
                    raise AppError('LLM_TIMEOUT', '报告洞察生成超时，未用虚构内容替代。', 504) from None
                except AppError:
                    raise
                except Exception:
                    raise AppError('REPORT_LLM_CALL_FAILED', '报告洞察生成失败。', 502) from None
                outputs.append(response)
                if responses and (response.provider, response.model) != (responses[0].provider, responses[0].model):
                    raise AppError('REPORT_BATCH_MODEL_MISMATCH', '批次返回的模型来源不一致，未合并该批结果。', 502)
                responses.append(response)
                stage.event('llm.returned', provider=response.provider, model=response.model, is_mock=response.is_mock,
                    output_bytes=len(response.text.encode()), call_id=response.call_id,
                    request_snapshot_id=response.request_snapshot_id, template_snapshot_id=response.template_snapshot_id)
                outcome.update(call_id=response.call_id, request_snapshot_id=response.request_snapshot_id)
                try:
                    if len(response.text.encode()) > 64 * 1024:
                        raise ValueError('Oversized response')
                    draft = InsightSelection.model_validate(strict_json(response.text))
                except (ValidationError, ValueError, TypeError, AttributeError):
                    raise AppError('REPORT_LLM_INVALID_OUTPUT', '洞察选择不符合V2结构契约，未使用旧格式或规则结果替代。', 502) from None
                stage.attributes(candidate_count=len(draft.insights), provider=response.provider, model=response.model, is_mock=response.is_mock)
            with trace.span('fact_validator', {'batch_index': index, 'batch_count': len(batches)}) as stage:
                # Only P0 tasks/metrics present in this batch are required here;
                # the assembler verifies global coverage against full Evidence.
                repairs = []
                values, failures = materialize_selection(draft, items, tasks, tables, profile, choices, limitation_pool,
                    observer=trace.candidate, repairs=repairs)
                accepted.extend(values)
                rejected.extend({**v, 'batch_index': index} for v in failures)
                stage.attributes(candidate_count=len(draft.insights), accepted_count=len(values), rejected_count=len(failures))
                invalid = invalid_candidates(failures)
                stage.terminal_status = 'partial' if invalid else 'complete'
                stage.event('report.candidates_classified', candidate_count=len(draft.insights),
                            accepted_count=len(values), rejected_count=len(failures),
                            rule_ids=['VALIDATED_REDUNDANCY'] if failures and not invalid else [])
                outcome.update(status='partial' if invalid else 'complete', accepted_count=len(values), rejected_count=len(failures),
                               redundant_count=len(failures)-len(invalid), invalid_count=len(invalid), candidate_repairs=repairs)
        except AppError as error:
            first_error = first_error or error
            outcome.update(error_code=error.error.code, accepted_count=0, rejected_count=len(error.error.details.get('rejected_candidates', [])))
            trace.event('report.batch_failed', batch_index=index, error_code=error.error.code)
    # TraceSnapshot kind is immutable per Run. Store once, not once per batch.
    if len(batches) == 1 and outputs:
        response = outputs[0]
        trace.snapshot('llm_output', response.text, lambda: llm_projection(response))
    elif len(batches) > 1:
        trace.snapshot('llm_output', json.dumps([r.text for r in outputs], ensure_ascii=False),
            lambda: {'batch_count': len(batches), 'count': len(outputs), 'batches': [llm_projection(r) for r in outputs],
                     'outcomes': outcomes, 'parsed': all(llm_projection(r).get('parsed') for r in outputs) and len(outputs) == len(batches)})
    if not accepted:
        if first_error:
            first_error.error.details['batch_results'] = outcomes
            raise first_error
        raise AppError('REPORT_NO_VALID_INSIGHTS', '所有批次均无有效洞察，计算结果保留。', 502, details={'batch_results': outcomes})
    accepted.sort(key=lambda i: tasks[i.task_id].priority)
    for index, insight in enumerate(accepted, 1):
        insight.insight_id = f'I{index:03d}'
    llm = LLMMetadata(provider=responses[0].provider, model=responses[0].model, is_mock=any(r.is_mock for r in responses))
    return accepted, rejected, outcomes, llm
