import { useState } from 'react';
import type { FormEvent } from 'react';
import { badCaseApi, writeErrorText } from '../../api/badCases';
import type { Attribution, BadCase, BadCaseSummary } from '../../types/badCases';

export const causeLabels:Record<Attribution['cause'],string>={prompt:'Prompt 指令问题',data:'数据问题',capability:'能力缺失',validation:'校验规则问题',code:'程序实现问题',unknown:'尚待进一步定位'};
export const repairNodeLabels={intent_parser:'需求理解 · Intent Parser',analysis_planner:'分析规划 · Analysis Planner',insight_generator:'洞察生成 · Insight Generator'};

export function AttributionForm({item,onSaved}:{item:BadCase|BadCaseSummary;onSaved:(next:BadCase)=>void}){
  const [cause,setCause]=useState<Attribution['cause']>(item.attribution?.cause||'unknown');
  const [node,setNode]=useState(item.attribution?.node_id||'');
  const [error,setError]=useState(''),[saving,setSaving]=useState(false);
  async function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const form=e.currentTarget,data=new FormData(form);setSaving(true);setError('');
    try{const next=await badCaseApi.attribute(item.case_id,{cause,node_id:cause==='prompt'?node as Attribution['node_id']:null,
      explanation:String(data.get('explanation')||''),annotator:String(data.get('annotator')||''),expected_sequence:item.sequence},String(data.get('token')||''));onSaved(next);}
    catch(e){setError(writeErrorText(e));}finally{setSaving(false);}
  }
  return <form className="bc-form bc-attribution" aria-label={`归因判断：${item.title}`} onSubmit={submit}>
    <p className="muted">归因是人工判断。提交后进入处理中，旧判断和冻结证据继续保留。</p>
    <div className="bc-form-row"><label>归因原因<select aria-label="归因原因" value={cause} disabled={saving} onChange={e=>setCause(e.target.value as Attribution['cause'])}>{Object.entries(causeLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      {cause==='prompt'&&<label>修复节点<select required aria-label="修复节点" disabled={saving} value={node} onChange={e=>setNode(e.target.value as typeof node)}><option value="">请选择实际 LLM 节点</option>{Object.entries(repairNodeLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>}
      <label>操作人<input name="annotator" required maxLength={40} disabled={saving}/></label>
      <label>标注凭证<input name="token" type="password" autoComplete="off" disabled={saving} placeholder="本机测试模式可留空"/></label></div>
    <label>归因说明<textarea name="explanation" aria-label="归因说明" required maxLength={2000} disabled={saving} defaultValue={item.attribution?.explanation||''} placeholder="说明依据，以及准备修改什么。" rows={3}/></label>
    {error&&<p role="alert" className="bc-error">{error}</p>}
    <div className="bc-actions"><button type="submit" className="primary-button" disabled={saving}>{saving?'正在提交归因…':'确认提交归因'}</button></div>
  </form>;
}
