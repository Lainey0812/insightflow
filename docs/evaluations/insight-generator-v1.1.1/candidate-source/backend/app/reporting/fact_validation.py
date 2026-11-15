"""Validate structured facts; free business interpretation is deliberately not certified."""
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext

from app.domain.analysis_report import Insight
from app.domain.errors import AppError
from .evidence import fmt
from . import claims

# Numeric or statistical assertions are not permitted in free interpretation text.
NUMERIC = re.compile(r"[0-9０-９]|[零〇一二三四五六七八九十百千万亿两点]{2,}|第[一二三四五六七八九十百千万两]+|[一二三四五六七八九十两](?:成|倍|条|个|名|位|年|月)|百分之|半数|一半")
UNSUPPORTED_ASSERTION = re.compile(r"导致|造成|归因于|证明|必然|保证|因果|显著|最高|最低|排名|占比|翻倍|全部|所有|超过.*半|大多数")
UNSUPPORTED_BUSINESS_CLAIM = re.compile(
    r"(?:利润|盈利能力|经营效率|投入产出|profit|efficiency).{0,10}(?:更高|更好|较高|领先|优于|最佳|higher|better)|"
    r"(?:更高|更好|较高|领先|最佳).{0,8}(?:利润|盈利能力|经营效率)|"
    r"\b(?:causes?|proves?|guarantees?)\b", re.IGNORECASE)
# These express a limit on inference, not a positive statistical/business claim.
# Restrict the subject and objects; do not blanket-whitelist negated causal clauses.
INFERENCE_LIMIT = re.compile(
    r"(?:销售额)?排名(?:不能|无法|不足以|不直接)(?:证明|说明|代表|判断|推断)"
    r"(?:盈利能力|利润|经营效率|投入效果|资源投入效果)(?:或(?:盈利能力|利润|经营效率|投入效果|资源投入效果))*")
COMPATIBLE = {
    "highlight": {"metric", "ranking", "maximum", "minimum"},
    "difference": {"difference", "comparison"},
    "concentration": {"proportion", "comparison"},
    "trend": {"change_rate"},
    "coverage": {"coverage"},
}


def literal_fact(evidence):
    value = evidence.value
    if evidence.evidence_type == "coverage":
        return f"该任务记录的有效样本量为 {fmt(value['valid_samples'])}，上传数据共 {fmt(value['dataset_rows'])} 条记录。"
    if evidence.evidence_type in {"ranking", "maximum", "minimum"}:
        return f"{fmt(value['category'])}的已计算指标值为 {fmt(value['value'])}。"
    if evidence.evidence_type == "proportion":
        return f"{fmt(value['category'])}的分组指标为 {fmt(value['numerator'])}，同口径总体分母为 {fmt(value['denominator'])}。"
    if evidence.evidence_type in {"difference", "comparison"}:
        return f"两个被比较的已计算指标值分别为 {fmt(value['left_value'])} 与 {fmt(value['right_value'])}。"
    if evidence.evidence_type == "change_rate":
        return f"已返回首期值为 {fmt(value['baseline'])}，末期值为 {fmt(value['current'])}。"
    return evidence.statement


def semantic_key(e):
    if e.evidence_type in {'ranking', 'maximum', 'minimum'}:
        return (e.task_id, e.data_ref, e.result_field, 'point', str(e.value['category']), str(e.value['value']))
    return (e.task_id, e.data_ref, e.result_field, e.evidence_type, str(e.value))


