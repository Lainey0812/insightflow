import type { AnalysisTaskV1, FieldProfile } from '../types/contracts';

const operators:Record<string,string>={eq:'等于',ne:'排除',gt:'大于',gte:'不小于',lt:'小于',lte:'不大于',in:'属于',not_in:'不属于',is_null:'为空',not_null:'不为空'};
const functions:Record<string,string>={count:'计数',distinct_count:'去重计数',sum:'合计',avg:'均值',median:'中位数',min:'最小值',max:'最大值'};
const knownOperations=new Set(['filter','aggregate','group_aggregate','sort','top_n','derive']);

/** Describe saved filters only; do not infer dataset limits or business meaning from names. */
export function directionScope(task:AnalysisTaskV1|undefined,fields:FieldProfile[]):string[] {
  if (!task?.steps.length) return ['当前方向的数据范围尚无法核对，请查看待确认事项。'];
  let names=new Map(fields.map(f=>[f.field_id,f.display_name]));
  let resultStage=false;let unknown=false;
  const lines:string[]=[];
  const name=(id:unknown)=>{const label=names.get(String(id));if(!label)unknown=true;return label ?? '待核对字段';};
  const value=(v:unknown):string=>Array.isArray(v)?v.map(value).join('、'):typeof v==='boolean'?(v?'是':'否'):String(v ?? '');
  for (const step of task.steps) {
    const p=step.params;
    if (!knownOperations.has(step.operation)) unknown=true;
    if (step.operation==='filter') {
      if (!Array.isArray(p.conditions) || !p.conditions.length) {unknown=true;continue;}
      for (const condition of p.conditions) {
        if (!condition || typeof condition!=='object') {unknown=true;continue;}
        const c=condition as Record<string,unknown>;const operator=operators[String(c.operator)];
        if (!operator) {unknown=true;continue;}
        lines.push(`${resultStage?'结果筛选':'数据筛选'}：${name(c.field)}${operator}${['is_null','not_null'].includes(String(c.operator))?'':value(c.value)}`);
      }
    }
    if (step.operation==='derive' && !['extract_year','extract_month'].includes(String(p.function))) unknown=true;
    if (step.operation==='derive' && typeof p.alias==='string') {
      names.set(p.alias,`${name(p.field)}的${p.function==='extract_year'?'年份':p.function==='extract_month'?'月份':'转换结果'}`);
    }
    if (['aggregate','group_aggregate'].includes(step.operation)) {
      const next=new Map([...names].filter(([id])=>Array.isArray(p.dimensions) && p.dimensions.includes(id)));
      if (Array.isArray(p.metrics)) for (const metric of p.metrics) {
        if (metric && typeof metric==='object' && typeof metric.alias==='string') {
          next.set(metric.alias,metric.field==null && metric.function==='count'?'记录数':`${name(metric.field)}${functions[String(metric.function)] ?? '统计结果'}`);
        }
      }
      names=next;resultStage=true;
    }
    if (step.operation==='top_n') resultStage=true;
  }
  if (unknown) lines.push('部分步骤的数据范围尚无法核对，请查看此方向的限制。');
  if (!lines.length) lines.push('当前方向未设置额外筛选。');
  return lines;
}
