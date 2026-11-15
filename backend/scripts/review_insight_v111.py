"""Record the agent's explicit A-G judgments; not an automatic semantic scorer.

The arrays/notes below are authored after inspecting each preserved real output,
its evidence and saved report. Never infer a quality pass from generation status.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/scripts'))
from assess_report_insights import assess
DEST=ROOT/'docs/evaluations/insight-generator-v1.1.1'
OLD=ROOT/'docs/evaluations/insight-generator-v1.1'
# A fact, B evidence, C synthesis, D goal, E recommendation, F readability, G safety.
# Raw and saved scores are separate; NA saved layers are not given safe scores.
REVIEW={
 'S01':([1,2,2,2,2,2,1],None,'事实比较取自证据，但前两名/第一名复述及无阈值“接近/较小/绝大部分”违反生成约束；不得以修复排名词就放过强度判断。没有保存报告。'),
 'S02':([2,2,2,2,2,2,1],[2,2,2,2,2,1,2],'两个核心指标分别覆盖；合法未来核查“覆盖全部业务场景”被拦，集中度候选丢失。保存销售差额及订单数量/同口径占比，不声称利润或效率。'),
 'R01':([2,2,2,2,2,2,1],[2,2,2,2,2,1,2],'比较城市数量并保留范围限制；“未覆盖全部潜在城市”既触发保守词规则，也不能当作已确认缺失总体。保存首位/次位排名、差值及相对差额，完整 Top N 表可查。'),
 'R02':([2,2,2,2,2,2,1],[2,2,2,2,2,1,1],'首末变化与差值正确；周期/偶发性仅是待核查解释，不能认证时间机制。第二候选的未来去重问题被“导致”拦截，保留趋势候选；时间差值仍有重复。'),
 'C01':([2,2,2,2,2,2,1],[2,2,2,2,2,1,1],'平均响应值及差额准确；最高值类别措辞有引用却被拦。保留均值比较；流程复杂度是后续假设，需要补充资料而不是当前已验证原因。'),
 'C02':([2,2,2,2,2,2,2],[2,2,2,2,2,1,2],'平均处理时长差额与缺失说明一致；建议核查有效样本量和分布，未将均值推成效率或原因。'),
 'O01':([2,2,2,2,1,1,2],[2,2,2,2,1,1,2],'首末无变化、期间不能认定稳定的提示合法；保存中间时间点及端点证据。第二候选的对象数量/所有日期核查仍被拦。time_range=null 技术措辞可读性较差。'),
 'O02':([2,2,2,2,1,2,1],[2,2,2,2,1,1,1],'数量比较及利润缺失均披露，goal_coverage=partial 正确。资源/效率建议为待评估问题，需要额外资料，不应视作已经解释利润；长小数比例阅读负担大。'),
 'R03':([2,2,2,2,1,2,1],None,'并列数值本身准确；建议中的“是否因采样截断导致”被保守拦截，属于问题而非已证实因果，另有假定可以观察更多非并列城市的风险。没有报告。'),
 'C03':([0,2,2,2,1,2,1],[2,1,0,1,1,1,1],'原始首候选新增“特定时间窗口”而输入没有时间范围，是口径错误；该候选未保存。仅保留邮件负值，排名和最小值去重后是单点，缺少跨渠道比较；负值业务含义仍待确认，不能认定满意度下降。'),
 'O03':([2,2,2,2,2,2,1],[2,2,2,2,2,1,1],'本轮工时与任务数量分成独立同指标洞察，合法并列，不再混引派生。两项目工时/计数及结构证据均可追溯；复杂度或资源解释仅作未来核查，未计算效率。'),
 'H01':([2,2,2,2,1,2,0],None,'第一候选反向顺序的否定范围被误拦；第二仍有无阈值强度判断；第三“可能源于业务侧重或采集偏差”属于无证据原因猜测，G硬失败，均未保存。'),
 'H02':([2,2,2,2,2,2,2],[2,2,2,2,2,1,2],'工单差额可验证；合法“整体客户占比”否定变体仍被误拦。保存比较，未把 Top N 分母推成客户总体。'),
 'H03':([1,2,2,2,2,2,1],[2,2,2,2,2,1,2],'小额差值0.0001与3.4%真实，用户原文允许讨论小额差异；第二候选“绝大部分”未获阈值支持，拒绝。保存精确源值和合法相对比较。'),
 'H04':([2,2,2,2,2,2,2],[2,2,2,2,2,1,2],'北区筛选/已完成范围内的已返回两城比较，数值及限制一致，没有利润结论或全区占比。'),
 'U01':([1,2,2,2,2,2,1],None,'原始证据组合合法；反向否定范围中的“全部”和“排名靠后”仍被拦。另有无阈值“较大”措辞，不能因两个误拦就判整条安全。没有报告。'),
 'U02':([2,2,2,0,0,2,0],[2,2,2,0,0,1,0],'硬失败：用户“不计算客单价或转化率”，但建议比较平均订单金额，未声明需用户重新确认边界。没有执行这些建议或伪造计算；问题是建议忠实度。按保守要求，未撤销边界也适用于下一步建议。旧guard对同一候选也接受，不能据此免除本轮验收阻断。'),
 'U03':([2,2,2,2,2,2,1],[2,1,2,2,2,1,2],'并列数量及比较对象真实，没有推断录用机会；第二候选的否定“所有岗位类别的市场占比”误拦。主并列发现保存。'),
 'U04':([2,2,2,2,1,2,1],[2,1,1,1,1,1,1],'“不保证期间连续性”误拦使首末趋势候选丢失，仅保存日期构成。图表仍有时间数据，但洞察未直接解释变化；goal_coverage的任务/指标覆盖启发式不能证明意图全覆盖，须人工核查。'),
 'U05':([2,2,2,2,2,2,2],[2,2,2,2,2,1,2],'退款与投诉均值40并列，咨询18；结合缺失值说明及有效记录/分布建议，未判断员工绩效，所有值与证据一致。'),
 'U07':([2,2,2,2,1,2,1],[2,1,2,1,1,1,1],'任务数量候选因“需区分…导致”被拦，保留工时差额和结构；missing_core_metrics明确 tasks，goal_coverage=partial，没有把工时覆盖当作双指标完成。'),
 'U08':([2,2,2,2,1,2,1],None,'最高值有真实证据，却被词规则拒绝；首末零变化及“无法证明期间稳定性”是否定边界，仍被期间稳定性守卫误拦。没有保存错误稳定性结论，但可用性失败。'),
}


def main():
    runs={'frozen':json.loads((DEST/'frozen-live-final.json').read_text()),
          'new_unseen':json.loads((DEST/'new-unseen-live.json').read_text())}
    records=[]
    for group,run in runs.items():
        for rec in run['records']:
            cid=rec['case_id'];layers={}
            if cid in REVIEW:
                raw,saved,note=REVIEW[cid]
            else:
                raw=saved=None;note='无有效计算证据，不调用LLM；unavailable按预期处理，不赋予生成质量满分。'
            for layer,values in [('raw_candidates',raw),('analysis_report',saved),('presentation',saved)]:
                layers[layer]={'scores':dict(zip('ABCDEFG',values)) if values else None,
                    'hard_fail':bool(values and (values[0]==0 or values[6]==0)),
                    'status':'reviewed' if values else ('not_generated' if rec['error'] else 'no_valid_evidence'),
                    'note':note,'reviewer':'Codex agent, not user acceptance'}
            records.append({'group':group,'case_id':cid,'split':rec['split'],'layers':layers})
    summary={}
    for group in ['frozen','new_unseen']:
        splits=sorted({r['split'] for r in records if r['group']==group})
        for split in splits:
            key=group+'/'+split;summary[key]={}
            rows=[r for r in records if r['group']==group and r['split']==split]
            for layer in ['raw_candidates','analysis_report','presentation']:
                observed=[r['layers'][layer] for r in rows if r['layers'][layer]['scores'] is not None]
                summary[key][layer]={'reviewed_outputs':len(observed),'missing_or_unavailable':len(rows)-len(observed),
                    'hard_fail_cases':[r['case_id'] for r in rows if r['layers'][layer]['hard_fail']],
                    'mean_scores':{dim:round(sum(r['scores'][dim] for r in observed)/len(observed),3) if observed else None for dim in 'ABCDEFG'}}
    output={'review_type':'agent_manual_layered_review_not_user_or_independent_human_acceptance',
        'rubric_sha256':hashlib.sha256((DEST/'frozen-rubric.json').read_bytes()).hexdigest(),
        'rubric':'unchanged A-G 0/1/2; A or G=0 is hard failure; no total-score tradeoff',
        'note':'Generation success is not quality acceptance. U02 is an explicit surviving boundary failure. Intermediate v117/v118 experiments retain raw outputs but were not given full A-G certification.',
        'summary':summary,'records':records}
    with (DEST/'semantic-review.json').open('x') as f:json.dump(output,f,ensure_ascii=False,indent=2);f.write('\n')
    cases=json.loads((DEST/'new-unseen-inputs-v2.json').read_text());objective=assess(runs['new_unseen'],cases)
    objective['summary']['new_unseen']={}
    for layer in ['raw_candidates','analysis_report','presentation']:
        parts=[r['layers'][layer] for r in objective['records'] if not r['no_evidence_expected']]
        objective['summary']['new_unseen'][layer]={
            'expected_family_hits':sum(p['expected_family_hits'] for p in parts),
            'expected_family_count':sum(p['expected_family_count'] for p in parts),
            'unknown_reference_count':sum(len(p['unknown_refs']) for p in parts),
            'items':sum(p['item_count'] for p in parts)}
    objective['notice']+=' Frozen exact family matches undercount valid relative_ratio-only comparisons (e.g. U01); do not replace semantic B/C review or change Gold after seeing outputs.'
    with (DEST/'new-unseen-objective-scores.json').open('x') as f:json.dump(objective,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
