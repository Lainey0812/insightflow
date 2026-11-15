"""Fail-closed finite grammar proofs, NOT general natural-language validation.

Only full supported expressions map. Samples can disambiguate exact categorical
values, never establish synonyms or field semantics. Every approved condition
has an actual operation reference. Intent text is never mutated.
"""
import hashlib
import json
import re
from dataclasses import dataclass

from app.domain.review_presentation import ConstraintAudit, ConstraintProof
from .bindings import record_count, observed_binding, goal_dimensions
from . import output_boundaries
from .confirmed_scope import PREFIX, decode

FUNCTIONS = {'sum': '合计', 'avg': '均值', 'median': '中位数', 'min': '最小值',
             'max': '最大值', 'count': '非空数量', 'distinct_count': '去重数量'}
AGG_WORDS = {'总和': 'sum', '合计': 'sum', '总额': 'sum', '总计': 'sum', '求和': 'sum',
             '平均值': 'avg', '均值': 'avg', '平均': 'avg', '中位数': 'median',
             '最大值': 'max', '最小值': 'min', '去重数量': 'distinct_count', '去重数': 'distinct_count'}
NUMBERS = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6,
           '七': 7, '八': 8, '九': 9, '十': 10}


@dataclass
class Clause:
    kind: str
    field: str | None = None
    function: str | None = None
    value: object = None
    direction: str | None = None


