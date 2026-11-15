"""User-confirmed finite text scopes compiled to existing exact membership filters."""
import hashlib
import json
import unicodedata
from typing import Literal
from pydantic import Field, StrictStr
from app.domain.analysis_plan import PlanModel
from app.domain.errors import AppError

PREFIX = '[confirmed-text-scope-v1]'


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if not c.isspace())


class ScopeRequest(PlanModel):
    expected_revision: int = Field(ge=0, strict=True)
    plan_id: str
    plan_version: int = Field(ge=1, strict=True)
    field_id: str
    filter_index: int = Field(ge=0, strict=True)
    keyword: StrictStr = Field(min_length=1, max_length=120)
    mode: Literal['exact', 'normalized_contains']


class ScopeConfirmation(ScopeRequest):
    preview_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class ConfirmedScope(PlanModel):
    field_id: StrictStr
    keyword: StrictStr = Field(min_length=1, max_length=120)
    mode: Literal['exact', 'normalized_contains']
    values: list[StrictStr] = Field(min_length=1, max_length=100)


def encode(scope):
    value = PREFIX + json.dumps(scope.model_dump(), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if len(value) > 2000:
        raise AppError('SCOPE_ENUMERATION_TOO_LARGE', '匹配名称过多或过长，无法完整登记；未截断条件，请缩小关键词范围。', 422)
    return value


def decode(text, profile):
    if not text.startswith(PREFIX):
        return None
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result: raise ValueError('Duplicate key')
            result[k] = v
        return result
    try:
        scope = ConfirmedScope.model_validate(json.loads(text[len(PREFIX):], object_pairs_hook=unique))
        field = next((f for f in profile.fields if f.field_id == scope.field_id), None)
        if (not field or field.logical_type != 'text' or not normalize(scope.keyword)
                or len(scope.values) != len(set(scope.values))):
            return None
        if not all((value == scope.keyword if scope.mode == 'exact' else normalize(scope.keyword) in normalize(value)) for value in scope.values):
            return None
        return scope
    except (ValueError, TypeError):
        return None


def summary(scope, profile):
    field = next(f for f in profile.fields if f.field_id == scope.field_id)
    rule = '名称包含' if scope.mode == 'normalized_contains' else '名称完全等于'
    detail = '，忽略英文大小写及空白' if scope.mode == 'normalized_contains' else ''
    return f'{field.display_name}：{rule}“{scope.keyword}”{detail}；按已核对的 {len(scope.values)} 种完整名称筛选'


def _related(value, keyword):
    token = normalize(value) if isinstance(value, str) else ''
    key = normalize(keyword)
    return bool(token and key and (value == keyword or key in token or token in key))


def guessed_scope(condition, keyword):
    """A model membership guess for this keyword, including extra names it added."""
    operator, value = condition.get('operator'), condition.get('value')
    if operator == 'eq':
        return _related(value, keyword)
    return bool(operator == 'in' and isinstance(value, list) and value
        and all(isinstance(item, str) and item for item in value) and any(_related(item, keyword) for item in value))


def check_target(record, request):
    intent = record.validated_plan.intent_snapshot
    if (intent is None or request.filter_index >= len(intent.constraints.filters)
            or intent.constraints.filters[request.filter_index].raw_text != request.keyword):
        raise AppError('SCOPE_SOURCE_MISMATCH', '只能确认当前需求中对应的原始筛选词，不能替换其他约束。', 409)
    matched = []
    for task in record.validated_plan.plan.tasks:
        aggregations = [i for i, s in enumerate(task.steps) if s.operation in {'aggregate', 'group_aggregate'}]
        if len(aggregations) != 1:
            raise AppError('SCOPE_TARGET_CONFLICT', '该字段还有其他限制或顺序不明确，不能自动替换；请重新明确需求。', 409)
        candidates = []
        for i, step in enumerate(task.steps):
            if step.operation != 'filter': continue
            for index, condition in enumerate(step.params.get('conditions', [])):
                if condition.get('field') != request.field_id: continue
                if i >= aggregations[0] or not guessed_scope(condition, request.keyword):
                    raise AppError('SCOPE_TARGET_CONFLICT', '该字段还有其他限制或顺序不明确，不能自动替换；请重新明确需求。', 409)
                candidates.append((task.task_id, step.step_id, index))
        if len(candidates) != 1:
            raise AppError('SCOPE_TARGET_CONFLICT', '各分析方向未使用同一个明确筛选字段，不能静默补齐或选择。', 409)
        matched += candidates
    if not matched:
        raise AppError('SCOPE_TARGET_CONFLICT', '当前没有可以确认的筛选步骤。', 409)
    return matched


def scope_questions(record, profile, items):
    """Questions the user can answer on the review page. Unrelated filters stay closed."""
    intent = record.validated_plan.intent_snapshot
    if intent is None:
        return []
    questions = []
    for index, constraint in enumerate(intent.constraints.filters):
        source = f'intent.constraints.filters[{index}]'
        if not any(item.source == source and item.status in {'unmapped', 'mismatch'} for item in items):
            continue
        keyword = constraint.raw_text
        found, usable = [], True
        for task in record.validated_plan.plan.tasks:
            aggregations = [i for i, step in enumerate(task.steps) if step.operation in {'aggregate', 'group_aggregate'}]
            if len(aggregations) != 1:
                usable = False
                break
            hits = []
            for position, step in enumerate(task.steps):
                if step.operation != 'filter' or position >= aggregations[0]:
                    continue
                hits += [condition.get('field') for condition in step.params.get('conditions', []) if guessed_scope(condition, keyword)]
            if len(hits) != 1:
                usable = False
                break
            found.append(hits[0])
        if not usable or len(set(found)) != 1:
            continue
        field = next((item for item in profile.fields if item.field_id == found[0] and item.logical_type == 'text'), None)
        if field is None:
            continue
        from types import SimpleNamespace
        try:
            check_target(record, SimpleNamespace(filter_index=index, keyword=keyword, field_id=field.field_id))
        except AppError:
            continue
        questions.append({'filter_index': index, 'keyword': keyword, 'field_id': field.field_id, 'field_name': field.display_name})
    return questions


def preview(record, request, datasets, files):
    from app.execution.loader import DatasetLoader
    check_target(record, request)
    if files is None:
        raise AppError('SCOPE_PREVIEW_UNAVAILABLE', '当前服务没有配置原文件读取，无法核对范围。', 503)
    loaded = DatasetLoader(datasets, files).load(record.dataset_id, record.dataset_version)
    field = next((f for f in loaded.profile.fields if f.field_id == request.field_id), None)
    if not field or field.logical_type != 'text' or not normalize(request.keyword):
        raise AppError('SCOPE_FIELD_INVALID', '范围确认仅支持明确的文本字段与非空关键词。', 422)
    cells = loaded.frame[request.field_id].tolist()
    matches = [v for v in cells if isinstance(v, str) and (v == request.keyword if request.mode == 'exact' else normalize(request.keyword) in normalize(v))]
    values = list(dict.fromkeys(matches))
    if not values:
        raise AppError('SCOPE_NO_MATCHES', '当前数据版本中没有匹配名称；未生成空范围方案。', 422)
    if len(values) > 100:
        raise AppError('SCOPE_ENUMERATION_TOO_LARGE', '匹配的完整名称超过100种，请缩小关键词；不会截断范围。', 422)
    scope = ConfirmedScope(field_id=request.field_id, keyword=request.keyword, mode=request.mode, values=values)
    canonical = encode(scope)
    digest = hashlib.sha256(json.dumps({'plan': record.model_dump(mode='json'), 'scope': canonical,
        'filter_index':request.filter_index,'revision':request.expected_revision},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {'scope':scope.model_dump(),'matched_row_count':len(matches),'dataset_row_count':len(cells),
            'summary':summary(scope,loaded.profile),'preview_digest':digest,'dataset_id':record.dataset_id,
            'dataset_version':record.dataset_version}
