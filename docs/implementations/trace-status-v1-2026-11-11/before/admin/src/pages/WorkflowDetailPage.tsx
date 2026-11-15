import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { RefreshCw, ChevronLeft, Check, CircleAlert, Clock3 } from 'lucide-react';
import { workflowApi } from '../api/workflows';
import type { WorkflowView, WorkflowObservation } from '../types/workflows';
import type { TraceSpan, Metadata } from '../types/traces';
import { BusinessBadge, CollectionBadge, FailureCard, Findings, InputSummary, QualityCard } from '../features/workflows/WorkflowShared';
import { TraceError } from '../features/traces/AccessPanel';
import { WorkflowBadCases } from '../features/badCases/BadCaseShared';
import { StatusBadge } from '../features/traces/TraceShared';
import { durationText, nodeLabels, timeText, valueText } from '../features/traces/presentation';

const names:Record<string,string>={...nodeLabels,analysis_engine:'分析执行',hitl:'人工审核',chart_builder:'图表构建'};
function ResultRefs({ attrs }: { attrs:Metadata }) {
  const refs=Object.fromEntries(['result_ref','report_id','approval_id','plan_version_id','dataset_id','dataset_version','operation_id','report_run_id'].filter(k=>attrs[k]!=null).map(k=>[k,attrs[k]]));
  return <dl className="wf-refs">{Object.entries(refs).map(([k,v])=><div key={k}><dt>{k}</dt><dd><code>{valueText(v)}</code></dd></div>)}{Array.isArray(attrs.result_refs)&&<div><dt>result_refs</dt><dd>{valueText(attrs.result_refs)}</dd></div>}{!Object.keys(refs).length&&<div><dt>result_ref</dt><dd>未采集独立结果引用；保留实际输出摘要。</dd></div>}</dl>;
}
function NodeEntry({ node,trace }: { node:TraceSpan; trace:WorkflowObservation }) {
  const attrs=node.attributes||{},events=trace.events.filter(e=>e.span_id===node.span_id),calls=trace.llm_calls.filter(c=>c.span_id===node.span_id);
  const same=trace.nodes.filter(n=>n.node_key===node.node_key);
  const reason=node.error_code||valueText(attrs.skip_reason);
  const icon=node.status==='complete'?<Check size={15}/>:node.status==='running'?<Clock3 size={15}/>:<CircleAlert size={15}/>;
  return <li id={'node-'+node.span_id} className={'wf-node wf-node-'+node.status} data-testid="workflow-node"><div className="wf-node-time"><time>{timeText(node.started_at)}</time><span className="wf-node-dot">{icon}</span></div><details className="wf-node-content" open={node.status==='failed'||node.status==='interrupted'}><summary><div className="wf-node-title"><strong>{names[node.name]||node.name}</strong><code>{node.node_key||'node_key 未采集'}</code><span>attempt #{node.node_attempt??'unknown'}</span></div><div className="wf-node-metrics"><StatusBadge status={node.status}/><span>{durationText(node.duration_ms)}</span><span>{calls.length} 条 LLM 调用</span></div></summary>
      <div className="wf-node-expanded"><dl className="wf-node-facts"><div><dt>started_at</dt><dd>{node.started_at||'未采集'}</dd></div><div><dt>ended_at</dt><dd>{node.finished_at||'未采集结束时间'}</dd></div><div><dt>reason_code</dt><dd>{reason}</dd></div><div><dt>span_id</dt><dd className="wf-id">{node.span_id}</dd></div></dl>
        {attrs.validation_role!=null&&<p>实际校验位置：<code>{String(attrs.validation_role)}</code></p>}
        <h3>输入摘要</h3><InputSummary attrs={attrs}/>
        <h3>结果引用</h3><ResultRefs attrs={attrs}/>
        <details><summary>实际输出摘要</summary><pre>{JSON.stringify(attrs,null,2)}</pre></details>
        <h3>事件记录 <small>{events.length} 条已采集</small></h3>{events.length?<ol className="wf-event-list">{events.map(e=><li key={e.event_id}><time>{timeText(e.recorded_at)}</time><code>{e.event_type}</code><pre>{JSON.stringify(e.payload||{},null,2)}</pre></li>)}</ol>:<p className="muted">没有可读取的事件，不据此推断节点没有运行。</p>}
        <h3>LLM 调用记录</h3>{calls.length?<ul className="wf-calls">{calls.map(c=><li key={c.call_id}><Link className="wf-link wf-id" to={'/prompts/calls/'+encodeURIComponent(c.call_id)}>{c.call_id}</Link><span>请求 #{c.call_sequence} · {c.status} · {durationText(c.duration_ms)}</span>{c.retry_index>0&&<span className="wf-warning">请求重试 #{c.retry_index}，前次：{c.retry_of_call_id||'引用未采集'}</span>}</li>)}</ul>:<p className="muted">0 条已采集调用；记录缺失不等于已确认未调用。</p>}
        {same.length>1&&<details><summary>相同 node_key 的实际重入记录（{same.length}）</summary><ul>{same.map(s=><li key={s.span_id}>attempt #{s.node_attempt??'unknown'} · {s.status} · {timeText(s.started_at)} · {s.span_id}</li>)}</ul><p className="muted">重复进入可能来自不同业务调用位置，不自动解释为失败重试。</p></details>}
      </div></details></li>;
}
function Association({ label,values }: { label:string; values:unknown[] }) {return <div><dt>{label}</dt><dd>{values.length?values.map((v,i)=><code className="wf-id" key={i}>{valueText(v)}</code>):<span className="muted">尚无通过校验的关联记录</span>}</dd></div>;}
export function WorkflowDetailPage() {
  const { workflowId='' }=useParams();
  const [view,setView]=useState<WorkflowView|null>(null),[error,setError]=useState<unknown>(null),[loading,setLoading]=useState(true),[refresh,setRefresh]=useState(0);
  useEffect(()=>{const controller=new AbortController();setView(null);setError(null);setLoading(true);workflowApi.get(workflowId,controller.signal).then(v=>{if(!controller.signal.aborted)setView(v);}).catch(e=>{if(!controller.signal.aborted)setError(e);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});return()=>controller.abort();},[workflowId,refresh]);
  const trace=view?.trace;
  return <div className="wf-page"><Link className="wf-back" to="/traces/workflows"><ChevronLeft size={15}/>Workflow 列表</Link><header className="wf-heading"><div><h1>Workflow 运行详情</h1><p className="wf-id">{workflowId}</p></div><button className="secondary-button" disabled={loading} onClick={()=>setRefresh(v=>v+1)}><RefreshCw size={15}/>手动刷新</button></header>
    {loading&&<p role="status">正在读取业务事实与实际节点…</p>}{error!=null&&<TraceError error={error} resource="Workflow 详情" retry={()=>setRefresh(v=>v+1)}/>}
    {view&&<><section className="wf-business-summary"><div><p className="wf-label">业务生命周期</p><BusinessBadge status={view.business_lifecycle.status}/><p>执行：{valueText(view.business_lifecycle.execution_status)}<br/>报告：{view.business_lifecycle.report_status||'尚无报告'} · {view.business_lifecycle.report_delivery==='delivered'?'已交付':view.business_lifecycle.report_delivery==='not_delivered'?'未交付':'交付尚无法判断'}</p><small>来源：Business DB。Root 与 Span 状态不会覆盖业务结论。</small></div><dl><div><dt>开始时间（Workflow 创建）</dt><dd>{timeText(view.created_at)}</dd></div><div><dt>业务更新时间</dt><dd>{timeText(view.updated_at)}</dd></div><div><dt>总耗时</dt><dd>{view.duration_ms==null?'缺少可靠终态时间':durationText(view.duration_ms)}</dd></div><div><dt>耗时口径</dt><dd>{view.duration_basis||'不估算未采集耗时'}</dd></div><div><dt>Trace 采集</dt><dd><CollectionBadge value={view.collection}/></dd></div></dl></section>
      {view.failure&&<FailureCard failure={view.failure}/>}
      {view.quality&&<QualityCard quality={view.quality}/>}
      <WorkflowBadCases view={view}/>
      <section className="wf-associations"><h2>业务与记录关联</h2><dl><Association label="Workflow" values={[view.workflow_id]}/><Association label="Session" values={[view.session_id]}/><div><dt>Root</dt><dd><code className="wf-id">{view.root_run_id}</code>{trace?.root?<Link className="wf-link" to={'/traces/'+encodeURIComponent(view.root_run_id)}>查看原始 Root Trace</Link>:<span className="muted">仅确认预留身份，物理 Root 暂不可读取</span>}</dd></div><Association label="PlanVersion" values={trace?.plan_versions.map(p=>p.plan_version_id)||[view.source_refs.plan_id].filter(Boolean)}/><Association label="Approval" values={trace?.approvals.map(a=>a.approval_id)||[view.source_refs.approval_id].filter(Boolean)}/><Association label="Execution / 结果引用" values={trace?.executions.map(e=>e.result_ref)||[view.source_refs.execution_id].filter(Boolean)}/><Association label="Report" values={trace?.reports.map(r=>r.report_id)||[view.source_refs.report_id].filter(Boolean)}/></dl><p className="muted">Root 原始状态属于准备阶段检查点；不作为全流程业务生命周期。</p></section>
      <section className="wf-timeline" aria-labelledby="timeline-heading"><header><div><h2 id="timeline-heading">生命周期时间线</h2><p>按真实开始时间排列，仅包含已持久化的实际 Span。</p></div><span>{trace?.nodes.length??0} 个实际 Span · {trace?.llm_calls.length??0} 条已采集 LLM 调用</span></header>{trace?.nodes.length?<ol className="wf-node-list">{trace.nodes.map(n=><NodeEntry key={n.span_id} node={n} trace={trace}/>)}</ol>:<div className="wf-empty"><h3>暂无可读取的实际节点</h3><p>业务结果仍展示在上方。节点缺席不能被自动解释为未执行。</p></div>}</section>
      {!!trace?.report_generations.length&&<section className="wf-report-attempts"><h2>报告尝试记录</h2><p className="muted">当前 ReportGeneration 与已保存的 Report Run 分开展示；不补造丢失的历史尝试。</p><dl className="wf-refs">{trace.report_generations.map((g,i)=><div key={i}><dt>当前 generation</dt><dd>{valueText(g.execution_id)} · attempt {valueText(g.attempt)} · {valueText(g.status)} · {valueText(g.report_id)}</dd></div>)}</dl><ul>{trace.report_artifact_runs.map((r,i)=><li key={i}><Link className="wf-link" to={'/traces/'+encodeURIComponent(String(r.run_id))}>{valueText(r.run_id)}</Link> · attempt {valueText(r.attempt)} · {valueText(r.status)}{r.error_code!=null&&<code>{String(r.error_code)}</code>}{r.retry_of_run_id!=null&&<small>真实重试来源：{String(r.retry_of_run_id)}</small>}</li>)}</ul></section>}
      <Findings view={view}/>
    </>}
  </div>;
}
