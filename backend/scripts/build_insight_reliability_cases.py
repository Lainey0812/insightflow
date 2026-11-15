"""Freeze new report-only cases, using existing deterministic test kernels.

No LLM call. Inputs are marked imported kernel results, not production Engine
executions. Never overwrite frozen fixtures or tune them from model output.
"""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
from report_fixtures import report_case
from planning_fixtures import task,step


def build(cid,domain,query,raw,metrics,*,top=None,failed=False,null=False):
    ops=[step('group_aggregate',{'dimensions':['field_0001'],'metrics':metrics})]
    if top:
        ops.append(step('top_n',{'field':metrics[0]['alias'],'direction':'desc','n':top},'S02'))
    t=task(ops);t.update(title=query,business_question=query,
        priority_reason='删除后无法回答当前用户明确提出的比较问题。')
    i,v,x,p=report_case([t],raw.encode())
    i.analysis_goal.analysis_object={'sales':'区域订单','recruiting':'岗位发布记录','support':'服务请求','operations':'项目运营记录'}[domain]
    i.analysis_goal.business_goal=query
    v.plan.core_requirements[0].description=query
    p.file_name=f'{cid}-{domain}.csv'
    for et in x.tasks:
        et.scope=query+'；仅限本次上传与操作链筛选范围。'
        if et.result:
            for c in et.result.columns:
                if c.role=='metric':
                    m=next(m for m in metrics if m['alias']==c.field)
                    source=next((f.display_name for f in p.fields if f.field_id==m.get('field')),None)
                    c.label=(source or '记录数量')+' · '+{'sum':'合计','count':'计数','avg':'平均值'}[m['function']]
                    c.unit='条' if m['function']=='count' else None
    families=['difference'] if not null else []
    if not top and p.fields[0].logical_type in {'date','datetime'}:families=['change_rate']
    return {'case_id':cid,'domain':domain,'split':'new_unseen','query':query,
        'note':'New independent report-only fixture; deterministic existing kernels, imported provenance; no model used to label results.',
        'expected':{'important_families':families,'no_valid_evidence':null,'unsupported_business_claims_allowed':False},
        'input':{'intent':i.model_dump(mode='json'),'validated':v.model_dump(mode='json'),
                 'execution':x.model_dump(mode='json'),'profile':p.model_dump(mode='json'),'original_query':query}}


def main():
    cases=[
        build('U01','sales','比较门店成交金额前三名，不能据此判断利润；仅说明返回范围的差异。',
            '门店,成交金额\n海棠,810\n松林,790\n云山,120\n石桥,95\n',
            [{'function':'sum','field':'field_0002','alias':'revenue'}],top=3),
        build('U02','sales','比较各渠道的订单总金额和订单数，两个指标分别解读，不计算客单价或转化率。',
            '渠道,订单金额\n直播,90\n直播,30\n商城,80\n门店,10\n',
            [{'function':'sum','field':'field_0002','alias':'amount'},{'function':'count','alias':'orders'}]),
        build('U03','recruiting','比较岗位类别数量，平手只说明并列，不推断录用机会。',
            '岗位类别,编号\n研发,r1\n运营,r2\n设计,r3\n研发,r4\n运营,r5\n',
            [{'function':'count','alias':'postings'}]),
        build('U04','recruiting','比较不同发布日期的岗位数量变化；不推断未观察日期或未来招聘趋势。',
            '发布日期,岗位\n2026-04-03,甲\n2026-04-03,乙\n2026-05-17,丙\n2026-07-09,丁\n2026-07-09,戊\n2026-07-09,己\n',
            [{'function':'count','alias':'postings'}]),
        build('U05','support','比较各请求类型平均首次响应时长，说明缺失值局限；不能判断员工绩效。',
            '请求类型,首次响应分钟\n咨询,18\n咨询,\n退款,40\n投诉,60\n投诉,20\n',
            [{'function':'avg','field':'field_0002','alias':'response'}]),
        build('U06','support','比较服务渠道平均处理时长；没有有效数值时不要生成洞察。',
            '服务渠道,处理分钟\n电话,\n在线,\n邮件,\n',
            [{'function':'avg','field':'field_0002','alias':'duration'}],null=True),
        build('U07','operations','比较交付组总投入小时与任务数，分别展示，不推算效率或任务复杂度。',
            '交付组,投入小时\n星组,7\n星组,5\n月组,15\n日组,3\n',
            [{'function':'sum','field':'field_0002','alias':'hours'},{'function':'count','alias':'tasks'}]),
        build('U08','operations','比较各观察日期的处理任务数量；首末相同不能证明整个期间稳定。',
            '观察日期,任务\n2026-06-02,甲\n2026-06-02,乙\n2026-06-11,丙\n2026-06-11,丁\n2026-06-11,戊\n2026-06-11,己\n2026-06-27,庚\n2026-06-27,辛\n',
            [{'function':'count','alias':'tasks'}]),
    ]
    dest=ROOT/'docs/evaluations/insight-generator-v1.1.1/new-unseen-inputs-v2.json'
    with dest.open('x') as f:json.dump(cases,f,ensure_ascii=False,indent=2);f.write('\n')
    print('Frozen 8 new independent inputs (7 generatable + 1 no-evidence).')


if __name__=='__main__':main()