def validate_comparison(e, tables=None):
    """Verify structured derived operands; the model never supplies these values."""
    kind = e.value.get('comparison_kind')
    if not kind:
        return
    try:
        value = e.value
        n, d, actual = (Decimal(str(value[k])) for k in ('numerator', 'denominator', 'percent'))
        a, b = (Decimal(str(value[k])) for k in ('left_value', 'right_value'))
        if not all(v.is_finite() for v in (n, d, actual, a, b)) or d <= 0:
            raise ValueError()
        if kind == 'relative_lead':
            valid = n == a - b and d == b and Decimal(str(value['difference'])) == n
        elif kind == 'relative_ratio':
            valid = n == a and d == b and a >= 0
        elif kind == 'returned_concentration':
            valid = n == a + b and 0 <= n <= d and value.get('denominator_scope') == 'returned_groups_only'
        else:
            valid = False
        with localcontext() as ctx:
            ctx.prec = max(28, actual.adjusted() + 10)
            if not valid or (n / d * 100).quantize(Decimal('.1'), rounding=ROUND_HALF_UP) != actual:
                raise ValueError()
        if tables is not None:
            table = tables[e.data_ref]
            field, dim = e.result_field, value['dimension_field']
            rows = [table.rows[index] for index in e.source_row_indices]
            if value.get('metric_field') != field or any(field not in row or dim not in row for row in rows):
                raise ValueError()
            left = [row[field] for row in rows if row[dim] == value['left']]
            right = [row[field] for row in rows if row[dim] == value['right']]
            if len(left) != 1 or len(right) != 1 or Decimal(str(left[0])) != a or Decimal(str(right[0])) != b:
                raise ValueError()
            if kind == 'returned_concentration' and (table.truncated or table.row_offset or
                    set(e.source_row_indices) != set(range(len(table.rows))) or
                    sum(Decimal(str(row[field])) for row in rows) != d):
                raise ValueError()
    except (ValueError, KeyError, IndexError, TypeError, ArithmeticError):
        raise AppError('REPORT_INVALID_COMPARISON', '比较证据的分子、分母、对象或结果来源不一致。', 502) from None


