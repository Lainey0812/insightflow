import asyncio
import json
import logging
from contextlib import nullcontext
from app.observability.context import current_trace
from app.observability.recorder import feasibility_counts
from uuid import uuid4

from pydantic import ValidationError

from app.domain.analysis_plan import AnalysisPlan, ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.domain.intent import IntentArtifact, LLMMetadata, ParsedIntent
from app.domain.provenance import Provenance
from app.llm.base import LLMProvider, LLMRequest, llm_observation
from app.planning.capabilities import CapabilityRegistry
from app.planning.context import planner_context
from app.planning.output import request_schema, validate_draft
from app.planning.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from app.planning.validator import PlanValidator
from app.llm.templates import pin_template
from app.llm.capture import CAPTURE_CODES

logger = logging.getLogger('app.planner')
PLANNER_RETRY_INSTRUCTION = '同一输入重新输出完整JSON；严格遵守参数Schema，不增加分析目标。'
RETRYABLE = {'PLANNER_INVALID_JSON', 'PLANNER_SCHEMA_INVALID', 'PLANNER_OUTPUT_TOO_LARGE',
             'LLM_INVALID_OUTPUT', 'LLM_INCOMPLETE_OUTPUT'}
PROVIDER_CODES = {'LLM_NOT_CONFIGURED', 'LLM_TIMEOUT', 'LLM_UNAVAILABLE', 'LLM_HTTP_ERROR',
                  'LLM_RATE_LIMITED', 'LLM_REFUSED', 'LLM_INCOMPLETE_OUTPUT', 'LLM_INVALID_OUTPUT',
                  'LLM_SCHEMA_REQUIRED'}
PROVIDER_CODES |= CAPTURE_CODES


