import asyncio
import json
from uuid import uuid4

from pydantic import ValidationError

from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.analysis_report import (AnalysisReport, InsightDraft, KeyMetric, Recommendation, Summary, UncompletedTask)
from app.domain.dataset_profile import DatasetProfile
from app.domain.execution import ExecutionResultV1
from app.domain.errors import AppError
from app.domain.intent import IntentArtifact, LLMMetadata, ParsedIntent
from app.domain.models import now
from app.domain.provenance import Provenance
from app.llm.base import LLMProvider, LLMRequest
from app.planning.capabilities import CapabilityRegistry
from app.reporting.contracts import prepare
from app.reporting.evidence import EvidenceBuilder
from app.reporting.fact_validation import materialize_candidates
from app.reporting.prompt import SYSTEM_PROMPT, request_schema
from app.reporting.prompt import GENERATION_VERSION
from app.reporting.selection import select_evidence
from app.reporting.visualization import VisualizationBuilder
from app.services.intent_parser import strict_json


class AnalysisReportService:
    def __init__(self, provider: LLMProvider, registry: CapabilityRegistry, timeout_seconds=30, enable_thinking=False):
        if not 0 < timeout_seconds <= 300:
            raise ValueError("Report timeout must be within (0, 300]")
        self.provider, self.registry, self.timeout_seconds = provider, registry, timeout_seconds
        self.enable_thinking = enable_thinking

    async def generate(self, intent: ParsedIntent, validated: ValidatedAnalysisPlan,
                       execution: ExecutionResultV1, profile: DatasetProfile, *, approved_snapshot=None, original_query=None) -> AnalysisReport:
        # Reparse all input instances; neither model_copy nor caller validation claims are trusted.
        try:
            intent = type(intent).model_validate(intent.model_dump())
            execution = ExecutionResultV1.model_validate(execution.model_dump())
            validated = ValidatedAnalysisPlan.model_validate(validated.model_dump())
            profile = DatasetProfile.model_validate(profile.model_dump())
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise AppError("REPORT_INPUT_INVALID", "报告输入结构不正确，未生成报告。", 422) from None
        if len(execution.model_dump_json().encode()) > 4 * 1024 * 1024:
            raise AppError("REPORT_INPUT_TOO_LARGE", "计算结果过大，请缩小返回结果范围并明确截断信息。", 422)
        checked, descriptions = prepare(intent, validated, execution, profile, self.registry)
        tasks = {task.task_id: task for task in checked.plan.tasks}
        evidence = EvidenceBuilder().build(execution, profile, descriptions)
        # Stable task priority ordering, retaining evidence IDs and row references.
        evidence.sort(key=lambda item: (tasks[item.task_id].priority, item.evidence_id))
        evidenced_tasks = {item.task_id for item in evidence}
        uncompleted = [UncompletedTask(task_id=t.task_id, title=tasks[t.task_id].title,
            priority=tasks[t.task_id].priority,
            reason=t.failure_reason or "结果没有可用于报告的有效数据证据。")
            for t in execution.tasks if t.status != "success" or t.task_id not in evidenced_tasks]
        core_tasks = [task for task in tasks.values() if task.priority == "P0"]
        core_success = [task for task in core_tasks if task.task_id in evidenced_tasks]
        coverage = "blocked" if not core_success else ("partial" if checked.coverage_status != "complete" or len(core_success) < len(core_tasks) else "complete")
        confirmed, resolved = False, set()
        if approved_snapshot is not None:
            from app.domain.execution import ApprovedExecutionSnapshot
            approved = ApprovedExecutionSnapshot.model_validate(approved_snapshot.model_dump())
            plain = ParsedIntent.model_validate({key: getattr(intent, key) for key in ParsedIntent.model_fields})
            if (execution.source != "engine" or approved.status != "approved" or
                    approved.approval_id != execution.approval_id or approved.session_id != execution.session_id or
                    approved.validated_plan != validated or approved.intent != plain):
                raise AppError("REPORT_APPROVAL_MISMATCH", "报告输入与批准快照不一致。", 422)
            confirmed = approved.constraints_confirmed
            resolved = set(approved.resolved_uncertainty_ids)
        unresolved = [u for u in intent.uncertainties if u.id not in resolved]
        constraints = intent.constraints
        pending = ([constraints.time_range] if constraints.time_range else []) + constraints.filters + constraints.metric_requirements + constraints.analysis_limits
        if coverage == "complete" and ((pending and not confirmed) or any(u.action == "defer" for u in unresolved)):
            coverage = "partial"
        limitations = ["结论仅适用于上传样本与本次分析范围，不能直接代表整体市场或总体人群。",
            "业务解释和行动建议采用谨慎表述，未经过严格事实验证，也不构成因果结论。"]
        if execution.source == "imported":
            limitations.append("计算结果由上游导入；报告模块核对版本、结构与证据一致性，未复算源数据。")
        limitations.extend(issue.message[:2000] for issue in profile.quality_issues[:20])
        used_metrics = {metric.field for desc in descriptions.values() for metric in desc.metrics.values() if metric.field}
        limitations.extend(f'上传范围内，{field.display_name[:100]}有 {field.missing_count} 条缺失；这不是本任务筛选范围的有效样本量，指标有效记录以执行口径为准。'
            for field in profile.fields if field.field_id in used_metrics and field.missing_count)
        limitations.extend(f'未完成任务：{t.title[:300]}；{t.reason[:600]}' for t in uncompleted)
        limitations.extend(f"待解决事项：{u.description}"[:2000] for u in unresolved)
        limitations.extend(f"需求约束尚需对照执行口径确认：{item.raw_text}"[:2000] for item in pending if not confirmed)
        for t in execution.tasks:
            if t.result and t.result.truncated:
                limitations.append(f"{tasks[t.task_id].title[:200]}：仅返回部分结果，不能据此推断未返回分组的排名或总体占比。")
            if t.result and any(step.operation == "top_n" for step in tasks[t.task_id].steps):
                limitations.append(f"{tasks[t.task_id].title[:200]}：任务含 Top N 选择，不能仅凭返回表格确认所有分组均已覆盖。")
        charts = VisualizationBuilder().build(execution, descriptions, evidence, tasks, intent)
        charts.sort(key=lambda chart: (tasks[chart.task_id].priority, chart.chart_id))
        from app.review.presentation import PlanPresentationMapper
        mapper = PlanPresentationMapper(profile)
        llm, insights, rejected_insights = None, [], []
        if evidence:
            # Only bounded structured evidence, never all result rows / raw dataset.
            selected = select_evidence(evidence, tasks)
            payload = {"analysis_goal": intent.analysis_goal.model_dump(), "goal_coverage": coverage,
                "original_query": (original_query or intent.analysis_goal.business_goal or '')[:2000],
                "constraints": intent.constraints.model_dump(), "constraints_confirmed": confirmed,
                "scope_context": [{"task_id": t.task_id, "approved_steps": mapper.steps(t)} for t in tasks.values()],
                "fields": [{"field_id": f.field_id, "name": f.display_name, "logical_type": f.logical_type,
                            "upload_missing_count": f.missing_count} for f in profile.fields],
                "uncompleted_tasks": [t.model_dump() for t in uncompleted],
                "task_sample_context": [{"task_id": t.task_id, "status": t.status,
                    "valid_sample_count": t.valid_sample_count, "sample_definition": t.sample_definition,
                    "metric_valid_counts": t.execution_metadata.metric_valid_counts if t.execution_metadata else {}}
                    for t in execution.tasks],
                "tasks": [{"task_id": t.task_id, "priority": t.priority, "business_question": t.business_question}
                          for t in tasks.values() if t.task_id in evidenced_tasks],
                "evidence": [item.model_dump() for item in selected],
                "evidence_groups": [{"task_id": tid, "data_ref": ref, "result_field": field,
                    "evidence_ids": [e.evidence_id for e in selected if (e.task_id, e.data_ref, e.result_field) == (tid, ref, field)]}
                    for tid, ref, field in dict.fromkeys((e.task_id, e.data_ref, e.result_field) for e in selected)],
                "limitations": limitations}
            instruction = json.dumps(payload, ensure_ascii=False)
            if len(instruction.encode()) > 160 * 1024:
                raise AppError("REPORT_CONTEXT_TOO_LARGE", "证据上下文过大，未调用模型。", 422)
            request = LLMRequest(purpose="report_insights_v1", system_prompt=SYSTEM_PROMPT,
                instruction=instruction, response_schema=request_schema(selected), enable_thinking=self.enable_thinking)
            try:
                response = await asyncio.wait_for(self.provider.generate(request), timeout=self.timeout_seconds)
            except TimeoutError:
                raise AppError("LLM_TIMEOUT", "报告洞察生成超时，未用虚构内容替代。", 504) from None
            except AppError:
                raise
            except Exception:
                raise AppError("REPORT_LLM_CALL_FAILED", "报告洞察生成失败。", 502) from None
            try:
                if len(response.text.encode()) > 64 * 1024:
                    raise ValueError("Oversized response")
                draft = InsightDraft.model_validate(strict_json(response.text))
            except (ValidationError, ValueError, TypeError, AttributeError):
                raise AppError("REPORT_LLM_INVALID_OUTPUT", "洞察输出不符合结构契约。", 502) from None
            insights, rejected_insights = materialize_candidates(draft, selected, tasks,
                {t.result.result_id: t.result for t in execution.tasks if t.status == 'success'}, limitations)
            llm = LLMMetadata(provider=response.provider, model=response.model, is_mock=response.is_mock)
        status = "unavailable" if not evidence else ("partial" if uncompleted or rejected_insights or execution.execution_status == "partial_success" else "complete")
        if rejected_insights:
            limitations.append(f'有 {len(rejected_insights)} 条模型候选洞察未通过校验，未作为事实或建议输出；本报告为部分生成，拒绝原因保留在技术详情。')
        if not evidence:
            coverage = "blocked"
            limitations.append("没有有效计算证据，未调用模型生成总结。")
        headline = {"complete": "计划内核心任务已有可用结果", "partial": "已有部分发现，核心目标仍有待核实之处", "blocked": "现有结果尚不能回答核心问题"}[coverage]
        if status == "unavailable":
            headline = "暂无可生成报告的有效证据"
        elif coverage == 'complete' and len(core_tasks) == 1:
            headline = core_tasks[0].title
        overview = f"围绕「{(intent.analysis_goal.business_goal or '数据分析')[:500]}」，基于 {len(evidenced_tasks)} 个任务的可用结果整理。"
        names = {f.field_id: f.display_name for f in profile.fields}
        for executed in execution.tasks:
            if executed.status == 'success' and any(s.operation == 'top_n' for s in tasks[executed.task_id].steps):
                dimensions = descriptions[executed.task_id].dimensions
                name = names.get(dimensions[0], '分组') if len(dimensions) == 1 else '分组'
                overview += f' 该任务实际返回 {len(executed.result.rows)} 个{name}；Top N 选择不代表完整总体。'
        if uncompleted:
            overview += f"另有 {len(uncompleted)} 个任务未形成有效报告结果，详见局限性。"
        summary_refs = list(dict.fromkeys(ref for insight in insights[:3] for ref in insight.evidence_refs))
        metrics = []
        for item in evidence:
            if item.evidence_type == "metric":
                label = next(c.label for t in execution.tasks if t.result and t.result.result_id == item.data_ref for c in t.result.columns if c.field == item.result_field)
                metrics.append(KeyMetric(label=item.value.get("label", label), value=item.value["value"], unit=item.value["unit"], evidence_ref=item.evidence_id))
            elif item.evidence_type == "coverage" and not any(m.label == "上传数据记录数" for m in metrics):
                metrics.append(KeyMetric(label="上传数据记录数", value=item.value["dataset_rows"], unit="条", evidence_ref=item.evidence_id))
                metrics.append(KeyMetric(label="首个核心任务有效样本量" if tasks[item.task_id].priority == "P0" else "首个任务有效样本量",
                    value=item.value["valid_samples"], unit="条", evidence_ref=item.evidence_id))
            elif item.evidence_type == "maximum" and not any(m.label.startswith("返回结果最大值") for m in metrics):
                unit = next(c.unit for t in execution.tasks if t.result and t.result.result_id == item.data_ref for c in t.result.columns if c.field == item.result_field)
                metrics.append(KeyMetric(label="返回结果最大值（" + ("缺失分组" if item.value["category"] is None else str(item.value["category"]))[:40] + "）", value=item.value["value"], unit=unit, evidence_ref=item.evidence_id))
            elif item.evidence_type == "proportion" and not any(m.label.startswith("同口径总体占比") for m in metrics):
                metrics.append(KeyMetric(label="同口径总体占比（" + ("缺失分组" if item.value["category"] is None else str(item.value["category"]))[:40] + "）", value=item.value["percent"], unit="%", evidence_ref=item.evidence_id))
        totals = [m for m in metrics if m.label.startswith("本次返回")]
        metrics = totals + [m for m in metrics if m not in totals]
        comparison_metrics = []
        leaders = []
        for item in evidence:
            if item.evidence_type != 'ranking' or item.value['rank'] != 1 or tasks[item.task_id].priority != 'P0':
                continue
            desc = descriptions[item.task_id]
            metric = desc.metrics[item.result_field]
            names = {f.field_id: f.display_name for f in profile.fields}
            measure = ('记录数量' if metric.field is None else names.get(metric.field, '指标'))
            if metric.function == 'count' and metric.field:
                measure += '非空记录数'
            maxima = [e for e in evidence if e.task_id == item.task_id and e.result_field == item.result_field and e.evidence_type == 'maximum']
            if maxima and maxima[0].value['tie_count'] == 1:
                leaders.append(KeyMetric(label='第一名' + measure, value=item.value['value'], unit=None, evidence_ref=item.evidence_id))
        for item in evidence:
            kind = item.value.get('comparison_kind')
            if tasks[item.task_id].priority != 'P0' or kind not in {'relative_lead', 'returned_concentration'}:
                continue
            label = (f"{item.value['left']}相对{item.value['right']}领先幅度" if kind == 'relative_lead'
                     else '前两个返回分组占返回合计')
            comparison_metrics.append(KeyMetric(label=label, value=item.value['percent'], unit='%', evidence_ref=item.evidence_id))
        metrics = leaders[:1] + comparison_metrics[:2] + metrics
        if insights:
            # Summary facts are copied from validated evidence, never free LLM statistics.
            overview += " " + " ".join(i.finding for i in insights[:2])[:1200]
        metadata = {t.task_id: {**t.model_dump(exclude={"result"}),
            "insight_generation_version": GENERATION_VERSION,
            "rejected_insights": rejected_insights,
            "approved_scope": mapper.steps(tasks[t.task_id]),
            "original_query": original_query if approved_snapshot is not None else None}
            for t in execution.tasks}
        report_id = "report_" + uuid4().hex
        return AnalysisReport(report_id=report_id, execution_id=execution.execution_id, plan_version=execution.plan_version,
            dataset_id=profile.dataset_id, dataset_version=profile.dataset_version, dataset_name=profile.file_name,
            dataset_row_count=profile.row_count, analysis_goal=intent.analysis_goal.business_goal or "数据分析",
            execution_source=execution.source, report_status=status, goal_coverage=coverage,
            summary=Summary(headline=headline, overview=overview, evidence_refs=summary_refs),
            key_metrics=metrics[:6], insights=insights, charts=charts,
            recommendations=[Recommendation(text=i.recommendation, evidence_refs=i.evidence_refs) for i in insights],
            limitations=list(dict.fromkeys(limitations)), uncompleted_tasks=uncompleted, evidence=evidence,
            result_data={t.result.result_id: t.result for t in execution.tasks if t.status == "success"},
            execution_metadata=metadata,
            task_metadata=tasks, fact_validation="structured_facts_verified_interpretations_unverified", llm=llm,
            provenance=Provenance(source="mock" if llm and llm.is_mock else ("llm" if llm else "uploaded"),
                dataset=profile.dataset_id, dataset_version=profile.dataset_version, plan_version=execution.plan_version,
                notice="事实来自执行结果和确定性证据；解释性陈述未严格验证。"),
            preview_url=f"/reports/{report_id}", download_url=f"/api/v1/reports/{report_id}/download", generated_at=now())
