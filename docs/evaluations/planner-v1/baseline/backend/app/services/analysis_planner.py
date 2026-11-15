import asyncio
import json
from uuid import uuid4

from pydantic import ValidationError

from app.domain.analysis_plan import AnalysisPlan, CoreRequirement, PlannerDraft, ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.domain.intent import IntentArtifact, LLMMetadata, ParsedIntent
from app.domain.provenance import Provenance
from app.intent.context import build_dataset_context
from app.llm.base import LLMProvider, LLMRequest
from app.planning.capabilities import CapabilityRegistry
from app.planning.prompt import SYSTEM_PROMPT
from app.planning.validator import PlanValidator
from app.services.intent_parser import strict_json


class AnalysisPlannerService:
    def __init__(self, provider: LLMProvider, registry: CapabilityRegistry, timeout_seconds: float = 30):
        if not 0 < timeout_seconds <= 300:
            raise ValueError("Planner timeout must be within (0, 300]")
        self.provider, self.registry, self.timeout_seconds = provider, registry, timeout_seconds
        self.validator = PlanValidator(registry)

    async def plan(self, intent: ParsedIntent, profile: DatasetProfile) -> ValidatedAnalysisPlan:
        build_dataset_context(profile)  # Enforce real profile and bounded field metadata.
        # Revalidate even programmatically constructed Intent instances.
        try:
            clean_intent = ParsedIntent.model_validate({key: getattr(intent, key) for key in ParsedIntent.model_fields})
        except (ValidationError, AttributeError, ValueError):
            raise AppError("PLANNER_INTENT_INVALID", "分析意图结构或流程规则无效。", 422) from None
        if clean_intent.next_action != "proceed":
            raise AppError("INTENT_CLARIFICATION_REQUIRED", "意图仍需澄清，不能生成分析计划。", 409)
        if isinstance(intent, IntentArtifact) and (intent.dataset_ref.dataset_id, intent.dataset_ref.dataset_version) != (profile.dataset_id, profile.dataset_version):
            raise AppError("INTENT_DATASET_MISMATCH", "意图与画像的数据集版本不一致。", 409)
        goal = clean_intent.analysis_goal
        requirements = [CoreRequirement(requirement_id="C01", description=goal.business_goal)]
        if goal.decision_goal is not None:
            requirements.append(CoreRequirement(requirement_id="C02", description=goal.decision_goal))
        context = {"intent": clean_intent.model_dump(mode="json"),
            "core_requirements": [r.model_dump() for r in requirements],
            "profile": {"dataset_id": profile.dataset_id, "dataset_version": profile.dataset_version,
                "file_name": profile.file_name, "row_count": profile.row_count,
                "fields": [{"field_id": f.field_id, "name": f.display_name,
                    "logical_type": f.logical_type.value, "physical_type": f.physical_type.value,
                    "non_missing_count": f.non_missing_count, "missing_rate": f.missing_rate,
                    "unique_count": f.unique_count} for f in profile.fields],
                "quality_issues": [{"code": i.code, "field_ids": i.field_ids} for i in profile.quality_issues]},
            "capabilities": self.registry.summary()}
        instruction = json.dumps(context, ensure_ascii=False)
        if len(instruction.encode("utf-8")) > 128 * 1024:
            raise AppError("PLANNER_CONTEXT_TOO_LARGE", "规划上下文过大，未调用模型。", 422)
        response = None
        for attempt in range(2):
            request = LLMRequest(purpose="analysis_planner_v1", system_prompt=SYSTEM_PROMPT,
                instruction=instruction + ("\n上次输出不符合结构或参数契约。请按同一输入及 Schema 重新生成，不输出解释。" if attempt else ""),
                response_schema=self.registry.request_schema())
            try:
                response = await asyncio.wait_for(self.provider.generate(request), timeout=self.timeout_seconds)
            except TimeoutError:
                raise AppError("LLM_TIMEOUT", "规划模型调用超时，未生成可执行计划。", 504) from None
            except AppError as exc:
                # Only malformed/incomplete output is retryable; no transport/auth retries.
                if attempt == 0 and exc.error.code in {"LLM_INVALID_OUTPUT", "LLM_INCOMPLETE_OUTPUT"}:
                    continue
                raise
            except Exception:
                raise AppError("PLANNER_LLM_CALL_FAILED", "规划模型调用失败，未生成计划。", 502) from None
            try:
                if len(response.text.encode("utf-8")) > 128 * 1024:
                    raise ValueError("Output too large")
                draft = PlannerDraft.model_validate(strict_json(response.text))
                for task in draft.tasks:
                    for step in task.steps:
                        spec = self.registry.operations.get(step.operation)
                        if spec is None:
                            raise ValueError("Undeclared operation")
                        spec.params_model.model_validate(step.params)
                break
            except (ValidationError, ValueError, TypeError, AttributeError):
                if attempt == 1:
                    raise AppError("PLANNER_INVALID_OUTPUT", "规划模型输出不符合 Schema，两次尝试均未通过。", 502) from None
        else:
            raise AppError("PLANNER_INVALID_OUTPUT", "规划模型未生成合法草案。", 502)
        plan = AnalysisPlan(plan_id="plan_" + uuid4().hex, dataset_id=profile.dataset_id,
            dataset_version=profile.dataset_version, plan_version=1, tasks=draft.tasks,
            core_requirements=requirements)
        validated = self.validator.validate(plan, profile)
        return validated.model_copy(update={
            "intent_snapshot": clean_intent,
            "llm": LLMMetadata(provider=response.provider, model=response.model, is_mock=response.is_mock),
            "provenance": Provenance(source="mock" if response.is_mock else "llm", dataset=profile.dataset_id,
                dataset_version=profile.dataset_version, plan_version=1,
                notice="模型任务草案已通过代码校验；可执行性不代表用户批准，未执行统计。")})
