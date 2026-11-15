"""Agent semantic review using the previously frozen A–G rubric; not user acceptance."""
import json
from pathlib import Path
P=Path(__file__).resolve().parent
OLD={
'S01':([2,0,0,1,1,1,2],'仅排名，建议通用；旧展示层另有确定性三条发现。'),
'S02':([2,0,0,2,1,1,1],'覆盖两核心任务，但没有差额比较；潜力/效率用语超出当前证据。'),
'R01':([2,0,0,1,1,1,1],'岗位数复述，建议招聘预算/录用资料较泛化。'),
'R02':([2,0,0,1,1,1,1],'选择最高发布日期而未回答时间变化，未返回其他日期的警示缺乏必要性。'),
'C01':([2,0,0,1,2,1,2],'单类别均值复述，但建议工单复杂度/排班与发现相关，未认定原因。'),
'C02':([2,1,1,1,0,1,1],'有渠道差额，建议却使用订单结构/成本，领域不匹配。'),
'O01':([2,0,0,1,1,1,1],'复述单日高值，未回答首末变化。'),
'O02':([2,0,0,1,2,1,1],'正确披露利润缺失，完成数不等于执行效率。'),
'R03':([2,0,0,1,1,1,2],'保留并列极值来源，但事实和建议信息量低。'),
'C03':([2,0,0,1,1,1,1],'单极值复述，净变化不等于渠道效能。'),
'O03':([1,0,1,1,1,1,1],'引用工时及任务数量不同指标，保存事实仍只有主要证据；单位任务占用特征未计算。'),
'H01':([2,1,1,2,2,1,1],'引用一个已计算构成比例，建议核查岗位定义/计划，综合程度有限。'),
'H02':([2,0,0,1,2,1,2],'原始候选谨慎且建议相关；原运行校验拒绝，不能给保存报告评分。'),
'H03':([2,1,1,2,1,1,2],'已计算差值合法，建议生产设备排程缺少领域依据但为待核查资料。'),
'H04':([2,0,0,1,1,1,1],'仅首位金额，没有两城比较；成本建议偏离只比较销售额。'),
}
NEW_RAW={
'S01':([2,2,2,2,2,2,1],'选择相对差额、首尾比例与返回组内集中度；第三项含未设阈值的集中度高及潜在未返回城市措辞。'),
'S02':([2,2,2,2,1,2,0],'前两项比较相关；第三项从销售构成猜测资源集中、整体市场结构，无资源证据。'),
'R01':([2,2,2,2,1,2,0],'岗位比较相关；第二项由岗位数猜测资源区域倾斜/策略，没有资源证据。'),
'R02':([2,2,2,2,2,2,1],'选中已计算首末变化；中间过程未知的表述需区分离散点与未返回数据。'),
'C01':([2,2,2,2,2,2,2],'均值差额、咨询/投诉比例和具体核查建议均相关，未认定因果或人员效率。'),
'C02':([2,2,2,2,2,2,2],'比较渠道均值，建议有效记录数/缺失归属，明确不据此判断服务效率影响。'),
'O01':([0,2,2,2,2,2,0],'首末相同不代表时间段产出稳定；中间已返回日期数量不同。整份未保存。'),
'O02':([2,2,2,2,2,2,2],'保留任务完成数比较和利润缺口；P0标识被数字规则误拒。'),
'R03':([2,1,1,2,2,2,2],'所有已返回分组相等符合实际；所有一词被保守规则误拒。'),
'C03':([2,2,2,2,1,2,1],'差额及负值有依据；建议追加时长、数据规则核查较宽泛，非已证实原因。'),
'O03':([0,2,2,2,1,2,1],'跨工时/任务数量混引，依现有契约无法校验同一指标口径；未进入报告。'),
'H01':([2,2,2,2,1,2,1],'有构成和差额，但绝大部分/两类岗位等触发阈值或数量指代规则。'),
'H02':([2,2,2,2,2,2,1],'否定原因边界及两个服务组触发保守规则；有查询范围偏差的未验证措辞。'),
'H03':([2,2,2,2,2,2,1],'差额、集中度引用合法；两个批次以及占比用语被拦，未返回分组建议需更谨慎。'),
'H04':([2,2,2,2,2,2,2],'明确范围内的两城差额和相对差额，建议订单数量/金额/构成，与事实直接关联。'),
}
NEW_SAVED={
'S01':([2,1,2,2,2,1,2],'两条事实实际综合多证据，保留差额/相对差额/首尾比例；集中度候选拒绝，87.8%仍保存在证据/KPI。叙述偏长。'),
'S02':([2,2,2,2,1,1,1],'保留两个核心任务比较，拒绝资源集中推测；建议中的高单量少订单措辞不清，效率提议仍需更谨慎。'),
'R01':([2,2,2,2,2,1,2],'保留城市差额和相关岗位核查建议；资源策略推测未保存。'),
'R02':([2,2,2,2,2,1,1],'首末变化、差额和两端实际值统一保存，未推断连续趋势；文字仍长。'),
'C01':([2,2,2,2,2,1,2],'类别均值差额与比例均可溯源，建议可验证；排名与极值表述有重复。'),
'C02':([2,2,2,2,2,1,2],'有效比较及缺失限制保存；样本量口径与指标非空数明确分开。'),
'C03':([2,2,1,2,1,1,1],'首条比较有依据；第二条排名和最小值实为同一事实，refs多不等于综合。'),
'H04':([2,2,2,2,2,1,2],'范围、数值和建议相关，但差额重复表述，阅读负担仍在。'),
}
records=[]
for version,filename in [('baseline','baseline-live-network.json'),('candidate','final-live.json')]:
 run=json.loads((P/filename).read_text())
 for r in run['records']:
  cid=r['case_id'];layers={}
  if cid=='S03':
   layers={layer:{'scores':None,'status':'expected_unavailable_no_llm','note':'真实筛选范围内指标均无有效值，不生成洞察正确。'} for layer in ['raw_candidates','analysis_report','presentation']}
  else:
   for layer in ['raw_candidates','analysis_report','presentation']:
    if layer=='raw_candidates':item=(OLD if version=='baseline' else NEW_RAW)[cid]
    elif not r['analysis_report']:
     layers[layer]={'scores':None,'status':'not_generated','note':r['error']['code']};continue
    else:
     item=(OLD if version=='baseline' else NEW_SAVED)[cid]
     if version=='baseline' and cid=='S01' and layer=='presentation':
      item=([2,2,2,2,2,2,2],'独立旧规则层计算三条比较与比例，内容强于旧生成器；不是LLM能力。')
     if version=='baseline' and cid=='O03' and layer!='raw_candidates':
      item=([1,0,0,1,1,1,1],'多引用未被综合为已保存事实，解释中单位任务占用尚无计算证据。')
    scores=dict(zip('ABCDEFG',item[0]));layers[layer]={'scores':scores,'hard_fail':scores['A']==0 or scores['G']==0,'status':'reviewed','note':item[1]}
  records.append({'version':version,'case_id':cid,'split':r['split'],'layers':layers})
summary={}
for version in ['baseline','candidate']:
 summary[version]={}
 for split in ['development','holdout']:
  summary[version][split]={}
  for layer in ['raw_candidates','analysis_report','presentation']:
   rows=[r['layers'][layer] for r in records if r['version']==version and r['split']==split]
   scored=[r for r in rows if r['scores']]
   summary[version][split][layer]={'scored_cases':len(scored),'not_generated':sum(r['status']=='not_generated' for r in rows),
    'hard_failure_cases':sum(r.get('hard_fail',False) for r in scored),
    'dimension_means_among_scored_only':{k:round(sum(r['scores'][k] for r in scored)/len(scored),3) if scored else None for k in 'ABCDEFG'}}
output={'review_type':'agent_semantic_review_not_user_or_blind_human_acceptance','rubric':'frozen-rubric.json',
 'note':'No rubric changes after outputs. Layer scores separated; missing reports unscored and explicitly counted, never silently removed from reliability denominators. A/G zero are hard failures. Scores are ordinal judgments, not statistical proof.',
 'summary':summary,'records':records}
(P/'semantic-review.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