class AnalysisPlannerService:
    def __init__(self, provider: LLMProvider, registry: CapabilityRegistry, timeout_seconds: float = 30,
                 *, max_attempts: int = 2, enable_thinking: bool | None = None):
        if not 0 < timeout_seconds <= 300:
            raise ValueError('Planner timeout must be within (0, 300]')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError('Planner max_attempts must be in [1, 3]')
        if enable_thinking is not None and type(enable_thinking) is not bool:
            raise ValueError('Planner enable_thinking must be boolean or None')
        self.provider, self.registry, self.timeout_seconds = provider, registry, timeout_seconds
        self.max_attempts, self.enable_thinking = max_attempts, enable_thinking
        self.validator = PlanValidator(registry)
        self.prompt_source = pin_template(provider,'analysis_planner',self,PROMPT_VERSION,SYSTEM_PROMPT)

    async def plan(self, intent: ParsedIntent, profile: DatasetProfile) -> ValidatedAnalysisPlan:
        try:
            clean_intent = ParsedIntent.model_validate({key: getattr(intent, key) for key in ParsedIntent.model_fields})
        except (ValidationError, AttributeError, ValueError):
            raise AppError('PLANNER_INTENT_INVALID', '分析意图结构或流程规则无效。', 422) from None
        if clean_intent.next_action != 'proceed':
            raise AppError('INTENT_CLARIFICATION_REQUIRED', '意图仍需澄清，不能生成分析计划。', 409)
        if isinstance(intent, IntentArtifact) and (intent.dataset_ref.dataset_id, intent.dataset_ref.dataset_version) != (profile.dataset_id, profile.dataset_version):
            raise AppError('INTENT_DATASET_MISMATCH', '意图与画像的数据集版本不一致。', 409)
        context, requirements = planner_context(clean_intent, profile, self.registry)
        parse_id, attempts, failure = uuid4().hex, 0, None
        trace = current_trace()
        if trace and trace.active:
            trace.active.attributes(operation_id=parse_id)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                for attempts in range(1, self.max_attempts + 1):
                    data = dict(context)
                    if failure:
                        data['validation_feedback'] = {'code': failure.error.code,
                            'instruction': PLANNER_RETRY_INSTRUCTION}
                    instruction = json.dumps(data, ensure_ascii=False)
                    if len(instruction.encode('utf-8')) > 132 * 1024:
                        raise AppError('PLANNER_CONTEXT_TOO_LARGE', '规划请求过大。', 422, details={'stage': 'input'})
                    request = LLMRequest(purpose='analysis_planner_v1', system_prompt=SYSTEM_PROMPT,
                        instruction=instruction, response_schema=request_schema(self.registry),
                        enable_thinking=self.enable_thinking,
                        call_binding=self.prompt_source.binding(parse_id,attempts,trace=trace,retry_reason=failure.error.code if failure else None) if self.prompt_source else None)
                    try:
                        try:
                            response = await self.provider.generate(request)
                            if trace and trace.active:
                                trace.active.attributes(**llm_observation(response))
                        except AppError as exc:
                            code = exc.error.code if exc.error.code in PROVIDER_CODES else 'PLANNER_LLM_CALL_FAILED'
                            status = exc.status if code in PROVIDER_CODES else 502
                            raised = AppError(code, '规划模型调用未成功，未生成计划。', status,
                                           details={'stage': 'call'})
                            observed = getattr(exc, 'observation', None)
                            if isinstance(observed, dict):
                                raised.observation = observed
                            raise raised from None
                        except TimeoutError:
                            raise AppError('LLM_TIMEOUT', '规划模型调用超时。', 504, details={'stage': 'call'}) from None
                        except Exception:
                            raise AppError('PLANNER_LLM_CALL_FAILED', '规划模型调用失败。', 502, details={'stage': 'call'}) from None
                        draft = validate_draft(response.text, self.registry)
                    except AppError as exc:
                        exc.error.details.update(attempts=attempts, parse_id=parse_id, prompt_version=PROMPT_VERSION)
                        logger.info('Planner attempt failed', extra={'parse_id': parse_id, 'attempt': attempts,
                            'error_code': exc.error.code, 'prompt_version': PROMPT_VERSION})
                        if exc.error.code not in RETRYABLE or attempts == self.max_attempts:
                            raise
                        failure = exc
                        continue
                    break
        except TimeoutError:
            raise AppError('LLM_TIMEOUT', '规划调用超过总时间限制。', 504,
                           details={'stage': 'call', 'attempts': attempts, 'parse_id': parse_id,
                                    'prompt_version': PROMPT_VERSION}) from None
        plan = AnalysisPlan(plan_id='plan_' + uuid4().hex, dataset_id=profile.dataset_id,
            dataset_version=profile.dataset_version, plan_version=1, tasks=draft.tasks,
            core_requirements=requirements)
        # Exactly one deterministic validation. No LLM repair of F0 or deleting tasks.
        with trace.span('plan_validator', {'validation_role':'planner_output'}) if trace else nullcontext() as validation_span:
            validated = self.validator.validate(plan, profile)
            if trace:
                validation_span.attributes(coverage_status=validated.coverage_status,
                    executable_count=len(validated.executable_task_ids), blocked_count=len(validated.blocked_task_ids),
                    plan_id=plan.plan_id, plan_version=plan.plan_version,
                    **feasibility_counts(validated))
        logger.info('Planner validated', extra={'parse_id': parse_id, 'attempts': attempts,
            'prompt_version': PROMPT_VERSION, 'coverage_status': validated.coverage_status})
        return validated.model_copy(update={
            'intent_snapshot': clean_intent,
            'llm': LLMMetadata(provider=response.provider, model=response.model, is_mock=response.is_mock),
            'provenance': Provenance(source='mock' if response.is_mock else 'llm', dataset=profile.dataset_id,
                dataset_version=profile.dataset_version, plan_version=1,
                notice=f'Prompt={PROMPT_VERSION}; attempts={attempts}; 模型草案经技术校验，不代表业务约束已核实或用户批准，未执行统计。')})
