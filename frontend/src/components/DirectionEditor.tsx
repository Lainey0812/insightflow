import { useState } from 'react';
import { api } from '../api/client';
import type { AnalysisTaskV1, FieldProfile, Session } from '../types/contracts';

const functions: Record<string, string> = {count:'计数', distinct_count:'去重计数', sum:'合计', avg:'均值', median:'中位数', min:'最小值', max:'最大值'};
const operators: Record<string, string> = {eq:'等于', ne:'排除', gt:'大于', gte:'不小于', lt:'小于', lte:'不大于', in:'属于以下值', not_in:'排除以下值', is_null:'为空', not_null:'不为空'};
type Params = {dimensions?: string[]; metrics?: {function: string; field: string|null; alias: string}[];
  conditions?: {field:string; operator:string; value:unknown}[]; field?:string; direction?:string; n?:number; function?:string; alias?:string};

/** Edits existing controlled operations only. Server Validator and approval remain authoritative. */
export function DirectionEditor({task, session, onSaved, onCancel, onPending}: {
  task:AnalysisTaskV1; session:Session; onSaved:(next:Session)=>void; onCancel:()=>void; onPending:(busy:boolean)=>void;
}) {
  const [steps,setSteps]=useState(()=>structuredClone(task.steps));
  const [saving,setSaving]=useState(false); const [error,setError]=useState('');
  const fields:FieldProfile[]=session.profile && 'fields' in session.profile ? session.profile.fields : [];
  function optionsBefore(index:number) {
    let options=fields.map(f=>({id:f.field_id,label:f.display_name,kind:String(f.logical_type)}));
    for (const step of steps.slice(0,index)) {
      const p=step.params as Params;
      if (step.operation==='derive' && p.alias) options.push({id:p.alias,label:`${options.find(f=>f.id===p.field)?.label ?? '日期'}的${p.function==='extract_year'?'年份':'月份'}`,kind:'integer'});
      if (['aggregate','group_aggregate'].includes(step.operation)) options=[...options.filter(f=>p.dimensions?.includes(f.id)),
        ...(p.metrics ?? []).map(m=>({id:m.alias,label:`${options.find(f=>f.id===m.field)?.label ?? '记录'}${functions[m.function] ?? '统计'}`,kind:'number'}))];
    }
    return options;
  }
  function change(index:number, update:(p:Params)=>void) {setSteps(current=>{const next=structuredClone(current);update(next[index].params as Params);return next;});}
  function fieldSelect(value:string|undefined,index:number,label:string,onChange:(value:string)=>void,nullable=false) {
    const options=optionsBefore(index);
    return <label>{label}<select aria-label={label} value={value ?? ''} onChange={e=>onChange(e.target.value)}>
      {nullable && <option value="">整行记录</option>}
      {value && !options.some(f=>f.id===value) && <option value={value}>原引用不可用，请重新选择</option>}
      {options.map(f=><option key={f.id} value={f.id}>{f.label}</option>)}
    </select></label>;
  }
  async function save() {
    setError('');setSaving(true);onPending(true);
    try {
      const normalized=structuredClone(steps);
      normalized.forEach((step,index)=>{
        const p=step.params as Params;
        for (const c of p.conditions ?? []) {
          const kind=optionsBefore(index).find(f=>f.id===c.field)?.kind;
          const convert=(value:unknown)=>{
            if (['integer','number'].includes(kind ?? '')) {
              if (String(value).trim()==='' || !Number.isFinite(Number(value))) throw new Error('数值字段的筛选条件需要填写有效数字。');
              return Number(value);
            }
            if (kind==='boolean') {if (![true,false,'true','false'].includes(value as boolean|string)) throw new Error('布尔字段请填写 true 或 false。');return value===true || value==='true';}
            return String(value ?? '');
          };
          c.value=['is_null','not_null'].includes(c.operator) ? null : ['in','not_in'].includes(c.operator)
            ? (Array.isArray(c.value)?c.value:String(c.value).split('\n')).map(convert) : convert(c.value);
        }
      });
      const next=await api.editDirection(session,task.task_id,Object.fromEntries(normalized.map(step=>[step.step_id,step.params])));
      onSaved(next);
    } catch(e) {setError(e instanceof Error?e.message:'修改未保存，请检查当前版本。');}
    finally {setSaving(false);onPending(false);}
  }
  return <form className="direction-editor" aria-label={`修改${task.title}`} onSubmit={e=>{e.preventDefault();void save();}}>
    <p>修改已有分析步骤。保存后生成新版本、撤销原审批，并重新检查目标与条件；冲突条件仍会阻止执行。</p>
    <fieldset disabled={saving}><legend>调整计算条件</legend>
      {steps.map((step,index)=>{const p=step.params as Params;return <div className="step-editor" key={step.step_id}>
        {p.conditions && <><h6>筛选条件</h6>{p.conditions.map((c,j)=><div className="editor-grid" key={j}>
          {fieldSelect(c.field,index,`筛选字段 ${j+1}`,value=>change(index,p=>{p.conditions![j].field=value;}))}
          <label>筛选方式<select aria-label={`筛选方式 ${j+1}`} value={c.operator} onChange={e=>change(index,p=>{p.conditions![j].operator=e.target.value;})}>{Object.entries(operators).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
          {!['is_null','not_null'].includes(c.operator) && <label>筛选值{['in','not_in'].includes(c.operator)
            ? <textarea aria-label={`筛选值 ${j+1}`} value={Array.isArray(c.value)?c.value.join('\n'):String(c.value ?? '')} placeholder="每行一个值" onChange={e=>change(index,p=>{p.conditions![j].value=e.target.value.split('\n');})}/>
            : <input aria-label={`筛选值 ${j+1}`} value={String(c.value ?? '')} onChange={e=>change(index,p=>{p.conditions![j].value=e.target.value;})}/>}</label>}
        </div>)}</>}
        {p.dimensions && <div><h6>分组维度</h6>{p.dimensions.map((value,j)=><div key={j}>{fieldSelect(value,index,`分组字段 ${j+1}`,value=>change(index,p=>{p.dimensions![j]=value;}))}</div>)}</div>}
        {p.metrics && <><h6>统计指标</h6>{p.metrics.map((m,j)=><div className="editor-grid" key={j}>
          {fieldSelect(m.field ?? '',index,`指标字段 ${j+1}`,value=>change(index,p=>{p.metrics![j].field=value||null;}),m.function==='count')}
          <label>计算方式<select aria-label={`计算方式 ${j+1}`} value={m.function} onChange={e=>change(index,p=>{
            const metric=p.metrics![j];metric.function=e.target.value;
            const options=optionsBefore(index);const numeric=!['count','distinct_count'].includes(metric.function);
            if (numeric && !options.some(f=>f.id===metric.field && ['integer','number'].includes(f.kind))) metric.field=options.find(f=>['integer','number'].includes(f.kind))?.id ?? metric.field;
            if (!metric.field && metric.function!=='count') metric.field=options[0]?.id ?? null;
          })}>{Object.entries(functions).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        </div>)}</>}
        {['sort','top_n'].includes(step.operation) && <><h6>排序与返回数量</h6><div className="editor-grid">
          {fieldSelect(p.field,index,'排序依据',value=>change(index,p=>{p.field=value;}))}
          <label>排序方式<select aria-label="排序方式" value={p.direction} onChange={e=>change(index,p=>{p.direction=e.target.value;})}><option value="desc">从高到低</option><option value="asc">从低到高</option></select></label>
          {step.operation==='top_n' && <label>返回前几项<input aria-label="返回前几项" type="number" min={1} max={1000} required value={p.n} onChange={e=>change(index,p=>{p.n=Number(e.target.value);})}/></label>}
        </div></>}
        {step.operation==='derive' && <><h6>日期转换</h6>{fieldSelect(p.field,index,'日期字段',value=>change(index,p=>{p.field=value;}))}<label>提取内容<select aria-label="提取内容" value={p.function} onChange={e=>change(index,p=>{p.function=e.target.value;})}><option value="extract_year">年份</option><option value="extract_month">月份</option></select></label></>}
        {!['filter','group_aggregate','aggregate','sort','top_n','derive'].includes(step.operation) && <p>此方法尚不支持直接修改，请重新提出需求。</p>}
      </div>;})}
    </fieldset>
    <p>这里调整已有步骤，不增加新方法或解除未确认要求。如需新增筛选步骤、改变核心目标或补充口径，请重新提出需求。</p>
    {error && <p role="alert">{error}</p>}
    <div className="editor-actions"><button className="secondary-button" type="button" disabled={saving} onClick={onCancel}>取消修改</button><button className="primary-button" disabled={saving} type="submit">{saving?'正在保存并校验…':'保存修改并重新审核'}</button></div>
  </form>;
}
