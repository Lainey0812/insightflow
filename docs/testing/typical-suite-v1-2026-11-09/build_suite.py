"""Create frozen synthetic software-test fixtures; never reads production data or calls LLMs."""
import csv
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent


def save_json(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def fixture(name, headers, rows, preamble=()):
    with (ROOT / 'data' / name).open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerows(preamble)
        writer.writerow(headers)
        writer.writerows(rows)


def main():
    (ROOT / 'data').mkdir(exist_ok=True)
    sales = [
        ['S01','2026-01-05','华东','济南','已完成',10000],
        ['S02','2026-02-05','华东','济南','已完成',11250],
        ['S03','2026-01-10','华东','南京','已完成',12000],
        ['S04','2026-02-10','华东','南京','已完成',8250],
        ['S05','2026-01-15','华东','上海','已完成',5760],
        ['S06','2026-02-15','华东','杭州','已完成',2740],
        ['S07','2026-01-20','华东','上海','已取消',90000],
        ['S08','2026-01-20','华北','北京','已完成',80000],
        ['S09','2025-12-31','华东','济南','已完成',70000],
        ['S10','2027-01-01','华东','南京','已完成',60000],
    ]
    fixture('sales.csv',['订单编号','订单日期','地区','城市','订单状态','销售额'],sales)
    fixture('sales_quality.csv',['订单编号','城市','销售额'],[
        ['Q01','济南',100],['Q02','济南',''],['Q03','南京',200],
        ['Q03','南京',200],['Q04','上海',0],['Q05','杭州',-50],
    ])
    jobs = [
        ['J01','上海','AI产品经理','1-3年','20-30K'],
        ['J02','北京','AI 产品经理','3-5年','30-40K'],
        ['J03','上海','ai产品经理（Agent方向）','1-3年','25-35K'],
        ['J04','深圳','高级AI产品经理','5年以上','40-50K'],
        ['J05','杭州','AI产品经理','1-3年','20-30K'],
        ['J06','北京','AIGC产品经理','3-5年','30-40K'],
        ['J07','上海','数据分析师','1-3年','15-25K'],
        ['J08','深圳','AI产品经理（B端）','3-5年','25-35K'],
    ]
    h=['岗位编号','城市','岗位名称','经验要求','薪资区间']
    fixture('recruitment.csv',h,jobs)
    fixture('recruitment_header6.csv',h,jobs,
        [['合成招聘测试数据'],['不含真实个人信息'],['说明行三'],['说明行四'],['说明行五']])
    fixture('tickets.csv',['工单编号','类别','状态','响应分钟'],[
        ['T01','技术','已解决',10],['T02','技术','处理中',30],['T03','技术','已解决',80],
        ['T04','咨询','已解决',10],['T05','咨询','处理中',20],['T06','咨询','已解决',30],
    ])
    fixture('projects.csv',['任务编号','团队','状态','实际工时'],[
        ['P01','运营','已完成',4],['P02','运营','已完成',6],['P03','研发','已完成',8],
        ['P04','研发','已完成',12],['P05','运营','进行中',100],['P06','研发','进行中',200],
    ])
    cases=[]
    def case(i,title,file,query,expected,*,mode='browser',header=1,actions=None,limits=None):
        cases.append({'case_id':f'TC{i:02d}','title':title,'test_mode':mode,
            'dataset':'data/'+file,'header_row':header,'user_query':query,
            'actions':actions or ['新建咨询，上传指定文件并填写指定表头行。','复制本例需求并提交。','核对意图、计划和约束；仅在满足本例条件时批准。','按本例预期检查业务记录、报告和Admin。'],
            'expected':expected,'safety_boundaries':limits or [],'execution_status':'not_run'})
    case(1,'销售多筛选、排名与Top 3','sales.csv',
        '分析2026年华东地区已完成订单的销售额，按城市求和并降序排名，取前三名。',
        {'intent':'goal_driven / proceed','target_rows':6,'result':[['济南',21250],['南京',20250],['上海',5760]],
         'top3_total':47260,'full_filtered_total':50000,'plan':'所有时间、地区、订单状态在聚合前生效；城市分组、sum销售额、降序、Top3。'},
        limits=['不得将前三名合计称为华东总体。','前两名占前三名87.8%，占完整筛选总体83.0%；只能引用已生成对应证据的比例。'])
    case(2,'明确排除条件','sales.csv',
        '只分析2026年华东地区已完成订单，排除上海，按城市汇总销售额并降序排名。',
        {'target_rows':5,'result':[['济南',21250],['南京',20250],['杭州',2740]],'total':44240},
        limits=['不能把排除上海反转为只看上海。','不额外增加利润、客户画像分析。'])
    case(3,'日期派生与月份顺序','sales.csv',
        '分析2026年华东地区已完成订单，按订单日期的月份汇总销售额，按月份升序。',
        {'target_rows':6,'result':[[1,27760],[2,22240]],'total':50000,
         'feasibility':'若使用extract_month前置派生，应为合法F1操作链；不得使用未支持时间函数。'},
        limits=['只覆盖2026年，不得混入2025或2027。','变化率只有确定性Evidence支持才可展示。'])
    case(4,'缺失、重复、零值与负值','sales_quality.csv',
        '统计城市销售额总和；缺失金额不参与求和，重复记录保留，零值和负值保留，不做自动清洗。',
        {'uploaded_rows':6,'missing_cells':1,'duplicate_rows':1,'amount_non_null_rows':5,
         'result':[['南京',400],['济南',100],['上海',0],['杭州',-50]],'total':450},
        limits=['不把一个缺失单元格写成一条全局无效数据。','不静默删除重复行、零值或负值。'])
    case(5,'筛选后零记录','sales.csv',
        '只统计2024年的订单，按城市汇总销售额。',
        {'target_rows':0,'engine':'空结果不应自动作为执行错误。','report':'无有效证据时明确不可生成/无可分析数据，不调用LLM编造洞察。'},
        limits=['不得自动改成2026年或取消时间条件。'])
    case(6,'招聘开放探索','recruitment.csv',
        '帮我探索这份招聘数据的主要特征，不限定岗位名称，不分析薪资，也不要给个人求职决策建议。',
        {'intent':'exploratory / proceed','uploaded_rows':8,'reference_city_counts':{'上海':3,'北京':2,'深圳':2,'杭州':1},
         'plan':'允许不同但相关的探索方向；核心P0需人工审阅，不固定任务数。','decision_goal':None},
        limits=['无薪资分析任务。','不把数据样本当作整个招聘市场。','不能自行推断用户职业或投递决策。'])
    case(7,'表头第6行与岗位名称变体范围确认','recruitment_header6.csv',
        '统计AI产品经理岗位的城市分布。',header=6,
        expected={'uploaded_rows':8,'exact_rows':2,'normalized_contains_rows':6,
          'variant_result':{'上海':2,'北京':1,'深圳':2,'杭州':1},'distinct_matched_names':5,
          'review':'若范围不明确，必须保留阻断；用户明确确认包含变体后才可生成新版本。'},
        actions=['新建咨询，上传文件，指定表头行为6。','提交需求；检查含空格、大小写和括号的名称是否被遗漏。',
          '若出现范围确认，选择包含名称变体，预览应匹配6/8条、5种名称；保存并重新审核。',
          '若系统已形成明确范围计划，逐项核对枚举值；没有入口时记录unsupported，不手工篡改数据库。',
          '确认旧版保留、新版重新校验，最终批准前不得执行。'],
        limits=['字面匹配不能自动纳入AIGC产品经理或数据分析师。','填5应明确表头/结构异常，不得自动猜成第6行。'])
    case(8,'不支持的薪资区间均值','recruitment.csv',
        '按城市比较薪资区间的平均值，必须计算平均薪资。',
        {'intent':'goal_driven','review':'缺少可计算的薪资数值/区间解析能力，核心任务保留F0或先澄清；不能完整可执行。'},
        limits=['不得对20-30K等字符串直接avg。','不能把岗位计数冒充薪资均值。'])
    case(9,'模糊请求与澄清恢复','projects.csv','帮我处理一下。',
        {'initial_intent':'undetermined / clarify','initial_plan':'无可审批计划，不进入Engine。',
         'clarification_reply':'按团队统计已完成任务数量。','after_reply':{'运营':2,'研发':2}},
        actions=['上传文件并提交模糊请求。','核对澄清问题，不应先执行分析。','在原会话补充：按团队统计已完成任务数量。','检查同Workflow关联保留；审核并执行，核对各团队2条。'])
    case(10,'指标完整性与否定边界','tickets.csv',
        '按类别比较响应分钟的平均值，按平均响应分钟降序；不要求计算中位数，不做因果解释。',
        {'intent':'goal_driven / proceed','result':[['技术',40],['咨询',20]],
         'constraints':'平均响应分钟属于metric_requirements；降序属于analysis_limits；不要求中位数为非必选，不是禁止。'},
        limits=['不得把未要求的中位数增加为核心目标。','不声称技术类别导致响应慢。'])
    case(11,'缺失核心业务指标','sales.csv','按城市比较利润总额，找出利润最高的城市。',
        {'review':'数据没有利润或成本字段，核心任务保留并披露缺口；无相关可执行核心任务时blocked。'},
        limits=['不能用销售额冒充利润。','不能自动捏造成本、利润率或转换规则。'])
    case(12,'项目工时聚合与计数口径','projects.csv',
        '只看已完成任务，按团队统计任务数量及实际工时总和；每行算一个任务，不去重。',
        {'target_rows':4,'result':[{'团队':'运营','任务数量':2,'工时总和':10},{'团队':'研发','任务数量':2,'工时总和':20}]},
        limits=['计数为count rows，工时为sum，不混用。','不从工时总和判断人员绩效或效率。'])
    case(13,'HITL修改、删除与旧审批失效','sales.csv',
        '先统计2026年华东已完成订单的整体销售额，并补充按城市汇总销售额，取前三名。',
        {'overall':50000,'initial_top_n':3,'edited_top_n':2,'edited_result':[['济南',21250],['南京',20250]],
         'required':'新计划版本重新校验，旧审批不能执行新版；批准前无Execution。'},
        actions=['提交需求，检查整体与城市两个业务方向。','若没有可安全删除的非核心任务，记录该分支not_applicable，不强删核心任务。',
          '通过已有表单将城市Top3改为Top2，保存新版本并重新审核；若产品不允许该编辑，记录缺口。',
          '若有非必要任务，删除后再次检查版本、目标覆盖和校验结果。','隔离API测试：尝试旧版本批准/执行，必须拒绝；不要向实际用户会话伪造审批。',
          '批准当前合法版本后执行，检查前两名合计41500。'])
    case(14,'报告模型失败不丢执行结果','sales.csv',
        '统计2026年华东已完成订单的销售额总和。',mode='isolated_fault_injection',
        expected={'engine_total':50000,'engine_status':'success','report':'明确failed或有真实依据的降级状态，不伪造LLM成功。',
          'persistence':'ExecutionResult仍可查询；若现有规则允许Retry，恢复后新report_attempt保留历史。'},
        actions=['必须在独立临时存储与测试Provider配置中进行，不停止共享后端或修改真实API Key。','先正常完成Intent/Planner与人工审批。',
          '仅在报告Insight Generator HTTP边界注入timeout或明确失败；不得让准备阶段先失败。','核对Engine成功、报告失败分离、错误节点/Call、结果仍可查询。',
          '仅对当前产品已支持的Retry执行恢复，不宣称unavailable支持重试。'],
        limits=['这是受控故障测试，不是真实模型质量评测；注入故障必须标记。'])
    case(15,'Trace故障与业务成功分离','projects.csv',
        '按团队统计已完成任务数量。',mode='isolated_fault_injection',
        expected={'result':{'运营':2,'研发':2},'business':'在仅Trace故障、其余依赖正常时保持正常业务结果。',
          'admin':'业务可读，collection gap明确；不得补造Span或反推Trace成功。'},
        actions=['使用隔离临时Business DB/Trace DB/Registry，保留正常模型或明确测试Provider。','仅让Trace写入不可用；不要同时破坏Prompt Registry。',
          '完成准备、审批、执行、报告；读取业务记录和Admin只读聚合。','核对结果与采集缺口；恢复Trace后不得补造未采集的历史Span。'],
        limits=['Trace fail-open与Registry fail-closed不同。','不得关闭生产Trace数据库或修改真实历史。'])
    save_json(ROOT/'cases.json',{'suite_version':'typical-suite-v1','created_at':'2026-11-09','data_source':'synthetic','cases':cases})
    (ROOT/'CASES.md').write_text('# 15例测试操作手册\n\n所有数据均为合成测试数据，尚未运行产品或真实LLM。\n\n'+ '\n\n'.join(
        f"## {c['case_id']}：{c['title']}\n\n文件：`{c['dataset']}`；表头行：{c['header_row']}；执行方式：{c['test_mode']}。\n\n需求（可直接复制）：\n\n> {c['user_query']}\n\n操作：\n\n"+
        '\n'.join(f'{i+1}. {x}' for i,x in enumerate(c['actions']))+'\n\n预期：\n\n```json\n'+json.dumps(c['expected'],ensure_ascii=False,indent=2)+'\n```\n\n边界：\n\n'+('\n'.join('- '+x for x in c['safety_boundaries']) or '- 遵守本套件统一验收规则。') for c in cases)+'\n')
    with (ROOT/'results-template.csv').open('x',encoding='utf-8-sig',newline='') as handle:
        w=csv.writer(handle);w.writerow(['case_id','测试状态','日期','workflow_id','root_run_id','session_id','plan_version','execution_id','report_id','prompt_snapshot_ids','实际结果','失败阶段','reason_code','证据路径','备注'])
        for c in cases:w.writerow([c['case_id'],'not_run']+['']*13)


if __name__=='__main__':
    main()
