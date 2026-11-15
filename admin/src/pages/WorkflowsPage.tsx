import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { workflowApi } from '../api/workflows';
import type { WorkflowPage } from '../types/workflows';
import { BusinessBadge, CollectionBadge, failureLabels } from '../features/workflows/WorkflowShared';
import { TraceError } from '../features/traces/AccessPanel';
import { durationText, timeText } from '../features/traces/presentation';

export function WorkflowsPage() {
  const [params,setParams]=useSearchParams();
  const [page,setPage]=useState<WorkflowPage|null>(null),[error,setError]=useState<unknown>(null),[loading,setLoading]=useState(true),[refresh,setRefresh]=useState(0);
  const size=Number(params.get('limit')||20), start=Number(params.get('offset')||0);
  const limit=Number.isInteger(size)&&size>=1&&size<=100?size:20, offset=Number.isInteger(start)&&start>=0&&start<=1000000?start:0;
  const query=new URLSearchParams({limit:String(limit),offset:String(offset)});
  const key=query.toString();
  useEffect(()=>{const controller=new AbortController();setLoading(true);setError(null);setPage(null);
    workflowApi.list(key,controller.signal).then(v=>{if(!controller.signal.aborted)setPage(v);}).catch(e=>{if(!controller.signal.aborted)setError(e);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();},[key,refresh]);
  function move(value:number){const next=new URLSearchParams(params);next.set('offset',String(value));setParams(next);}
  return <div className="wf-page"><header className="wf-heading"><div><h1>Workflow</h1><p>每次分析一条记录。点查看详情进入节点图。</p></div><button className="secondary-button" onClick={()=>setRefresh(v=>v+1)} disabled={loading}><RefreshCw size={15}/>手动刷新</button></header>
    <div className="wf-readonly">只读监控。不提供执行、重试或恢复操作。</div>
    {loading&&<p role="status" className="wf-loading">正在读取业务与观测记录…</p>}
    {error!=null&&<TraceError error={error} retry={()=>setRefresh(v=>v+1)} resource="Workflow 运行"/>}
    {!loading&&page&&<><div className="wf-table-top"><strong>{page.total} 条真实 Workflow</strong><span>按创建时间倒序，ID 稳定排序</span></div>{page.items.length ? <div className="wf-table-scroll"><table className="wf-table"><thead><tr><th>Workflow / Session</th><th>业务生命周期</th><th>开始 / 业务更新时间</th><th>总耗时</th><th>Trace 采集</th><th>异常</th><th>质量提示</th><th>详情</th></tr></thead><tbody>{page.items.map(item=><tr key={item.workflow_id}><td><code className="wf-id">{item.workflow_id}</code><code className="wf-subid">{item.session_id}</code></td><td><BusinessBadge status={item.business_lifecycle.status}/></td><td><time>{timeText(item.created_at)}</time><small>{timeText(item.updated_at)}</small></td><td title={item.duration_basis||'缺少可靠的结束时间'}>{item.duration_ms==null?'尚无可靠值':durationText(item.duration_ms)}</td><td><CollectionBadge value={item.collection}/></td><td>{item.failure?<span className="wf-warning">{failureLabels[item.failure.category]}<code className="wf-subid">{item.failure.node_name?item.failure.node_name+' / ':''}{item.failure.code}</code></span>:item.has_exception?<span className="wf-warning">需要查看</span>:<span className="muted">无已知异常</span>}</td><td>{!item.quality?<span className="muted">—</span>:item.quality.attention_count?<span className="wf-warning" title={item.quality.signals.filter(s=>s.level==='attention').map(s=>s.label).join('、')}>{item.quality.attention_count} 项需关注</span>:<span className="muted">无</span>}</td><td><Link className="wf-link" to={'/traces/workflows/'+encodeURIComponent(item.workflow_id)}>查看详情</Link></td></tr>)}</tbody></table></div>:<section className="wf-empty"><h2>没有匹配的 Workflow</h2><p>只展示真实登记记录。</p></section>}
      <div className="wf-pagination"><label>每页<select aria-label="每页记录数" value={limit} onChange={e=>{const next=new URLSearchParams(params);next.set('limit',e.target.value);next.delete('offset');setParams(next);}}>{Array.from(new Set([10,20,50,100,limit])).sort((a,b)=>a-b).map(v=><option key={v} value={v}>{v}</option>)}</select></label><span>{page.total?offset+1:0}–{Math.min(offset+limit,page.total)} / {page.total}</span><button className="secondary-button" disabled={offset===0} onClick={()=>move(Math.max(0,offset-limit))}>上一页</button><button className="secondary-button" disabled={offset+limit>=page.total} onClick={()=>move(offset+limit)}>下一页</button></div></>}
  </div>;
}