class ConstraintAuditor:
    def __init__(self, profile):
        self.profile = profile
        self.fields = {f.field_id: f for f in profile.fields}
        self.entity_context = ""

    def named_fields(self, text):
        return [f for f in self.profile.fields if text in {f.display_name, f.original_name}]

    def metric(self, text):
        # Exact field names win, including names containing “平均” or “数量”.
        candidates = []
        for f in self.profile.fields:
            name = '(?:' + '|'.join(re.escape(n) for n in {f.display_name, f.original_name} if n) + ')'
            if re.fullmatch(r'(?:统计|计算|分析|比较)?' + name, text):
                candidates.append(Clause('metric', f.field_id))
            for word, fn in AGG_WORDS.items():
                if re.fullmatch(r'(?:统计|计算|分析|比较)?(?:' + name + r'(?:的)?' + word + '|' + word + name + ')', text):
                    candidates.append(Clause('metric', f.field_id, fn))
        if text in {'记录数', '记录数量', '记录总数', '行数', '总记录数'}:
            candidates.append(Clause('metric', function='count'))
        if record_count(text, self.profile, self.entity_context):
            candidates.append(Clause('metric', function='count'))
        # No guessing quantity sum vs order count, salary parsing, or denominators.
        unique = {(c.field, c.function): c for c in candidates}
        return next(iter(unique.values())) if len(unique) == 1 else None

    def parse(self, text, category):
        if text.startswith(PREFIX):
            confirmed = decode(text, self.profile) if category == 'filters' else None
            return [Clause('filter', confirmed.field_id, value={'operator':'in','value':confirmed.values})] if confirmed else None
        s = re.sub(r'\s+', '', text).strip('。；;，,')
        restriction = output_boundaries.boundary(s) if category == 'analysis_limits' else None
        if restriction:
            return [Clause('output_boundary', value=restriction)]
        # Negation is recognized as a whole expression, not a substring keyword.
        forbidden = re.fullmatch(r'(?:(?:不要|禁止|不允许)(?:分析|计算|统计)?|不分析|不计算|不统计)(.+)', s)
        if forbidden:
            metric = self.metric(forbidden[1])
            return [Clause('prohibited', metric.field)] if metric and metric.field else None
        if s.startswith('不排除'):
            bound = observed_binding(s[len('不排除'):], self.profile)
            return [Clause('no_exclusion', bound[0], value=bound[1])] if bound else None
        if re.search(r'不要求|未指定|可选|不必|不需要', s):
            return None  # Do not convert optional/unspecified to required/prohibited.
        year = re.fullmatch(r'(?:(.+?)(?:为|在|是|属于)?)?((?:19|20)\d{2})年(?:全年)?', s)
        if year and category == 'time_range':
            fields = self.named_fields(year[1]) if year[1] else [f for f in self.profile.fields if f.logical_type in {'date', 'datetime'}]
            return [Clause('year', fields[0].field_id, value=int(year[2]))] if len(fields) == 1 else None
        dimension = re.fullmatch(r'(?:按照|按)(.+?)(?:分组|汇总|统计|比较|分析|计算)', s)
        if dimension:
            fields = self.named_fields(dimension[1])
            if len(fields) == 1:
                return [Clause('dimension', fields[0].field_id)]
        # An explicit “按城市汇总销售额” has two independently proved components.
        grouped = re.fullmatch(r'(?:按照|按)(.+?)(?:汇总|统计|计算)(.+)', s)
        if grouped:
            fields, metric = self.named_fields(grouped[1]), self.metric(grouped[2])
            if len(fields) == 1 and metric:
                return [Clause('dimension', fields[0].field_id), metric]
        ordered = re.fullmatch(r'(?:(?:按照|按)(.+?))?(降序|升序)(?:排列|排序|排名)?', s)
        if ordered:
            if ordered[1] in {'月份', '年份'}:
                fields = [f for f in self.profile.fields if f.logical_type in {'date', 'datetime'}]
                return [Clause('temporal_sort', fields[0].field_id,
                    function='extract_month' if ordered[1] == '月份' else 'extract_year',
                    direction='desc' if ordered[2] == '降序' else 'asc')] if len(fields) == 1 else None
            basis = Clause('metric', function='count') if ordered[1] == '数量' and not self.named_fields('数量') else self.metric(ordered[1]) if ordered[1] else None
            if basis is None and ordered[1] in AGG_WORDS and not self.named_fields(ordered[1]):
                basis = Clause('metric', function=AGG_WORDS[ordered[1]])
            if ordered[1] and basis is None:
                return None
            return [Clause('sort', basis.field if basis else None, basis.function if basis else None,
                           direction='desc' if ordered[2] == '降序' else 'asc')]
        ranked_top = re.fullmatch(r'(升序|降序)(?:排列|排序|排名)?((?:取|保留|选取)?前(?:[0-9]+|[一二两三四五六七八九十])(?:名|个|项|条)?)', s)
        if ranked_top:
            limit = self.parse(ranked_top[2], category)
            return [Clause('sort', direction='desc' if ranked_top[1] == '降序' else 'asc'), *limit] if limit else None
        top = re.fullmatch(r'(?:取|保留|选取)?(?:排名)?前([0-9]+|[一二两三四五六七八九十])(?:名|个|项|条)?', s)
        if top is None:
            top = re.fullmatch(r'(?:取)?[Tt][Oo][Pp]([0-9]+)', s)
        if top:
            n = int(top[1]) if top[1].isdigit() else NUMBERS[top[1]]
            return [Clause('top_n', value=n)] if 1 <= n <= 1000 else None
        if category in {'filters', 'analysis_limits'}:
            exclusion = s.startswith(('排除', '不包含', '不含'))
            clean = re.sub(r'^(?:只统计|仅统计|只分析|仅分析|不包含|排除|不含|只看|仅看|仅限|限于|仅)', '', s)
            explicit = []
            for f in self.profile.fields:
                names = '(?:' + '|'.join(re.escape(n) for n in {f.display_name, f.original_name} if n) + ')'
                match = re.fullmatch(names + r'(?:为|是|等于|=|：|:)(.+)', clean)
                if match:
                    explicit.append(Clause('filter', f.field_id, value={'operator': 'ne' if exclusion else 'eq', 'value': match[1].strip('“”\"\'')}))
            if len(explicit) == 1:
                return explicit
            # Compact expressions require an exact, untruncated observed value
            # and a unique candidate field. No fuzzy values or arbitrary suffixes.
            bound = observed_binding(clean, self.profile)
            if bound:
                field, values = bound
                operator = ('not_in' if exclusion else 'in') if len(values) > 1 else ('ne' if exclusion else 'eq')
                return [Clause('filter', field, value={'operator': operator, 'value': values if len(values) > 1 else values[0]})]
        metric = self.metric(s)
        return [metric] if metric else None

    @staticmethod
    def task_info(task):
        aggregations = [(i, s) for i, s in enumerate(task.steps) if s.operation in {'aggregate', 'group_aggregate'}]
        index, agg = aggregations[0] if len(aggregations) == 1 else (-1, None)
        filters = [(i, s, c) for i, s in enumerate(task.steps) if s.operation == 'filter' for c in s.params.get('conditions', [])]
        derives = {s.params.get('alias'): (i, s) for i, s in enumerate(task.steps) if s.operation == 'derive'}
        return index, agg, filters, derives

    def prove(self, clause, task):
        index, agg, filters, derives = self.task_info(task)
        def ref(step, **values):
            return {'task_id': task.task_id, 'step_id': step.step_id, 'operation': step.operation, **values}
        if clause.kind == 'output_boundary':
            if not output_boundaries.available():
                return []
            if clause.value == 'no_profit_analysis' and not output_boundaries.profit_references_absent(task, self.profile):
                return []
            return [{'task_id': task.task_id, 'check': 'enforced_report_boundary',
                     'policy_version': output_boundaries.POLICY_VERSION, 'boundary': clause.value}]
        if clause.kind == 'prohibited':
            # Verify absence of structural references; task prose cannot authorize it.
            refs = []
            for step in task.steps:
                p = step.params
                refs += [p.get('field'), *p.get('dimensions', [])]
                refs += [c.get('field') for c in p.get('conditions', [])]
                refs += [m.get('field') for m in p.get('metrics', [])]
            return [{'task_id': task.task_id, 'check': 'field_absent'}] if clause.field not in refs else []
        if clause.kind == 'no_exclusion':
            # A positive allow-list can also exclude a named value. Do not merely
            # search for ne/not_in or assume the currently observed rows prove intent.
            restrictions = [s for s in task.steps if s.operation == 'filter' and
                any(c.get('field') == clause.field for c in s.params.get('conditions', []))]
            return [{'task_id': task.task_id, 'check': 'no_field_filter', 'field': clause.field,
                     'values': clause.value}] if not restrictions else []
        if agg is None:
            return []
        if clause.kind == 'filter':
            expected = {'field': clause.field, **clause.value}
            def same(condition):
                if condition.get('field') != expected['field'] or condition.get('operator') != expected['operator']:
                    return False
                if expected['operator'] in {'in', 'not_in'} and isinstance(condition.get('value'), list):
                    encode = lambda values: {json.dumps(v, ensure_ascii=False, sort_keys=True) for v in values}
                    return encode(condition['value']) == encode(expected['value'])
                return json.dumps(condition.get('value')) == json.dumps(expected['value'])
            return [ref(step, condition=c) for i, step, c in filters if i < index and same(c)]
        if clause.kind == 'year':
            year = clause.value
            lower, upper = f'{year:04}-01-01', f'{year+1:04}-01-01'
            if self.fields[clause.field].logical_type == 'datetime':
                lower += 'T00:00:00'; upper += 'T00:00:00'
            matches = []
            for op, value in [('gte', lower), ('lt', upper)]:
                match = [ref(s, condition=c) for i, s, c in filters if i < index and c == {'field': clause.field, 'operator': op, 'value': value}]
                if not match:
                    break
                matches += match
            else:
                return matches
            for alias, (i, step) in derives.items():
                if i < index and step.params.get('function') == 'extract_year' and step.params.get('field') == clause.field:
                    matches = [ref(s, condition=c) for j, s, c in filters if i < j < index and c == {'field': alias, 'operator': 'eq', 'value': year}]
                    if matches:
                        return [ref(step, params=step.params), *matches]
            return []
        if clause.kind == 'dimension':
            return [ref(agg, dimension=clause.field)] if clause.field in agg.params.get('dimensions', []) else []
        if clause.kind == 'temporal_sort':
            for alias, (i, step) in derives.items():
                if i < index and step.params.get('field') == clause.field and step.params.get('function') == clause.function and agg.params.get('dimensions') == [alias]:
                    tail = [s for s in task.steps[index+1:] if s.operation in {'sort', 'top_n'}]
                    if tail and tail[-1].params.get('field') == alias and tail[-1].params.get('direction') == clause.direction:
                        return [ref(step, params=step.params), ref(agg, dimension=alias), ref(tail[-1], params=tail[-1].params)]
            return []
        metrics = [m for m in agg.params['metrics'] if (clause.field is None or m.get('field') == clause.field)
                   and (clause.function is None or m['function'] == clause.function)]
        if clause.field is None and clause.function == 'count':
            metrics = [m for m in metrics if m.get('field') is None]
        if clause.kind == 'metric':
            if clause.field is None:  # Explicit record count only, not nonmissing count.
                metrics = [m for m in metrics if m.get('field') is None]
            elif clause.function is None:
                metrics = [m for m in metrics if m['function'] not in {'count', 'distinct_count'}]
            return [ref(agg, metric=m, **({'count_basis': 'uploaded_rows_not_distinct_entities'} if m['function'] == 'count' and m.get('field') is None else {})) for m in metrics]
        if clause.kind in {'sort', 'top_n'}:
            # Bare sort/Top N needs a unique numeric metric; never guess among metrics.
            if len(metrics) != 1:
                return []
            alias = metrics[0]['alias']
            tail = [(i, s) for i, s in enumerate(task.steps) if i > index and s.operation in {'sort', 'top_n'}]
            if not tail or tail[-1][1].params.get('field') != alias:
                return []
            if clause.kind == 'sort':
                step = tail[-1][1]
                return [ref(step, metric=metrics[0], params=step.params)] if step.params.get('direction') == clause.direction else []
            tops = [s for _, s in tail if s.operation == 'top_n']
            return [ref(tops[0], metric=metrics[0], params=tops[0].params)] if len(tops) == 1 and tops[0].params.get('field') == alias and tops[0].params.get('n') == clause.value else []
        return []

    def audit(self, checked):
        intent = checked.intent_snapshot
        self.entity_context = ' '.join(str(getattr(intent.analysis_goal, key) or '') for key in ('analysis_object', 'business_goal')) if intent else ''
        binding = {'dataset_id': checked.plan.dataset_id, 'dataset_version': checked.plan.dataset_version,
                   'plan_id': checked.plan.plan_id, 'plan_version': checked.plan.plan_version,
                   'validation_version': checked.validation_version, 'registry_version': checked.registry_version}
        digest = hashlib.sha256(json.dumps({'checked': checked.model_dump(mode='json'), 'profile': self.profile.model_dump(mode='json'),
                                           'audit_version': '2.3'}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        items, parsed = [], []
        tasks = [t for t in checked.plan.tasks if t.task_id in checked.executable_task_ids]
        if intent is None:
            items.append(ConstraintProof(source='intent', raw_text='', status='unmapped', category='context', message='缺少已保存的分析需求，不能批准。'))
        else:
            dimensions = goal_dimensions(intent.analysis_goal.business_goal or '', self.profile)
            if dimensions is None:
                items.append(ConstraintProof(source='intent.analysis_goal.business_goal',
                    raw_text=intent.analysis_goal.business_goal, category='goal_dimensions', status='ambiguous',
                    message='目标中的分组字段名称重复，不能选择任意同名字段。'))
            elif dimensions:
                matches = []
                passed = bool(tasks)
                for task in tasks:
                    _, agg, _, _ = self.task_info(task)
                    okay = agg is not None and set(agg.params.get('dimensions', [])) == set(dimensions)
                    passed &= okay
                    if okay:
                        matches.append({'task_id': task.task_id, 'step_id': agg.step_id,
                                        'operation': agg.operation, 'dimensions': dimensions})
                items.append(ConstraintProof(source='intent.analysis_goal.business_goal',
                    raw_text=intent.analysis_goal.business_goal, category='goal_dimensions',
                    status='verified' if passed else 'mismatch', field_ids=dimensions, matches=matches,
                    message='目标中的明确字段分组已核对。' if passed else '计划分组与目标明确指定的字段不一致。'))
            for category in ('time_range', 'filters', 'metric_requirements', 'analysis_limits'):
                values = getattr(intent.constraints, category)
                values = [values] if category == 'time_range' and values else ([] if category == 'time_range' else values)
                for n, value in enumerate(values):
                    source = f'intent.constraints.{category}' + ('' if category == 'time_range' else f'[{n}]')
                    # Split only explicit conjunctions/punctuation. Every component must pass.
                    parts = [value.raw_text] if value.raw_text.startswith(PREFIX) else re.split(r'[，,；;]|并且|并|且', value.raw_text)
                    clauses = [self.parse(part, category) for part in parts if part.strip()]
                    if not clauses or any(c is None for c in clauses):
                        items.append(ConstraintProof(source=source, raw_text=value.raw_text, status='unmapped', category=category,
                            message='尚不能可靠对应到唯一字段和完整统计条件；请在新需求中明确字段、取值或口径。'))
                        continue
                    flat = [c for group in clauses for c in group]
                    parsed += flat
                    matches, okay = [], bool(tasks)
                    for clause in flat:
                        targets = checked.plan.tasks if clause.kind in {'prohibited', 'output_boundary'} else tasks
                        proofs = [self.prove(clause, task) for task in targets]
                        # Conservatively require the complete specified question in
                        # every executed direction; never stitch proofs across tasks.
                        passed = bool(proofs) and all(proofs)
                        okay &= passed
                        matches += [m for proof in proofs for m in proof]
                    items.append(ConstraintProof(source=source, raw_text=value.raw_text, status='verified' if okay else 'mismatch',
                        category=category, field_ids=list(dict.fromkeys(c.field for c in flat if c.field)), matches=matches,
                        message=('已核对受控报告表达边界。' if any(c.kind == 'output_boundary' for c in flat) else '已对应到当前可执行操作并核对条件。') if okay else '当前分析步骤未完整满足此条件，或存在多个可能的指标；请重新提出明确需求。'))
        if items:
            # A proved year cannot coexist with an unmentioned status restriction or
            # premature top_n. Reject additional row restrictions, not just omissions.
            allowed_filters = {(m['task_id'], m['step_id'], json.dumps(m['condition'], sort_keys=True))
                               for item in items for m in item.matches if 'condition' in m}
            has_top = any(c.kind == 'top_n' for c in parsed)
            specified_dimensions = {c.field for c in parsed if c.kind == 'dimension'}
            for task in tasks:
                index, agg, filters, _ = self.task_info(task)
                extra = [s.step_id for i, s, c in filters if i >= index or (task.task_id, s.step_id, json.dumps(c, sort_keys=True)) not in allowed_filters]
                extra += [s.step_id for i, s in enumerate(task.steps) if s.operation == 'top_n' and (i < index or not has_top)]
                if agg and specified_dimensions and set(agg.params.get('dimensions', [])) != specified_dimensions:
                    extra.append(agg.step_id)
                if agg is None or extra:
                    items.append(ConstraintProof(source=f'plan.tasks.{task.task_id}', raw_text=task.title, status='mismatch', category='scope',
                        message='计划中有尚未与需求完整核对的筛选、截取、分组或多次汇总，当前不能证明范围一致。',
                        matches=[{'task_id': task.task_id, 'step_id': step} for step in dict.fromkeys(extra)]))
        return ConstraintAudit(audit_version='2.3', binding=binding, digest=digest, items=items, all_verified=all(i.status == 'verified' for i in items))