def validate_text(text, role, chosen=(), tasks=None, tables=None, trusted_limitations=(), diagnostics=None):
    """Conservative prose guard; finite verified references, not a semantic parser.

    Normalization below changes only the checking view. Original text is retained
    in the Insight and in audit metadata. Unknown factual claims still fail closed.
    """
    if role == 'limitation' and text in trusted_limitations:
        return
    checked = text
    verified = []
    def replace(old, new, rule):
        nonlocal checked
        if old in checked:
            checked = checked.replace(old, new)
            verified.append({'rule': rule, 'fragment': old})

    # Treat complete boundary phrases before any shorter phrase can destroy their
    # negation. A trailing affirmative clause is checked separately as before.
    for boundary in ['不保证时间点连续', '不是全部筛选范围或整体市场占比',
                     '不代表全部筛选范围或整体市场占比',
                     '不是全部筛选范围或整体市场', '不代表全部筛选范围或整体市场',
                     '不能仅凭返回表格确认所有分组均已覆盖',
                     '当前数据不足以判断造成差异的具体业务原因']:
        replace(boundary, '推断边界', 'NEGATIVE_BOUNDARY')
    if chosen and any(e.evidence_type == 'change_rate' for e in chosen):
        # Endpoint equality is not interval stability, even when all sampled
        # endpoints happen to match. No stability evidence exists in V1.1.1.
        for clause in re.split(r'[，。；;]|但是|但|然而', checked):
            if '稳定' in clause and not any(s in clause for s in ['不能判断', '无法判断', '不足以判断', '核查', '验证']):
                raise AppError('REPORT_UNVERIFIED_FACT', '首末比较不能证明期间稳定。', 502,
                    details={'rule': 'ENDPOINT_NOT_INTERVAL_STABILITY', 'role': role, 'text': text})
    for term in claims.pair_terms(chosen, tables):
        replace(term, '对应对象', 'BOUND_COMPARISON_OBJECTS')
    if claims.all_returned_equal(chosen, tables):
        replace('返回结果中所有分组', '本次返回分组', 'ALL_RETURNED_CELLS_EQUAL')
    if any(e.value.get('comparison_kind') == 'returned_concentration' for e in chosen):
        replace('前两个排名分组', '已比较对象', 'BOUND_CONCENTRATION_PAIR')
    if any(e.evidence_type == 'ranking' for e in chosen):
        replace('排名靠前', '已引用的前列对象', 'BOUND_RANKING_REFERENCE')
    if tasks and chosen:
        for step in tasks[chosen[0].task_id].steps:
            if step.operation == 'top_n' and isinstance(step.params.get('n'), int):
                n = step.params['n']
                for match in list(re.finditer(r'Top\s*'+str(n)+r'(?![0-9A-Za-z_])', checked, re.I)):
                    replace(match.group(), '已批准选择', 'BOUND_TOP_N')
        if role == 'limitation':
            for task in tasks.values():
                # Priority tokens are metadata only in an explicit task label.
                if task.title in checked:
                    replace(task.priority+'任务', '对应任务', 'BOUND_TASK_PRIORITY')
    has_ratio = any(e.evidence_type == 'proportion' or e.value.get('comparison_kind') in
                    {'returned_concentration', 'relative_ratio'} for e in chosen)
    if has_ratio:
        for clause in re.split(r'[，。；;]|但是|但|然而', checked):
            if '占比' in clause and any(w in clause for w in ['整个', '全部', '总体', '市场份额']):
                # This term cannot be normalized merely because some ratio exists.
                raise AppError('REPORT_UNVERIFIED_FACT', '比例解释的总体范围未经证据绑定。', 502,
                    details={'rule': 'UNBOUND_POPULATION_SCOPE', 'role': role, 'text': text})
        # Only vocabulary, no amounts or ranking assertions are exempted. Numeric
        # prose and "最高" remain guarded after this scoped reference check.
        replace('占比', '构成', 'BOUND_RATIO_VOCABULARY')
    for allowed in ['不构成因果结论', '不能据此推断因果关系', '不代表因果关系']:
        checked = checked.replace(allowed, '')
    checked = INFERENCE_LIMIT.sub('', checked)
    checked = re.sub(r'(?:销售额)?(?:不能|无法|不足以)(?:证明|判断|推断)(?:盈利能力|利润|经营效率)', '', checked)
    checked = re.sub(r'(?:不能|无法|不足以|不可)(?:据此|直接)?(?:判断|评价|推断|认定)(?:人员绩效|员工绩效|经营表现|经营效率|盈利能力|利润|市场份额|录用机会)', '', checked)
    checked = re.sub(r'(?:不代表|不能代表|无法代表|不能外推至?)(?:全部筛选范围|整体市场|总体人群|总体|所有分组)(?:占比|比例)?', '', checked)
    checked = checked.replace('已返回的排名结果', '已返回的结果')
    # Ground bounded object-count references, never arbitrary metric values.
    # "两个渠道" describes a verified comparison pair, not two orders or years.
    pair = any('left' in e.value and 'right' in e.value for e in chosen)
    if pair:
        checked = re.sub(r'(?:这|该)?两(?:个(?:分组|城市|渠道|项目|类别)|类(?:工单|记录))|两者', '对应对象', checked)
    if any(e.value.get('comparison_kind') == 'returned_concentration' for e in chosen):
        checked = checked.replace('前两名', '已比较对象').replace('前两个返回分组', '已比较对象')
    if tasks and chosen:
        task = tasks[chosen[0].task_id]
        if role == 'limitation':
            for task_id in tasks:
                checked = re.sub(r'(?<![A-Za-z0-9_])'+re.escape(task_id)+r'(?![A-Za-z0-9_])', '对应任务', checked)
        for step in task.steps:
            if step.operation == 'top_n':
                n = step.params.get('n')
                if isinstance(n, int):
                    checked = re.sub(r'Top\s*'+str(n)+r'\b', '已批准选择', checked, flags=re.I)
                    chinese = {1:'一',2:'二',3:'三',4:'四',5:'五',6:'六',7:'七',8:'八',9:'九',10:'十'}.get(n)
                    if chinese:
                        checked = checked.replace('前'+chinese+'名', '已批准选择')
    # A negative inference boundary is not a positive causal or population claim.
    checked = re.sub(r'(?:不能|无法|不足以)(?:据此|直接)?归因于[^，。；;]*', '推断边界', checked)
    checked = checked.replace('不是全部筛选范围或整体市场占比', '分母范围边界')
    checked = checked.replace('不代表全部筛选范围或整体市场占比', '分母范围边界')
    checked = checked.replace('不能仅凭返回表格确认所有分组均已覆盖', '覆盖边界')
    if role == 'recommendation' and re.match(r'(?:建议|进一步|补充|比较|对比|核查|核对|确认|检查|评估|检验)', checked):
        # Future requests to investigate observable relationships are not completed causal proof.
        checked = re.sub(r'是否(?:由|与|源于)[^，。；;]*(?:驱动|引起|相关|导致|所致)', '待核查关联', checked)
        checked = checked.replace('占比', '构成').replace('排名', '排序')
    elif role == 'implication':
        checked = checked.replace('占比结构', '构成结构').replace('合计占比', '合计构成')
    # Numeric facts belong to deterministic composition, including English numeric claims.
    english_number = re.search(r'\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|percent|percentage|ninety)\b', checked, re.I)
    causal = re.search(r'源自|源于|得益于|驱动|由于|因为|促成|决定了|带来.{0,12}(?:增长|下降|增加|减少)|\b(?:because|caus\w*|attribut\w*|proves?|guarantees?)\b', checked, re.I)
    business = re.search(r'(?:利润|盈利|效率|绩效|录用机会|营销效果|市场份额|profit|efficiency).{0,12}(?:高于|低于|更|领先|最佳|提升|改善|增加|下降|better|higher|greater)|(?:高于|低于|更高|更好|提升).{0,8}(?:利润|盈利|效率|profit|efficiency)', checked, re.I)
    completed = re.search(r'已(?:经)?(?:验证|证实|确定|找到|解释)|已完成(?:补充|后续|建议|进一步|全部|所有)|(?:核心|全部)目标.{0,5}已完成|事实证明|可以确定|足以说明|持续(?:增长|下降)|未来(?:将|会)', checked)
    threshold_claim = re.search(r'绝大部分|高度集中|规模优势|显著|相对差异较大|参与不足|竞争态势', checked)
    matches = {name: match.group() for name, match in [
        ('NUMERIC', NUMERIC.search(checked)), ('ENGLISH_NUMBER', english_number),
        ('CAUSAL', causal), ('BUSINESS_ASSERTION', business), ('COMPLETED_CLAIM', completed),
        ('UNDEFINED_THRESHOLD', threshold_claim), ('UNSUPPORTED_ASSERTION', UNSUPPORTED_ASSERTION.search(checked)),
        ('UNSUPPORTED_BUSINESS_CLAIM', UNSUPPORTED_BUSINESS_CLAIM.search(checked))] if match}
    if matches:
        raise AppError('REPORT_UNVERIFIED_FACT', '解释或建议包含未验证数值、原因、经营判断或已证实声明。', 502,
            details={'rule': 'FREE_TEXT_GUARD', 'role': role, 'text': text, 'matches': matches})
    if diagnostics is not None and verified:
        diagnostics.append({'role': role, 'original_text': text, 'checking_view': checked,
            'verified_references': verified, 'display_text_changed': False,
            'evidence_refs': [e.evidence_id for e in chosen]})


