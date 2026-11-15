"""Freeze inputs and scoring protocol BEFORE any generator modifications. No LLM calls."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'backend/tests')]
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.intent import ParsedIntent
from app.planning.validator import PlanValidator
from app.planning.capabilities import CapabilityRegistry
from report_fixtures import report_case
from planning_fixtures import step, task
from intent_fixtures import intent_payload


def group(dimension, field=None, function='sum', alias='value', top=None):
    steps = [step('group_aggregate', {'dimensions':[dimension], 'metrics':[
        {'function':function, **({'field':field} if field else {}), 'alias':alias}]})]
    if top:
        steps.append(step('top_n', {'field':alias, 'direction':'desc', 'n':top}, 'S02'))
    return steps


def candidate(steps, question, tid='A01', priority='P0'):
    result=task(steps, tid, priority)
    result.update(title=question, business_question=question)
    return result


cases=[]
def add(cid, domain, query, raw, tasks, *, split='development', failures=(), missing=False, important=('difference',), note=''):
    i,v,x,p=report_case(tasks,raw.encode(),failures=failures,null_metrics=missing)
    i=ParsedIntent.model_validate(intent_payload(business_goal=query,analysis_object=domain+'数据'))
    data=v.plan.model_dump();data['core_requirements'][0]['description']=query
    v=PlanValidator(CapabilityRegistry()).validate(data,p);v.intent_snapshot=i
    p.file_name=domain+'.csv'
    # Correct business metric labels in the generic kernel fixture; values remain actual kernel results.
    fields={f.field_id:f.display_name for f in p.fields}
    for executed in x.tasks:
        if not executed.result:continue
        planned=next(t for t in v.plan.tasks if t.task_id==executed.task_id)
        metrics={m['alias']:m for s in planned.steps if s.operation in {'aggregate','group_aggregate'} for m in s.params['metrics']}
        for col in executed.result.columns:
            if col.field in metrics:
                m=metrics[col.field];name=fields.get(m.get('field'),'记录')
                col.label=name+' · '+{'sum':'合计','count':'数量','avg':'平均值','median':'中位数'}[m['function']]
                col.unit='条' if m['function']=='count' else None
        executed.scope=query+'；仅限当前上传数据与批准任务范围。'
    cases.append({'case_id':cid,'domain':domain,'split':split,'query':query,'note':note,
        'expected':{'important_families':list(important),'unsupported_business_claims_allowed':False,
                    'no_valid_evidence':missing,'failed_tasks':list(failures)},
        'input':{'intent':i.model_dump(mode='json'),'validated':v.model_dump(mode='json'),
                 'execution':x.model_dump(mode='json'),'profile':p.model_dump(mode='json')}})


# Exact previously saved real sales execution, not synthetic expected rows.
old=ROOT/'docs/evaluations/report-workflow-v1'
snap=json.loads((old/'fresh-workflow-approved-snapshot.json').read_text())
sess=json.loads((old/'fresh-workflow-session.json').read_text())
cases.append({'case_id':'S01','domain':'sales','split':'development','query':'分析2026年华东地区已完成订单销售额，按城市降序取前三名',
    'note':'Saved real Engine execution and real approval; source CSV 60 rows, effective 16.',
    'expected':{'important_families':['difference','relative_lead','relative_ratio','returned_concentration'], 'unsupported_business_claims_allowed':False,'no_valid_evidence':False,'failed_tasks':[]},
    'input':{'intent':snap['intent'],'validated':snap['validated_plan'],
        'execution':json.loads((old/'fresh-workflow-execution.json').read_text()),'profile':sess['profile'],
        'approved_snapshot':snap,'original_query':sess['user_goal']}})
add('S02','sales','比较各渠道销售额和订单数量，不判断利润', '渠道,销售额\n线上,100\n线上,200\n线下,280\n合作,60\n',[
    candidate(group('field_0001','field_0002'), '各渠道销售额'),
    candidate(group('field_0001',function='count',alias='orders'),'各渠道订单数量','A02')])
add('R01','recruiting','比较城市岗位数量取前三名，不依据岗位数判断薪资或录用机会',
    '城市,岗位\n上海,产品\n上海,研发\n上海,设计\n北京,产品\n北京,研发\n杭州,产品\n成都,研发\n',
    [candidate(group('field_0001',function='count',top=3),'城市岗位数量前三名')])
add('R02','recruiting','比较不同发布日期的岗位数量变化，不能外推市场趋势',
    '发布日期,岗位\n2026-01-01,产品\n2026-02-01,产品\n2026-02-01,研发\n2026-03-01,产品\n2026-03-01,设计\n2026-03-01,研发\n',
    [candidate(group('field_0001',function='count'),'不同发布日期岗位数量变化')], important=('change_rate',))
add('C01','support','比较不同工单类别的平均响应分钟，不能认定坐席效率或原因',
    '类别,响应分钟\n投诉,30\n投诉,50\n咨询,10\n咨询,14\n退款,25\n',
    [candidate(group('field_0001','field_0002','avg'),'工单类别平均响应分钟')])
add('C02','support','比较渠道的平均处理分钟，并说明缺失值限制',
    '渠道,处理分钟\n在线,10\n在线,\n电话,30\n电话,20\n邮件,\n',
    [candidate(group('field_0001','field_0002','avg'),'渠道平均处理分钟与数据缺失')])
add('O01','operations','比较各日期的已完成任务数量变化，不判断项目健康程度',
    '日期,状态\n2026-01-01,完成\n2026-02-01,完成\n2026-02-01,完成\n2026-03-01,完成\n',
    [candidate(group('field_0001',function='count'),'各日期已完成任务数量变化')],important=('change_rate',))
add('O02','operations','比较项目完成任务数及利润，缺少利润数据时必须披露',
    '项目,任务\n甲,发布\n甲,测试\n乙,发布\n',[
    candidate(group('field_0001',function='count'),'项目完成任务数'),
    candidate([step('aggregate',{'metrics':[{'function':'sum','field':'missing_profit','alias':'profit'}]})],'项目利润','A02')],
    failures=('A02',),note='Unsupported P0 is retained; never manufacture profit or full goal coverage.')
add('S03','sales','分析销售额，指标均缺失时不能生成结论','城市,销售额\n甲,\n乙,\n',
    [candidate([step('aggregate',{'metrics':[{'function':'count','alias':'n'}]})],'缺失指标报告')],missing=True,important=())
add('R03','recruiting','比较城市岗位数量，存在并列时不编造唯一名次','城市,岗位\n甲,研发\n乙,研发\n丙,研发\n',
    [candidate(group('field_0001',function='count',top=3),'城市岗位数量与并列')],important=())
add('C03','support','比较渠道净变化值，负值不生成无意义占比','渠道,净变化\n在线,10\n电话,0\n邮件,-5\n',
    [candidate(group('field_0001','field_0002'),'渠道净变化')],important=('difference',))
add('O03','operations','比较各项目投入工时与任务数量，不据此断定效率', '项目,工时\n甲,8\n甲,12\n乙,30\n丙,5\n',[
    candidate([step('group_aggregate',{'dimensions':['field_0001'],'metrics':[
        {'function':'sum','field':'field_0002','alias':'hours'},{'function':'count','alias':'tasks'}]})],'项目工时与任务数量')])
# Independent holdout: frozen now; no prompt examples use these values or recommendations.
add('H01','recruiting','比较岗位类型数量的结构，不判断招聘成功率','类型,岗位\n算法,甲\n算法,乙\n算法,丙\n算法,丁\n产品,戊\n产品,己\n设计,庚\n',
    [candidate(group('field_0001',function='count'),'岗位类型数量结构')],split='holdout')
add('H02','support','比较服务组工单数量前三名，不能当作整体客户占比','服务组,工单\n红组,1\n红组,2\n红组,3\n红组,4\n蓝组,5\n蓝组,6\n绿组,7\n黄组,8\n',
    [candidate(group('field_0001',function='count',top=3),'服务组工单数量前三名')],split='holdout')
add('H03','operations','比较批次耗时的小额差异，不据此确定瓶颈原因','批次,耗时\n早批,0.003\n午批,0.0029\n晚批,0.0004\n',
    [candidate(group('field_0001','field_0002'),'批次耗时比较')],split='holdout')
add('H04','sales','只比较北区已完成销售额，不分析利润，不能把返回两名当作全区','区域,状态,城市,销售额\n北区,完成,青岛,140\n北区,完成,天津,120\n北区,完成,太原,30\n南区,完成,广州,999\n北区,取消,青岛,999\n',[
    candidate([step('filter',{'conditions':[{'field':'field_0001','operator':'eq','value':'北区'},{'field':'field_0002','operator':'eq','value':'完成'}]}),
        step('group_aggregate',{'dimensions':['field_0003'],'metrics':[{'function':'sum','field':'field_0004','alias':'sales'}]},'S02'),
        step('top_n',{'field':'sales','direction':'desc','n':2},'S03')],'北区已完成销售额前两名')],split='holdout')

protocol={'version':'insight-quality-v1.1-frozen-2026-10-28','case_count':len(cases),
 'layers':['raw_candidates','analysis_report','presentation'],
 'scores':{
  'A':{'name':'事实准确性','0':'虚构/错误数值、名次、对象或口径','1':'未发现错误但事实或来源表达不完整','2':'事实与真实证据和范围逐项一致','hard_fail':True},
  'B':{'name':'重要证据利用','0':'遗漏核心证据','1':'只选排名/单值或部分重要比较','2':'合理选用目标相关比较/变化/结构证据'},
  'C':{'name':'多证据深度','0':'单值复述','1':'单项比较或并列复述','2':'相关证据综合为非重复发现'},
  'D':{'name':'业务相关','0':'偏离或增加未要求核心目标','1':'基本相关但泛化','2':'直接回应当前问题并披露未覆盖要求'},
  'E':{'name':'建议关联','0':'无关/未执行写成结论','1':'通用继续核查','2':'与具体发现相连且提出可验证后续动作'},
  'F':{'name':'用户可读','0':'难懂/技术术语主导','1':'可读但模板化/冗余','2':'对象和指标清楚、简洁易懂'},
  'G':{'name':'安全边界','0':'无依据因果/利润/经营判断、TopN总体误读','1':'无明显越界但限制表达不足','2':'范围和解释边界明确','hard_fail':True}},
 'aggregation':'按层分别报告；A/G=0即硬失败；不以总分抵消。调用或生成失败单列，不填成功报告分数。',
 'review':'自动引用/数值/来源检查与代理逐例语义审阅分别记录；代理审阅不称用户人工验收。',
 'metrics':{'important_evidence_utilization':'引用重要证据家族数/冻结期望家族数；仅作用于有该家族证据的非空案例，同时报告覆盖数',
  'multi_evidence':'每条至少两个不重复事实来源；仅加refs不算综合，最终报告须实际表达',
  'reliability':'真实返回/真实调用；保存报告成功/预期可生成案例；失败不从质量分母中静默剔除'},
 'holdout_policy':'H01-H04在本次优化前冻结；不用于修改Prompt示例/阈值；首次运行后即成为已见回归，不能再称独立未见。'}

target=OUT/'frozen-inputs.json'
if target.exists():raise SystemExit('Refusing to overwrite frozen inputs')
OUT.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
(OUT/'frozen-rubric.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
manifest={}
for path in [*list((ROOT/'backend/app/reporting').glob('*.py')),ROOT/'backend/app/services/analysis_report.py',ROOT/'backend/app/domain/analysis_report.py',ROOT/'backend/app/domain/report_presentation.py']:
    rel=path.relative_to(ROOT);content=path.read_bytes();dest=OUT/'baseline-source'/rel
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content);manifest[str(rel)]=hashlib.sha256(content).hexdigest()
for name in ['frozen-inputs.json','frozen-rubric.json']:
    manifest[name]=hashlib.sha256((OUT/name).read_bytes()).hexdigest()
protected=['backend/app/services/analysis_engine.py','backend/app/services/analysis_planner.py','backend/app/services/plan_review.py','backend/app/planning/validator.py','backend/app/workflow/orchestrator.py']
(OUT/'protected-sha256.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in protected},indent=2)+'\n')
(OUT/'freeze-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Frozen',len(cases),'cases, four domains, four holdout cases and A–G rubric before implementation.')
