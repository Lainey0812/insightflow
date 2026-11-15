import { useState } from 'react';
import { api } from '../api/client';
import type { Session, ScopePreview, ScopeTarget } from '../types/contracts';

export function ScopeConfirmation({session,target,fieldName,busy,onSaved,onPending}:{
  session:Session;target:ScopeTarget;fieldName:string;busy:boolean;onSaved:(next:Session)=>void;onPending:(busy:boolean)=>void;
}) {
  const [mode,setMode]=useState<'exact'|'normalized_contains'>('normalized_contains');
  const [preview,setPreview]=useState<ScopePreview|null>(null);const [pending,setPending]=useState(false);const [error,setError]=useState('');
  async function act(save:boolean) {
    setPending(true);onPending(true);setError('');
    try {
      if (save && preview) onSaved(await api.confirmScope(session,target,mode,preview.preview_digest));
      else setPreview(await api.previewScope(session,target,mode));
    } catch(e) {setError(e instanceof Error?e.message:'范围核对失败，请刷新方案。');}
    finally {setPending(false);onPending(false);}
  }
  return <section className="scope-confirmation" aria-label={`${fieldName}的范围确认`}>
    <h5>先确认“{target.keyword}”包含哪些名称</h5>
    <p>筛选字段：{fieldName}。选定范围后重新校验方案，尚不会执行分析。</p>
    <fieldset disabled={busy||pending}><legend>名称匹配方式</legend>
      <label><input type="radio" name={`scope-${target.filter_index}`} checked={mode==='normalized_contains'} onChange={()=>{setMode('normalized_contains');setPreview(null);setError('');}}/>包含名称变体（忽略大小写和空白）</label>
      <label><input type="radio" name={`scope-${target.filter_index}`} checked={mode==='exact'} onChange={()=>{setMode('exact');setPreview(null);setError('');}}/>仅完全等于“{target.keyword}”</label>
    </fieldset>
    <p>按文字包含关系核对，不自动推断同义词或职业类别，也不修改原始数据。</p>
    {preview && <div className="scope-preview" role="status"><strong>匹配 {preview.matched_row_count} / {preview.dataset_row_count} 条上传记录</strong><p>{preview.summary}</p>
      <details><summary>查看纳入的 {preview.scope.values.length} 种完整名称</summary><ul>{preview.scope.values.map(value=><li key={value}>{value}</li>)}</ul></details>
    </div>}
    {error && <p role="alert">{error}</p>}
    <div className="editor-actions"><button className="secondary-button" disabled={busy||pending} onClick={()=>void act(false)}>{pending&&!preview?'正在核对范围…':'预览匹配范围'}</button>
      <button className="primary-button" disabled={busy||pending||!preview} onClick={()=>void act(true)}>{pending&&preview?'正在保存并重新校验…':'保存范围并重新审核'}</button></div>
  </section>;
}
