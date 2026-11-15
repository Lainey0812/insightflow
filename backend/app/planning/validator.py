"""Deterministic validation only; never calls a model or executes a dataset."""
import json
from pydantic import ValidationError

from app.domain.analysis_plan import (AnalysisPlan, UnmetCoreRequirement, ValidatedAnalysisPlan,
                                      ValidationIssue, ValidationResult)
from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.domain.provenance import Provenance
from .capabilities import CapabilityError, CapabilityRegistry, FieldState
from .params import AggregateParams, DeriveParams, FilterParams, GroupParams, SortParams


class PlanValidator:
    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def validate(self, plan: AnalysisPlan | dict, profile: DatasetProfile) -> ValidatedAnalysisPlan:
        try:
            # Reparse instances too: model_copy/construct must not bypass schema validation.
            json.dumps(plan.model_dump(mode="json") if isinstance(plan, AnalysisPlan) else plan, allow_nan=False)
            plan = AnalysisPlan.model_validate(plan.model_dump() if isinstance(plan, AnalysisPlan) else plan)
        except (ValidationError, ValueError, TypeError):
            raise AppError("PLAN_SCHEMA_INVALID", "计划结构、枚举或唯一 ID 不符合要求。", 422) from None
        results = [self._task(task, plan, profile) for task in plan.tasks]
        by_id = {result.task_id: result for result in results}
        unmet = []
        any_core_answer = False
        for requirement in plan.core_requirements:
            known = {r.requirement_id for r in plan.core_requirements}
            core_tasks = [t for t in plan.tasks if t.priority == "P0" and (
                requirement.requirement_id in t.requirement_ids or not t.requirement_ids or not set(t.requirement_ids) <= known)]
            blocked = [t for t in core_tasks if not by_id[t.task_id].executable]
            any_core_answer |= any(by_id[t.task_id].executable for t in core_tasks)
            if blocked or not core_tasks:
                unmet.append(UnmetCoreRequirement(requirement_id=requirement.requirement_id,
                    description=requirement.description, task_ids=[t.task_id for t in blocked],
                    reason_codes=list(dict.fromkeys(by_id[t.task_id].reason_code for t in blocked)) or ["CORE_NOT_COVERED"]))
        executable = [r.task_id for r in results if r.executable]
        blocked = [r.task_id for r in results if not r.executable]
        coverage = "blocked" if not any_core_answer else ("partial" if unmet else "complete")
        return ValidatedAnalysisPlan(plan=plan, validation_results=results, unmet_core_requirements=unmet,
            coverage_status=coverage, executable_task_ids=executable, blocked_task_ids=blocked,
            fully_executable=coverage == "complete" and not blocked, registry_version=self.registry.version,
            provenance=Provenance(source="uploaded", dataset=profile.dataset_id,
                dataset_version=profile.dataset_version, plan_version=plan.plan_version,
                notice="依据真实画像确定性校验；未执行统计，仍需用户审批。"))

    def _task(self, task, plan, profile):
        def fail(code, message, step=None, field=None):
            return ValidationResult(task_id=task.task_id, feasibility="F0", reason_code=code,
                executable=False, validation_issues=[ValidationIssue(code=code, message=message, step_id=step, field=field)])
        if (plan.dataset_id, plan.dataset_version) != (profile.dataset_id, profile.dataset_version):
            return fail("DATASET_VERSION_MISMATCH", "计划与画像的数据集版本不一致。")
        if task.depends_on:
            return fail("UNSUPPORTED_DEPENDENCY", "MVP 不支持跨任务依赖；每个任务必须从原始数据独立执行。")
        requirements = {r.requirement_id for r in plan.core_requirements}
        if not set(task.requirement_ids) <= requirements or (task.priority == "P0" and not task.requirement_ids):
            return fail("UNKNOWN_REQUIREMENT", "P0 必须关联已知核心需求，不能虚构需求 ID。")
        if task.missing_inputs:
            return fail("MISSING_FIELD", "任务明确缺少必要输入：" + "；".join(task.missing_inputs)[:1700])
        fields = {f.field_id: FieldState(f.logical_type, f.non_missing_count) for f in profile.fields}
        original = set(fields)
        reserved = set(fields)
        rowset_transformed = False
        future_aliases = set()
        for step in task.steps:
            metrics = step.params.get("metrics", [])
            if isinstance(metrics, list):
                future_aliases.update(m["alias"] for m in metrics if isinstance(m, dict) and isinstance(m.get("alias"), str))
            if isinstance(step.params.get("alias"), str):
                future_aliases.add(step.params["alias"])
        for step in task.steps:
            spec = self.registry.operations.get(step.operation)
            if spec is None:
                return fail("UNSUPPORTED_OPERATION", "当前系统未实现该操作。", step.step_id)
            try:
                params = spec.params_model.model_validate(step.params)
            except ValidationError:
                return fail("INVALID_SCHEMA", "操作参数不符合能力目录的参数 Schema。", step.step_id)
            if isinstance(params, DeriveParams) and params.function not in {"extract_year", "extract_month"}:
                return fail("UNSUPPORTED_OPERATION", "当前系统未实现该派生函数。", step.step_id, params.field)
            refs = []
            if isinstance(params, FilterParams):
                refs = [c.field for c in params.conditions]
            elif isinstance(params, AggregateParams):
                refs = [m.field for m in params.metrics if m.field is not None]
                if isinstance(params, GroupParams):
                    refs += params.dimensions
            elif isinstance(params, (SortParams, DeriveParams)):
                refs = [params.field]
            for ref in refs:
                if ref not in fields:
                    if ref in future_aliases and ref not in reserved:
                        code, message = "INVALID_OPERATION_ORDER", "引用了尚未生成的中间别名。"
                    elif ref in original or ref in reserved:
                        code, message = "INVALID_FIELD_REFERENCE", "字段已被先前聚合移除，不能重新访问原始数据。"
                    else:
                        code, message = "MISSING_FIELD", "画像和先前步骤均不存在该字段。"
                    return fail(code, message, step.step_id, ref)
            try:
                # A derived filter/top_n changes row membership even if a later
                # aggregate drops the derived column or counts rows without a field.
                if step.operation in {"filter", "top_n"}:
                    rowset_transformed |= any(fields[ref].requires_transformation for ref in refs)
                fields = self.registry.propagate(step.operation, params, fields, reserved)
            except CapabilityError as exc:
                return fail(exc.code, exc.message, step.step_id, exc.field)
            reserved.update(fields)
        transformed = rowset_transformed or any(state.requires_transformation for state in fields.values())
        return ValidationResult(task_id=task.task_id, feasibility="F1" if transformed else "F2",
            reason_code="REQUIRES_TRANSFORMATION" if transformed else "READY", executable=True, validation_issues=[])
