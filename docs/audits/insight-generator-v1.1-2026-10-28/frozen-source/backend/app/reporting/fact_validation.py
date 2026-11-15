"""Validate structured facts; free business interpretation is deliberately not certified."""
import re

from app.domain.analysis_report import Insight
from app.domain.errors import AppError
from .evidence import fmt

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
    "concentration": {"proportion"},
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


def materialize(draft, evidence, tasks):
    by_id = {item.evidence_id: item for item in evidence}
    insights = []
    seen = set()
    for index, item in enumerate(draft.insights):
        refs = item.evidence_refs
        if len(refs) != len(set(refs)) or not set(refs) <= by_id.keys() or item.primary_evidence_id not in refs:
            raise AppError("REPORT_INVALID_EVIDENCE_REFERENCE", "洞察引用不存在、重复或缺少主要证据。", 502)
        primary = by_id[item.primary_evidence_id]
        if primary.evidence_type not in COMPATIBLE[item.finding_type] or primary.evidence_id in seen:
            raise AppError("REPORT_INVALID_EVIDENCE_TYPE", "洞察类型与证据不匹配，或重复使用主要证据。", 502)
        if any(by_id[ref].task_id != primary.task_id for ref in refs):
            raise AppError("REPORT_INVALID_EVIDENCE_REFERENCE", "单条洞察不能混合不同任务的证据口径。", 502)
        for text in [item.implication, item.recommendation, *item.limitations]:
            checked_text = text
            for allowed in ["不构成因果结论", "不能据此推断因果关系", "不代表因果关系"]:
                checked_text = checked_text.replace(allowed, "")
            checked_text = INFERENCE_LIMIT.sub("", checked_text)
            if primary.evidence_type in {"ranking", "maximum", "minimum"}:
                # A neutral reference to an actual ranking is not a new rank assertion.
                checked_text = checked_text.replace("已返回的排名结果", "已返回的结果")
            if NUMERIC.search(checked_text) or UNSUPPORTED_ASSERTION.search(checked_text) or UNSUPPORTED_BUSINESS_CLAIM.search(checked_text):
                raise AppError("REPORT_UNVERIFIED_FACT", "解释或建议含无法验证的数值、统计断言或因果表述。", 502)
        seen.add(primary.evidence_id)
        # No LLM-written numbers/ranks are copied into facts or findings.
        insights.append(Insight(insight_id=f"I{index + 1:03d}", task_id=primary.task_id,
            fact=literal_fact(primary), finding=primary.statement, implication="可能意味着：" + item.implication[:1900],
            recommendation="可考虑：" + item.recommendation[:1900], evidence_refs=refs,
            limitations=[*item.limitations, "业务解释和建议尚未经过严格事实验证；样本现象不代表因果关系。"] ))
    if any(tasks[e.task_id].priority == "P0" for e in evidence) and not any(tasks[i.task_id].priority == "P0" for i in insights):
        raise AppError("REPORT_CORE_FINDINGS_MISSING", "洞察遗漏了已有证据的核心任务。", 502)
    return sorted(insights, key=lambda i: (tasks[i.task_id].priority, i.insight_id))