def materialize(draft, evidence, tasks, result_data=None, *, require_core=True, trusted_limitations=(), diagnostics=None):
    by_id = {item.evidence_id: item for item in evidence}
    insights = []
    seen = set()
    seen_facts = set()
    for index, item in enumerate(draft.insights):
        refs = item.evidence_refs
        if len(refs) != len(set(refs)) or not set(refs) <= by_id.keys() or item.primary_evidence_id not in refs:
            raise AppError("REPORT_INVALID_EVIDENCE_REFERENCE", "洞察引用不存在、重复或缺少主要证据。", 502)
        primary = by_id[item.primary_evidence_id]
        if primary.evidence_type not in COMPATIBLE[item.finding_type] or primary.evidence_id in seen:
            raise AppError("REPORT_INVALID_EVIDENCE_TYPE", "洞察类型与证据不匹配，或重复使用主要证据。", 502)
        chosen = [by_id[ref] for ref in refs]
        claims.compatible(primary, chosen)
        if item.finding_type == 'concentration' and primary.evidence_type == 'comparison' and primary.value.get('comparison_kind') != 'returned_concentration':
            raise AppError('REPORT_INVALID_EVIDENCE_TYPE', '集中度必须引用有明确分母的构成证据。', 502)
        atoms, keys = [], set()
        for e in chosen:
            claims.validate_source(e, result_data, tasks)
            validate_comparison(e, result_data)
            key = semantic_key(e)
            if key not in keys:
                atoms.append(e.statement.replace(' · ', ''))
                keys.add(key)
        if semantic_key(primary) in seen_facts or keys <= seen_facts:
            raise AppError('REPORT_DUPLICATE_FINDING', '该发现与已选择事实重复，没有新增证据信息。', 502)
        for role, text in [('implication', item.implication), ('recommendation', item.recommendation), *[('limitation', s) for s in item.limitations]]:
            validate_text(text, role, chosen, tasks, result_data, trusted_limitations, diagnostics)
        combined = claims.compose([e for e in chosen if semantic_key(e) in keys], result_data)
        if len(combined) > 1800:
            raise AppError('REPORT_FACT_COMPOSITION_TOO_LARGE', '单条事实组合过长，请减少重复证据。', 502)
        seen.add(primary.evidence_id)
        seen_facts.update(keys)
        # All selected atoms are expressed, not merely attached as invisible citations.
        insights.append(Insight(insight_id=f"I{index + 1:03d}", task_id=primary.task_id,
            fact='事实依据：' + '、'.join(refs) + '；数值、对象及统计范围已逐项核对。', finding=combined,
            implication='待验证的业务解释：' + item.implication[:1850],
            recommendation='下一步建议（尚未执行）：' + item.recommendation[:1850], evidence_refs=refs,
            limitations=[*item.limitations, '业务解释是待验证假设，未经过完整语义事实验证；不能据此推断因果关系。'] ))
    if require_core and {e.task_id for e in evidence if tasks[e.task_id].priority == 'P0'} - {i.task_id for i in insights}:
        raise AppError("REPORT_CORE_FINDINGS_MISSING", "洞察遗漏了已有证据的核心任务。", 502)
    return sorted(insights, key=lambda i: (tasks[i.task_id].priority, i.insight_id))


