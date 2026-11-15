from pathlib import Path
import json,hashlib,statistics,collections,shutil
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');suite=root/'docs/evaluations/direction-first-acceptance-v1-2026-11-09';runs=suite/'runs/frozen-baseline-01'
def save(name,value):
 with (suite/name).open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2)
frozen=json.loads((suite/'frozen/manifest.json').read_text())['files']
freeze_ok=all(hashlib.sha256((suite/'frozen'/name).read_bytes()).hexdigest()==sha for name,sha in frozen.items())
source=json.loads((suite/'source-freeze.json').read_text());changed=[name for name,sha in source.items() if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha]
cases=json.loads((suite/'frozen/cases.json').read_text());records=[];bad=[];calls=[]
notes={
'S01':'核心筛选、销售额、城市、降序和Top3均匹配独立基准。比较证据充分，建议仍偏向通用核对。排名固定附带并列说明，容易误读。',
'S03':'4个方向与销售探索相关，实际计算均通过。报告有10条洞察，长小数和重复边界文案降低可读性；本轮未证明普通用户能独立理解。',
'S04':'缺少利润数据，保留P0不可执行计划，coverage=blocked且无执行记录。属于预期安全停止，不是报告成功。',
'R01':'城市计数与排序正确，数值可追溯。当前数据无岗位唯一标识，报告使用记录计数；不能泛化为已完成岗位实体去重。',
'R03':'模糊请求实际暂停澄清；补充后在同一Workflow继续，生成正确城市计数和报告。',
'T01':'均值计算正确，7个非空响应值参与。重复极值候选被正确拒绝，报告保留2条洞察但标partial。排名按数值高低而非响应越快越好，易造成业务误读。',
'P02':'只保留已完成且非丙项目，甲16、乙36、合计52与独立基准一致。建议与解释偏模板化。',
'P03':'3个方向有业务相关性，10个指标实际计算通过。差值证据被选为集中度主证据，校验正确拒绝；报告partial/coverage partial，任务数指标对应候选未进入报告。使用显著差异措辞但操作只有描述统计，不应理解为统计显著性已验证。',
'R05':'4个方向可计算且相关，但最终仅城市和学历有文字发现；薪资和岗位名称有图表无解读，也未作为未完成方向披露。系统complete不等于方向解读完整。',
'T05':'4个方向可计算。工单数量差值证据被当作集中度主证据，校验正确拒绝。优先级/状态、月度方向无文字解读，未完成任务列表为空。业务问题含显著差异、处理进度优于，现有链路未验证显著性或绩效优劣。',
}
for case in cases:
 cid=case['case_id'];d=runs/cid;r=json.loads((d/'result.json').read_text());trace=json.loads((d/'workflow-trace.json').read_text());cs=json.loads((d/'llm-calls.json').read_text());calls.extend(cs)
 report=json.loads((d/'analysis-report.json').read_text()) if (d/'analysis-report.json').exists() else None
 nodes=trace['nodes'];root_id=r['root_run_id'];span_ids={n['span_id'] for n in nodes}
 trace_checks={'http_ok':r['trace_http_status']==200,'single_root':all(n['run_id']==root_id for n in nodes),'direct_root_spans':all(n['parent_span_id'] is None for n in nodes),'calls_bound':all(c['run_id']==root_id and c['span_id'] in span_ids for c in cs),'collection_observed':trace['collection']['status']=='observed','all_finished':all(n.get('finished_at') for n in nodes)}
 system_status=report['report_status'] if report else 'expected_stop' if r.get('expected_stop') else r['status']
 missing=sorted(set(report['execution_metadata'])-{i['task_id'] for i in report['insights']}) if report else []
 defects=[]
 if report:
  first=next(iter(report['execution_metadata'].values()),{})
  for rejection in first.get('rejected_insights',[]):
   primary=next(e for e in report['evidence'] if e['evidence_id']==rejection['primary_evidence_id']);batch=rejection.get('batch_index',1)
   candidates=[]
   report_responses=[]
   for file in sorted(d.glob('http-*-response.json')):
    try:raw=json.loads(json.loads(file.read_text())['text'])
    except (ValueError,KeyError):continue
    if 'insights' in raw:report_responses.append((file,raw))
   chosen_file,raw=report_responses[batch-1];choice=raw['insights'][rejection['candidate_index']]
   span=next(n for n in nodes if n['node_key']=='fact_validator' and n['node_attempt']==batch)
   item={'case_id':cid,'user_goal':case['query'],'workflow_id':r['workflow_id'],'root_run_id':root_id,'span_id':span['span_id'],'node_key':'fact_validator','rule_id':rejection['error_code'],'candidate':choice,'primary_evidence':primary,'raw_response':str(chosen_file.relative_to(suite)),'classification':'duplicate_candidate' if rejection['error_code']=='REPORT_DUPLICATE_FINDING' else 'invalid_finding_type','false_positive_observed':False,'basis':'Primary difference evidence is not a concentration fact; or extreme fact duplicates previously selected ranking evidence. Safety check is justified; do not disable it.'}
   bad.append(item);defects.append(rejection['error_code'])
  if missing:bad.append({'case_id':cid,'workflow_id':r['workflow_id'],'classification':'direction_explanation_gap','task_ids':missing,'system_report_status':report['report_status'],'uncompleted_tasks':report['uncompleted_tasks'],'basis':'Actual successful directions have charts/results but no selected Insight or explicit missing-interpretation disclosure.'})
 records.append({'case_id':cid,'domain':case['domain'],'query':case['query'],'kind':case['kind'],'system_delivery_status':system_status,'execution_status':r.get('execution_status'),'goal_coverage':r.get('goal_coverage'),'workflow_id':r['workflow_id'],'root_run_id':root_id,'execution_id':r.get('execution_id'),'report_id':r.get('report_id'),'elapsed_seconds':r['elapsed_seconds'],'span_count':len(nodes),'llm_call_count':len(cs),'trace_checks':trace_checks,'collection':trace['collection'],'automated_checks':r['checks'],'direction_ids_without_insight':missing,'reject_rule_ids':defects,'agent_review_note':notes[cid],'ordinary_user_review':'not_performed','raw_result_status':r['status']})
 counts=dict(collections.Counter(r['system_delivery_status'] for r in records))
 node_times={}
