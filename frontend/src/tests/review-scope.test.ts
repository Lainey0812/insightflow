import { expect, it } from 'vitest';
import { directionScope } from '../components/reviewScope';
import fixture from './fixtures/hitl-v1.json';
import type { AnalysisTaskV1, FieldProfile } from '../types/contracts';
const fields=fixture.profile.fields as FieldProfile[];
const task=(steps:AnalysisTaskV1['steps']):AnalysisTaskV1=>({task_id:'A01',title:'范围验证',business_question:'比较各分组',priority:'P0',priority_reason:'回答核心问题',requirement_ids:['C1'],depends_on:[],steps});

it('does not invent filters or effective sample counts when none are configured',()=>{
  expect(directionScope(task([{step_id:'S1',operation:'aggregate',params:{metrics:[{function:'count',field:null,alias:'n'}]}}]),fields)).toEqual(['当前方向未设置额外筛选。']);
});
it('keeps input filters separate from filters on aggregated results',()=>{
  const field=fields.find(f=>f.logical_type==='text')!;
  const scope=directionScope(task([
    {step_id:'S1',operation:'filter',params:{conditions:[{field:field.field_id,operator:'ne',value:'已取消'}]}},
    {step_id:'S2',operation:'aggregate',params:{metrics:[{function:'count',field:null,alias:'n'}]}},
    {step_id:'S3',operation:'filter',params:{conditions:[{field:'n',operator:'gt',value:2}]}},
  ]),fields);
  expect(scope).toEqual([`数据筛选：${field.display_name}排除已取消`,'结果筛选：记录数大于2']);
  expect(scope.join()).not.toContain('field_');
});
it('does not claim a verified scope for missing, unsupported or invalid steps',()=>{
  expect(directionScope(undefined,fields).join()).toContain('尚无法核对');
  expect(directionScope(task([{step_id:'S1',operation:'python',params:{}}]),fields).join()).toContain('尚无法核对');
  expect(directionScope(task([{step_id:'S1',operation:'filter',params:{conditions:[]}}]),fields).join()).toContain('尚无法核对');
});
it('does not expose unknown field IDs or mistake unknown references for unfiltered input',()=>{
  const result=directionScope(task([{step_id:'S1',operation:'filter',params:{conditions:[{field:'invented',operator:'eq',value:'A'}]}}]),fields).join();
  expect(result).toContain('待核对字段');expect(result).toContain('尚无法核对');expect(result).not.toContain('invented');expect(result).not.toContain('未设置额外筛选');
});