def materialize_candidates(draft, evidence, tasks, result_data, trusted_limitations=(), *, diagnostics=None):
    """Isolate rejected candidates visibly. Never repair claims or invent fallback insights."""
    from app.domain.analysis_report import InsightDraft
    accepted, rejected, seen = [], [], set()
    by_id = {e.evidence_id: e for e in evidence}
    first_error = None
    for index, item in enumerate(draft.insights):
        try:
            candidate = materialize(InsightDraft(insights=[item]), evidence, tasks, result_data,
                require_core=False, trusted_limitations=trusted_limitations, diagnostics=diagnostics)[0]
            key = semantic_key(by_id[item.primary_evidence_id])
            if key in seen:
                raise AppError('REPORT_DUPLICATE_FINDING', '该候选发现重复，没有新增事实。', 502)
            seen.update(semantic_key(by_id[ref]) for ref in item.evidence_refs)
            candidate.insight_id = f'I{len(accepted) + 1:03d}'
            accepted.append(candidate)
        except AppError as exc:
            first_error = first_error or exc
            # Rejected prose stays outside the saved business report. Keep rule
            # identity and binding diagnostics, never embed a rejected assertion
            # in metadata that might later be mistaken for a valid report fact.
            details = {k: v for k, v in exc.error.details.items() if k not in {'text', 'matches'}}
            if 'matches' in exc.error.details:
                details['triggered_rules'] = list(exc.error.details['matches'])
            rejected.append({'candidate_index': index, 'primary_evidence_id': item.primary_evidence_id,
                             'error_code': exc.error.code, 'details': details})
    if not accepted:
        error = first_error or AppError('REPORT_NO_VALID_INSIGHTS', '没有通过校验的洞察。', 502)
        error.error.details['rejected_candidates'] = rejected
        raise error
    missing_core = {e.task_id for e in evidence if tasks[e.task_id].priority == 'P0'} - {i.task_id for i in accepted}
    if missing_core:
        raise AppError('REPORT_CORE_FINDINGS_MISSING', '已有证据的核心任务未形成合法洞察，未保存完整报告。', 502)
    return sorted(accepted, key=lambda i: (tasks[i.task_id].priority, i.insight_id)), rejected