for c in calls:node_times.setdefault(c['node_id'],[]).append(c['duration_ms']/1000)
summary={'requirement':'REQ-0103','overall_verdict':'not_accepted_as_complete_mvp','system_delivery_counts':counts,'execution_success_count':sum(r['execution_status']=='success' for r in records),'independent_calculation_pass_count':sum(r['automated_checks'].get('calculation',False) for r in records),'normal_case_approval_blocks':0,'llm_call_count':len(calls),'llm_call_statuses':dict(collections.Counter(c['status'] for c in calls)),'actual_http_request_count':sum(len(list((runs/c['case_id']).glob('http-*-request.json'))) for c in cases),'retry_records':sum(c['retry_index']>0 for c in calls),'call_latency_seconds':{node:{'count':len(v),'median':round(statistics.median(v),3),'min':round(min(v),3),'max':round(max(v),3)} for node,v in node_times.items()},'trace_checks_pass':all(all(r['trace_checks'].values()) for r in records),'source_unchanged':not changed,'changed_source_files':changed,'frozen_inputs_verified':freeze_ok,'ordinary_user_trial':'not_performed','direction_interpretation_gap_cases':[r['case_id'] for r in records if r['direction_ids_without_insight']],'limits':['Single round; small synthetic datasets; not statistical reliability estimate.','Historical inputs reused; R05/T05 new requests are not a blinded holdout.','Backend API TestClient + real HTTP model, isolated SQLite/files; not browser-operated 10-case user trial.','No product change, no outer retries, no safety validator relaxed.','Isolated run records are not injected into the currently running production Admin database.']}
save('case-review.json',records);save('bad-cases.json',bad);save('summary.json',summary)
save('trace-correlation.json',[{'case_id':r['case_id'],'workflow_id':r['workflow_id'],'root_run_id':r['root_run_id'],'checks':r['trace_checks'],'nodes':json.loads((runs/r['case_id']/'workflow-trace.json').read_text())['nodes']} for r in records])
print(json.dumps(summary,ensure_ascii=False,indent=2))
