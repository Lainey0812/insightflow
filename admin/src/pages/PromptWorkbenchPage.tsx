import { Fragment, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { FileText, FlaskConical, History, Link2, Play, Search } from 'lucide-react';
import { promptApi } from '../api/prompts';
import { workbenchApi } from '../api/promptWorkbench';
import type { DebugResult } from '../api/promptWorkbench';
import type { PromptCatalogItem, TemplateSummary } from '../types/prompts';
import { CopyText, jsonText, nodeLabels, Pagination, RegistryError, usePromptData, versionPath } from '../features/prompts/PromptShared';
import { timeText, durationText } from '../features/traces/presentation';
import { badCaseApi, writeErrorText } from '../api/badCases';

const labels:Record<string,string>={intent_parser:'需求理解',analysis_planner:'分析规划',insight_generator:'洞察生成'};
const tabs=[['edit','编辑',FileText],['debug','调试 & Diff',FlaskConical],['history','历史版本',History],['related','关联内容',Link2]] as const;
const nodes=Object.keys(labels);

export function PromptWorkbenchPage(){
  const [params,setParams]=useSearchParams();
  const node=nodes.includes(params.get('node')||'')?params.get('node')!:'intent_parser';
  const tab=tabs.some(t=>t[0]===params.get('tab'))?params.get('tab')!:'edit';
  const catalog=usePromptData(signal=>promptApi.catalog('',signal),[]);
  const [busy,setBusy]=useState(false);
  const queryRef=useRef(params);
  useEffect(()=>{queryRef.current=params;},[params]);
  function route(values:Record<string,string>){const next=new URLSearchParams(queryRef.current);Object.entries(values).forEach(([k,v])=>v?next.set(k,v):next.delete(k));queryRef.current=next;setParams(next);}
  return <div className="pw-page"><header className="pw-heading"><div><h1>Prompt 工作台</h1><p>沿着节点调整指令，用真实调用核对变化。</p></div><Link to="/prompts/catalog" className="trace-link">快照目录</Link></header>
    <div className="pw-layout"><aside className="pw-directory" aria-label="LLM 节点目录"><h2>Workflow 节点</h2>{nodes.map(n=>{const item=catalog.data?.items.find(i=>i.node_id===n);return <button key={n} disabled={busy} aria-current={node===n?'page':undefined} onClick={()=>route({node:n,version:'',left:'',right:'',offset:''})}><span className="pw-node-dot"/><span><strong>{labels[n]}</strong><small>{nodeLabels[n]}</small><small>{item?`${item.version_count} 个已登记版本`:'正在读取版本'}</small></span></button>;})}<p>仅列出当前三个真实 LLM 节点。计算与校验节点不使用 Prompt。</p></aside>
    <main className="pw-main">{catalog.error?<RegistryError error={catalog.error} retry={catalog.reload}/>:catalog.loading?<p role="status">正在读取节点…</p>:<NodeWorkspace key={node} node={node} tab={tab} params={params} route={route} catalog={catalog.data?.items.find(i=>i.node_id===node)} busy={busy} setBusy={setBusy} refreshCatalog={catalog.reload}/>}</main></div>
  </div>;
}

function NodeWorkspace({node,tab,params,route,catalog,busy,setBusy,refreshCatalog}:{node:string;tab:string;params:URLSearchParams;route:(x:Record<string,string>)=>void;catalog?:PromptCatalogItem;busy:boolean;setBusy:(v:boolean)=>void;refreshCatalog:()=>void}){
  const navigate=useNavigate(),badCaseId=params.get('bad_case')||'';
  const repairCase=usePromptData(signal=>badCaseId?badCaseApi.get(badCaseId,signal):Promise.resolve(null),[badCaseId]);
  const [repairOperator,setRepairOperator]=useState(''),[repairNote,setRepairNote]=useState(''),[repairError,setRepairError]=useState('');
  const offset=Number(params.get('offset'))||0;
  const history=usePromptData(signal=>promptApi.history(node,Math.max(0,offset),signal),[node,offset]);
  const runtime=catalog?.runtime_registration==='registered'?catalog.runtime_snapshot_id:null;
  // A historical selection is explicit; never substitute latest history for current runtime.
  const selected=params.get('version')||runtime||'';
  const detail=usePromptData(signal=>selected?promptApi.detail(node,selected,signal):Promise.resolve(null),[node,selected]);
  const [draft,setDraft]=useState(''),[draftBase,setDraftBase]=useState('');
  const [instruction,setInstruction]=useState(''),[schema,setSchema]=useState('{\n  "type": "object",\n  "properties": {},\n  "additionalProperties": false\n}');
  const [caseName,setCaseName]=useState(''),[sourceCall,setSourceCall]=useState('');
  const [annotation,setAnnotation]=useState(''),[snapshot,setSnapshot]=useState('');
  const [result,setResult]=useState<DebugResult|null>(null),[failure,setFailure]=useState<unknown>(null);
  const [sourceBusy,setSourceBusy]=useState(false),[runRevision,setRunRevision]=useState(0);
  const [useDraft,setUseDraft]=useState(false);
  const [versionSearch,setVersionSearch]=useState('');
  useEffect(()=>{if(detail.data){setDraft(detail.data.template.system_template);setDraftBase(detail.data.template.template_snapshot_id);setUseDraft(false);}},[detail.data]);
  const mode=params.get('mode')==='diff'?'diff':'single';
  const left=params.get('left')||selected,right=params.get('right')||'';
  const changed=!!detail.data&&draft!==detail.data.template.system_template;
  const canRepair=!!repairCase.data&&repairCase.data.status==='in_progress'&&repairCase.data.attribution?.cause==='prompt'&&repairCase.data.attribution.node_id===node;
  async function confirmRepair(){
    if(!repairCase.data||!canRepair||!changed||draftBase!==selected||!repairOperator.trim())return;
    setBusy(true);setRepairError('');
    try{
      const saved=await badCaseApi.saveRepairDraft(badCaseId,{base_snapshot_id:selected,system_prompt:draft,expected_sequence:repairCase.data.sequence},annotation);
      await badCaseApi.completeRepair(badCaseId,{template_snapshot_id:saved.template_snapshot_id,expected_sequence:repairCase.data.sequence,annotator:repairOperator.trim(),note:repairNote},annotation);
      navigate('/bad-cases/'+encodeURIComponent(badCaseId));
    }catch(e){setRepairError(writeErrorText(e));}finally{setBusy(false);}
  }
  const current=runtime?history.data?.items.find(t=>t.template_snapshot_id===runtime):null;
  const currentDetail=usePromptData(signal=>runtime?promptApi.detail(node,runtime,signal):Promise.resolve(null),[node,runtime]);
  const version=current?.version||currentDetail.data?.template.version;
  async function loadCall(){
    setSourceBusy(true);setFailure(null);
    try{
      const call=await promptApi.call(sourceCall);
      if(call.call.node_id!==node)throw new Error('该调用不属于当前节点。');
      const raw=await promptApi.raw(sourceCall,snapshot);
      const messages=raw.payload.messages as {role:string;content:string}[];
      const user=messages.filter(m=>m.role==='user');
      const format=raw.payload.response_format as {json_schema?:{schema?:Record<string,unknown>}};
      if(user.length!==1||typeof user[0].content!=='string'||!format?.json_schema?.schema)throw new Error('请求不是当前支持的单条User消息与JSON Schema格式。');
      setInstruction(user[0].content);setSchema(jsonText(format.json_schema.schema));
      setCaseName(caseName||`回放 ${sourceCall}`);
    }catch(e){setFailure(e);}finally{setSourceBusy(false);}
  }
  async function run(){
    setFailure(null);setResult(null);
    try{
      const value=JSON.parse(schema) as Record<string,unknown>;
      if(!value||Array.isArray(value)||value.type!=='object')throw new Error('输出Schema必须是type=object的JSON对象。');
      if(!instruction.trim()||!caseName.trim())throw new Error('请填写测试名称和测试输入。');
      const ids=mode==='diff'?[left,right]:[selected];
      if(ids.some(v=>!v)||new Set(ids).size!==ids.length)throw new Error('请选择有效版本；Diff需要两个不同版本。');
      if(useDraft&&draftBase!==selected)throw new Error('草稿与基准版本不一致，请重新加载。');
      setBusy(true);
      const response=await workbenchApi.run({node_id:node,snapshot_ids:ids,case_name:caseName.trim(),instruction,response_schema:value,
        ...(mode==='single'&&useDraft?{draft_system:draft}:{})},annotation,snapshot);
      setResult(response);setRunRevision(v=>v+1);history.reload();
    }catch(e){setFailure(e);}finally{setBusy(false);}
  }
  const versions=(history.data?.items||[]).filter(v=>!versionSearch||`${v.version} ${v.content_hash} ${v.template_snapshot_id}`.toLowerCase().includes(versionSearch.toLowerCase()));
  function select(label:string,value:string,key:string){return <label className="pw-field">{label}<select disabled={busy} aria-label={label} value={value} onChange={e=>route({[key]:e.target.value})}><option value="">选择已登记版本</option>{value&&!versions.some(v=>v.template_snapshot_id===value)&&<option value={value}>{value}</option>}{versions.map(v=><option key={v.template_snapshot_id} value={v.template_snapshot_id}>{v.version}{v.provenance==='admin_debug_draft'?'（调试草稿）':''}</option>)}</select></label>;}
  return <>{badCaseId&&<section className="bc-repair-context" aria-label="Bad Case 修复来源"><strong>正在修复 Bad Case：{repairCase.data?.title||badCaseId}</strong><code>{badCaseId}</code><Link to={'/bad-cases/'+encodeURIComponent(badCaseId)}>返回问题详情</Link>{repairCase.error?<p role="alert">无法读取修复任务，请返回详情刷新。</p>:repairCase.loading?<p role="status">正在读取归因…</p>:!canRepair?<p role="alert">当前归因、状态或节点不匹配；不能提交此修复。</p>:<p>保存修复草稿后返回详情，状态进入待验证；不会自动发布。</p>}</section>}<section className="pw-version-card"><div><span>当前运行时版本</span><h2>{version||'unknown'}</h2><p>{labels[node]} <span className="pw-active-dot"/> {runtime?'当前进程已绑定':'未确认当前进程绑定，不以最新登记替代'}</p></div><div className="pw-version-meta"><span>{catalog?.version_count??0} 个登记版本</span><code title={runtime||''}>{runtime?runtime.slice(0,18)+'…':'未采集快照'}</code><small>编辑与调试不会直接发布</small></div></section>
    <nav className="pw-tabs" role="tablist" aria-label="Prompt 内容">{tabs.map(([key,label,Icon])=><button disabled={busy} role="tab" aria-selected={tab===key} key={key} onClick={()=>route({tab:key})}><Icon size={16}/>{label}</button>)}</nav>
    {history.error&&<RegistryError error={history.error} retry={history.reload}/>}
    {tab==='edit'&&<section className="pw-panel"><header className="pw-section-head"><div><h2>编辑指令</h2><p>从已保存的版本开始，修改后进入调试。</p></div><span className={'pw-state '+(changed?'pw-dirty':'')}>{changed?'草稿已修改':'与所选版本一致'}</span></header>{select('编辑基准版本',selected,'version')}
      {detail.loading?<p role="status">正在加载 Prompt…</p>:detail.error?<RegistryError error={detail.error} retry={detail.reload}/>:detail.data?<>
        <label className="pw-field">System Prompt<textarea className="pw-editor" aria-label="System Prompt 编辑器" spellCheck={false} disabled={busy} value={draft} onChange={e=>setDraft(e.target.value)}/></label>
        <details className="pw-composition"><summary>查看固定 User 组合、重试指令与动态 Schema 定义</summary><p>这些片段由现有服务代码组装，本页只读；调试中的测试输入独立填写。</p><pre>{jsonText(detail.data.template.user_composition)}</pre><pre>{jsonText(detail.data.template.output_schema_definition)}</pre></details>
        <footer className="pw-editor-footer"><small>{badCaseId?'可先调试，或在下方确认保存修复草稿。未确认不会提交修复。':'草稿未发布。离开此页面或切换版本前，请先调试以保留快照。'}</small><button className="primary-button" disabled={busy||!draft.trim()} onClick={()=>{setUseDraft(true);route({tab:'debug',mode:'single'});}}>调试此草稿 <Play size={14}/></button></footer>
        {badCaseId&&<section className="bc-repair-confirm" aria-label="确认提交修复"><h3>确认本次修复</h3><p>请先修改指令；确认会保存新草稿并进入待验证，不代表验证通过。</p><div className="bc-form-row"><label>修复操作人<input aria-label="修复操作人" value={repairOperator} maxLength={40} disabled={busy} onChange={e=>setRepairOperator(e.target.value)}/></label><label>标注凭证<input type="password" value={annotation} autoComplete="off" onChange={e=>setAnnotation(e.target.value)} placeholder="本机测试模式可留空"/></label></div><label>修复说明<textarea aria-label="修复说明" value={repairNote} maxLength={2000} onChange={e=>setRepairNote(e.target.value)}/></label>{repairError&&<p role="alert" className="bc-error">{repairError}</p>}<button className="primary-button" disabled={busy||!canRepair||!changed||!repairOperator.trim()} onClick={()=>void confirmRepair()}>{busy?'正在提交修复…':'确认修复并返回待验证'}</button></section>}
      </>:<p className="pw-empty">该节点暂无可确认的当前 Prompt。请选择已有历史版本；不生成虚假内容。</p>}</section>}
    {tab==='debug'&&<section className="pw-panel"><div className="pw-subtabs" role="tablist" aria-label="调试方式"><button role="tab" aria-selected={mode==='single'} onClick={()=>route({mode:'single'})}>单独调试</button><button role="tab" aria-selected={mode==='diff'} onClick={()=>{setUseDraft(false);route({mode:'diff'});}}>Diff 调试</button></div>
      <div className="pw-version-selects">{mode==='single'?select('调试版本',selected,'version'):<>{select('左侧版本',left,'left')}{select('右侧版本',right,'right')}</>}</div>
      {mode==='single'&&<label className="pw-check"><input type="checkbox" checked={useDraft} disabled={busy||!draftBase} onChange={e=>setUseDraft(e.target.checked)}/>使用编辑页草稿（将登记独立调试快照）</label>}
      {mode==='diff'&&left&&right&&left!==right&&<SavedDiff left={left} right={right}/>}
      <div className="pw-debug-input"><label className="pw-field">测试名称<input value={caseName} disabled={busy} onChange={e=>setCaseName(e.target.value)} placeholder="例如：城市销售额 Top 3"/></label>
        <details><summary>从已授权的历史调用载入输入</summary><div className="pw-inline"><input aria-label="历史 Call ID" value={sourceCall} onChange={e=>setSourceCall(e.target.value)} placeholder="call_…"/><button className="secondary-button" disabled={busy||sourceBusy||!sourceCall} onClick={()=>void loadCall()}>载入请求</button></div><p>将读取历史用户输入；不会将历史System覆盖到草稿。</p></details>
        <label className="pw-field">测试输入（User 消息）<textarea aria-label="调试输入" disabled={busy} value={instruction} onChange={e=>setInstruction(e.target.value)} placeholder="填写该节点所需的结构化输入，或从已授权调用载入。"/></label>
        <details><summary>输出 JSON Schema</summary><label className="pw-field">输出 Schema<textarea aria-label="输出 Schema" disabled={busy} value={schema} onChange={e=>setSchema(e.target.value)}/></label></details>
        <details className="pw-permissions"><summary>访问凭证（本地测试模式无需填写）</summary><label>调试写入凭证<input type="password" value={annotation} onChange={e=>setAnnotation(e.target.value)} autoComplete="off"/></label><label>快照读取凭证<input type="password" value={snapshot} onChange={e=>setSnapshot(e.target.value)} autoComplete="off"/></label><p>仅保留于当前页面内存；不写入URL或浏览器存储。</p></details>
      </div><footer className="pw-editor-footer"><p>会向当前配置的模型发送测试输入，产生真实调用费用。仅验证返回与JSON语法，不代表业务验收通过。</p><button className="primary-button" disabled={busy||sourceBusy||!selected||!instruction.trim()||!caseName.trim()||(mode==='diff'&&(!right||left===right))} onClick={()=>void run()}><Play size={15}/>{busy?'正在调试…':mode==='diff'?'运行两个版本':'运行调试'}</button></footer>
      {!!failure&&<div role="alert" className="trace-danger">{failure instanceof Error?failure.message:'调试未完成'}{'serverCode' in Object(failure)&&<code>{String((failure as {serverCode:string}).serverCode)}</code>}</div>}
      {result&&<section className="pw-results"><h2>调试结果</h2><p>{result.notice}</p><code>{result.test_id}</code><div className={result.results.length===2?'pw-result-grid':''}>{result.results.map(r=><article key={r.operation_id}><h3>{r.status} {r.is_mock?'· 测试 Provider':''}</h3><code>{r.template_snapshot_id}</code>{r.error_code?<p role="alert">{r.error_code}</p>:<><small>{r.model} · JSON {r.json_valid?'可解析':'不可解析'}</small><pre>{r.output}</pre><CopyText text={r.output||''}/><p>{r.validation_notice}</p></>}{r.calls.map(c=><p key={c.call_id}><Link to={'/prompts/calls/'+c.call_id}>{c.call_id}</Link> · {durationText(c.duration_ms)}</p>)}</article>)}</div></section>}
    </section>}
    {tab==='history'&&<section className="pw-panel"><header className="pw-section-head"><div><h2>历史版本</h2><p>原始快照不可覆盖。调试草稿单独标记，不代表已发布。</p></div><button className="secondary-button" onClick={()=>{history.reload();refreshCatalog();}}>刷新版本</button></header>{history.loading?<p role="status">正在加载历史版本…</p>:!versions.length?<p className="pw-empty">尚无已登记快照</p>:<div className="trace-table-wrap pw-history-wrap"><table className="trace-table pw-history-table" aria-label="Prompt 历史版本"><thead><tr><th scope="col">版本号</th><th scope="col">来源 / 状态</th><th scope="col">登记时间</th><th scope="col">变更说明</th><th scope="col">操作</th></tr></thead><tbody>{versions.map(v=><HistoryEntry key={v.template_snapshot_id} row={v} current={v.template_snapshot_id===runtime} onEdit={()=>route({version:v.template_snapshot_id,tab:'edit'})}/>)}</tbody></table></div>}{history.data&&<Pagination {...history.data} change={v=>route({offset:String(v)})}/>}</section>}
    {tab==='related'&&<section className="pw-panel"><header className="pw-section-head"><div><h2>关联内容</h2><p>按精确快照查询实际运行过的测试，不根据版本名称猜测关联。</p></div><Search size={18}/></header><label className="pw-field">搜索当前页版本<input aria-label="版本搜索" placeholder="版本号、哈希或快照 ID" value={versionSearch} onChange={e=>setVersionSearch(e.target.value)}/></label>{select('筛选 Prompt 版本',selected,'version')}{selected?<RelatedContent key={selected+runRevision} node={node} id={selected}/>:<p className="pw-empty">请选择实际存在的版本。</p>}</section>}
    {history.data&&tab!=='history'&&<Pagination {...history.data} label="可选版本" change={v=>route({offset:String(v)})}/>}
  </>;
}

function HistoryEntry({row,current,onEdit}:{row:TemplateSummary;current:boolean;onEdit:()=>void}){
  const [open,setOpen]=useState(false);
  const data=usePromptData(signal=>open?promptApi.detail(row.node_id,row.template_snapshot_id,signal):Promise.resolve(null),[open,row.template_snapshot_id]);
  const contentId=`history-content-${row.template_snapshot_id}`;
  return <Fragment><tr><td><strong title={row.version}>{row.version}</strong><code title={row.content_hash}>{row.content_hash.slice(0,12)}…</code></td><td><span>{row.provenance==='admin_debug_draft'?'调试草稿':'运行时来源快照'}</span>{current&&<small className="pw-current-version">当前运行时</small>}</td><td><time>{timeText(row.created_at)}</time><small title={row.source_commit||'unknown'}>Commit：{row.source_commit?.slice(0,8)||'unknown'}</small></td><td><span className="pw-history-summary" title={row.change_summary}>{row.change_summary}</span></td><td><div className="pw-history-actions"><button className="secondary-button" aria-expanded={open} aria-controls={contentId} onClick={()=>setOpen(v=>!v)}>{open?'收起 Prompt 内容':'查看完整 Prompt 内容'}</button><button className="secondary-button" onClick={onEdit}>带入编辑</button><Link className="trace-link" to={versionPath(row.node_id,row.template_snapshot_id)}>完整版本详情</Link></div></td></tr>{open&&<tr className="pw-history-content"><td colSpan={5}><section id={contentId} aria-label={`${row.version}的 Prompt 内容`}><h3>{row.version}</h3>{data.error?<RegistryError error={data.error} retry={data.reload}/>:data.data?<><pre>{data.data.template.system_template}</pre><details><summary>User 组合与来源</summary><pre>{jsonText(data.data.template.user_composition)}</pre></details></>:<p role="status">正在读取内容…</p>}</section></td></tr>}</Fragment>;
}

function SavedDiff({left,right}:{left:string;right:string}){
  const data=usePromptData(signal=>promptApi.compare(left,right,signal),[left,right]);
  return <details className="pw-saved-diff"><summary>查看两个版本的文本 Diff</summary>{data.error?<RegistryError error={data.error} retry={data.reload}/>:data.data?<>{data.data.sections.filter(s=>s.changed).map(s=><section key={s.key}><h3>{s.label}</h3><div className="pw-diff-lines">{s.lines.filter(l=>l.kind!=='equal').map((l,i)=><div key={i}><pre className="diff-removed">{l.left_number} {l.left}</pre><pre className="diff-added">{l.right_number} {l.right}</pre></div>)}</div></section>)}{data.data.content_hash_equal&&<p>版本内容相同。</p>}</>:<p>正在比较…</p>}</details>;
}

function RelatedContent({node,id}:{node:string;id:string}){
  const [offset,setOffset]=useState(0),[callOffset,setCallOffset]=useState(0);
  const tests=usePromptData(signal=>workbenchApi.tests(node,id,offset,signal),[node,id,offset]);
  const calls=usePromptData(signal=>promptApi.calls(node,id,callOffset,signal),[node,id,callOffset]);
  return <><h3>关联测试用例</h3>{tests.error?<RegistryError error={tests.error} retry={tests.reload}/>:tests.loading?<p role="status">正在查询关联用例…</p>:tests.data&&<><p className="muted">{tests.data.notice}</p>{tests.data.items.length?<div className="trace-table-wrap"><table className="trace-table"><thead><tr><th>测试名称 / 时间</th><th>输入哈希</th><th>状态与调用</th></tr></thead><tbody>{tests.data.items.map(t=><tr key={t.test_id}><td><strong>{t.case_name}</strong><small>{timeText(t.created_at)}</small><code>{t.test_id}</code></td><td><code>{t.input_hash}</code></td><td>{t.sides.map(s=><div key={s.operation_id}>{s.status}{s.calls.map(c=><p key={c.call_id}><Link to={'/prompts/calls/'+c.call_id}>{c.call_id}</Link></p>)}</div>)}</td></tr>)}</tbody></table></div>:<p className="pw-empty">该版本暂无已记录的调试测试用例；不代表从未测试。</p>}<Pagination {...tests.data} label="测试用例" change={setOffset}/></>}
    <h3>实际模型调用</h3><p className="muted">调用记录与测试用例分开展示；普通分析调用不冒充评测案例。</p>{calls.error?<RegistryError error={calls.error} retry={calls.reload}/>:calls.data&&<><ul className="pw-call-list">{calls.data.items.map(i=><li key={i.call.call_id}><Link to={'/prompts/calls/'+i.call.call_id}>{i.call.call_id}</Link><span>{i.call.status} · {timeText(i.call.started_at)}</span></li>)}</ul>{!calls.data.items.length&&<p className="pw-empty">暂无关联调用。</p>}<Pagination {...calls.data} label="调用" change={setCallOffset}/></>}
  </>;
}
