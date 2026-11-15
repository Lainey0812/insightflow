import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { it, expect, vi } from 'vitest';
import { BusinessPlanReview } from '../components/BusinessPlanReview';
import { api } from '../api/client';
import type { Session, ReviewPresentation } from '../types/contracts';
import fixture from './fixtures/hitl-v1.json';
import { reviewFixture } from './review-fixtures';

const state = () => structuredClone(fixture) as Session;
function props(current:Session) {return {session:current, plan:current.review_plan!, busy:false, onRemove:vi.fn(), onConfirm:vi.fn(), onRestart:vi.fn()};}

it('keeps approval disabled until authoritative eligibility returns',async()=>{
  let resolve!:(value:ReviewPresentation)=>void;
  const current=state();vi.spyOn(api,'review').mockReturnValue(new Promise(r=>{resolve=r;}));
  render(<BusinessPlanReview {...props(current)}/>);
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
  resolve(reviewFixture(current));
  await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeEnabled());
});
it('fails closed when eligibility cannot load and retry is functional',async()=>{
  const current=state();vi.spyOn(api,'review').mockRejectedValueOnce(new Error('network')).mockResolvedValue(reviewFixture(current));
  render(<BusinessPlanReview {...props(current)}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('在核对完成前不会开始分析');
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
  await userEvent.click(screen.getByRole('button',{name:'重新加载方案'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeEnabled());
});
it.each(['revision','plan_version','session_id','plan_id'] as const)('rejects eligibility for a mismatched %s',async key=>{
  const current=state();const view=reviewFixture(current);Object.assign(view,{[key]:typeof view[key]==='number'?99:'foreign'});
  vi.spyOn(api,'review').mockResolvedValue(view);render(<BusinessPlanReview {...props(current)}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('方案已更新');
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
});
it('does not infer permission from verified audit when server denies approval',async()=>{
  const current=state();vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current,{can_approve:false}));
  const p=props(current);render(<BusinessPlanReview {...p}/>);
  await screen.findByText('01 · 核心分析目标');
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();expect(p.onConfirm).not.toHaveBeenCalled();
});
it('places raw operations, field IDs and feasibility only inside technical details',async()=>{
  const current=state();vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current));
  render(<BusinessPlanReview {...props(current)}/>);await screen.findByText('01 · 核心分析目标');
  const technical=screen.getByText('技术详情').closest('details')!;
  const raw=within(technical).getByText(/field_0004/);expect(raw).not.toBeVisible();
  expect(screen.getAllByText('核心分析').length).toBeGreaterThan(0);
  await userEvent.click(screen.getByText('技术详情'));expect(raw).toBeVisible();
});
it('exposes a working restart and no nonfunctional natural-language revision',async()=>{
  const current=state();vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current));
  const p=props(current);render(<BusinessPlanReview {...p}/>);await screen.findByText('01 · 核心分析目标');
  await userEvent.click(screen.getByRole('button',{name:'重新提出需求'}));expect(p.onRestart).toHaveBeenCalledOnce();
  expect(screen.queryByRole('button',{name:/AI.*修改|自然语言修改/})).not.toBeInTheDocument();
});
it('ignores an old response after deletion creates a new immutable version',async()=>{
  const old=state();let resolve!:(value:ReviewPresentation)=>void;
  const next=structuredClone(old);next.revision+=2;next.review_plan!.plan_version=2;next.current_plan_version=2;
  vi.spyOn(api,'review').mockReturnValueOnce(new Promise(r=>{resolve=r;})).mockResolvedValue(reviewFixture(next,{goal:'新的已校验目标'}));
  const r=render(<BusinessPlanReview {...props(old)}/>);r.rerender(<BusinessPlanReview {...props(next)}/>);
  expect(await screen.findByText('新的已校验目标')).toBeInTheDocument();
  resolve(reviewFixture(old));await waitFor(()=>expect(screen.getByText('新的已校验目标')).toBeInTheDocument());
  expect(screen.getByRole('region',{name:'分析方案 第2版'})).toBeInTheDocument();
});
it.each([true,false])('shows report capacity estimate without inferring approval: %s',async supported=>{
  const current=state();const view=reviewFixture(current,{can_approve:supported});
  view.report_capacity={policy_version:'report-capacity-v1',supported,metric_count:9,core_metric_count:9,
    estimated_batches:2,max_groups_per_call:8,max_groups:64,max_batches:8,estimated_metadata_bytes:2000,
    context_estimate_only:true,message:supported?'包含9个核心指标，预计分2批生成。':'方案超出报告总容量，请重新明确范围。'};
  vi.spyOn(api,'review').mockResolvedValue(view);
  render(<BusinessPlanReview {...props(current)}/>);
  await screen.findByText('03 · 请确认分析方向');
  const message=screen.getByText(view.report_capacity.message);
  if (supported) {expect(message).not.toBeVisible();await userEvent.click(screen.getByText('技术详情'));}
  expect(message).toBeVisible();
  expect(screen.getByRole('button',{name:'确认并开始分析'}).hasAttribute('disabled')).toBe(!supported);
});

it('saves a declared grain as a new plan through the working API and parent update',async()=>{
  const current=state();const next={...current,revision:current.revision+1};
  const basis={version:'analysis-basis-v1',digest:'saved',plan_version:1,row_grain:'unknown' as const,entity_field_id:null,
    metrics:[{task_id:'A01',step_id:'S01',alias:'n',field_id:null,label:'记录',function:'count',basis:'逐行计数，不是业务实体去重数量',unit_status:'record_count'}],
    entity_field_options:[{field_id:'field_0001',label:'唯一编号',unique_non_null:true}]};
  vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current,{analysis_basis:basis}));
  const save=vi.spyOn(api,'saveAnalysisBasis').mockResolvedValue(next);const onBasisSaved=vi.fn();
  render(<BusinessPlanReview {...props(current)} onBasisSaved={onBasisSaved}/>);
  await screen.findByText('需要说明一行代表什么？（可选）');
  expect(screen.getByText(/逐行计数，不是业务实体去重数量/)).not.toBeVisible();
  await userEvent.click(screen.getAllByText('查看计算说明')[0]);
  expect(screen.getByText(/逐行计数，不是业务实体去重数量/)).toBeVisible();
  await userEvent.click(screen.getByText('需要说明一行代表什么？（可选）'));
  await userEvent.selectOptions(screen.getByLabelText('记录粒度'),'entity');
  expect(screen.getByRole('button',{name:'保存粒度声明并重新审核'})).toBeDisabled();
  await userEvent.selectOptions(screen.getByLabelText('实体标识'),'field_0001');
  await userEvent.click(screen.getByRole('button',{name:'保存粒度声明并重新审核'}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith(current,'entity','field_0001'));
  expect(onBasisSaved).toHaveBeenCalledWith(next);
});

it('allows a grain declaration while unrelated approval issues remain blocking',async()=>{
  const current=state();
  const basis={version:'analysis-basis-v1',digest:'bound',plan_version:1,row_grain:'unknown' as const,entity_field_id:null,metrics:[],entity_field_options:[]};
  vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current,{can_approve:false,analysis_basis:basis}));
  render(<BusinessPlanReview {...props(current)} onBasisSaved={vi.fn()}/>);
  await screen.findByText('需要说明一行代表什么？（可选）');
  await userEvent.click(screen.getByText('需要说明一行代表什么？（可选）'));
  expect(screen.getByLabelText('记录粒度')).toBeEnabled();
  expect(screen.getByRole('button',{name:'保存粒度声明并重新审核'})).toBeEnabled();
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
});

it('shows genuine profile cards and never labels missing cells as invalid rows',async()=>{
  const current=state();const overview={dataset_id:'dataset',dataset_version:'version',file_name:'通用.csv',sheet_name:null,
    row_count:100,column_count:5,missing_cell_count:8,duplicate_row_count:2,fields_with_missing:[{name:'工时',missing_count:8}],quality_notes:[],
    cleaning_status:'not_performed' as const,cleaning_notice:'尚未自动删除、填补或去重。',sample_notice:'有效样本量执行后统计。'};
  vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current,{data_overview:overview}));
  render(<BusinessPlanReview {...props(current)}/>);
  const region=await screen.findByRole('region',{name:'本次使用的数据'});
  expect(region).toHaveTextContent('缺失单元格');expect(region).toHaveTextContent('8 个');expect(region).toHaveTextContent('未自动清洗');
  expect(region).not.toHaveTextContent('有效数据 92');
});

it('requires explicit deletion confirmation and blocks approval during the decision',async()=>{
  const current=state();vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current));
  const p=props(current);render(<BusinessPlanReview {...p}/>);await screen.findByText('03 · 请确认分析方向');
  await userEvent.click(screen.getByRole('button',{name:'删除高额记录地区排名'}));
  expect(screen.getByText(/这是核心分析，移除后可能无法回答原问题/)).toBeVisible();
  expect(p.onRemove).not.toHaveBeenCalled();expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
  await userEvent.click(screen.getByRole('button',{name:'保留此方向'}));
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeEnabled();
});

it('saves an actual metric edit and requires the parent to load the new review version',async()=>{
  const current=state();vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current));
  const next={...current,revision:current.revision+1};const save=vi.spyOn(api,'editDirection').mockResolvedValue(next);const onBasisSaved=vi.fn();
  render(<BusinessPlanReview {...props(current)} onBasisSaved={onBasisSaved}/>);
  await userEvent.click(await screen.findByRole('button',{name:'修改此方向：辅助销售汇总'}));
  const form=screen.getByRole('form',{name:'修改辅助销售汇总'});
  await userEvent.selectOptions(within(form).getByLabelText('计算方式 1'),'avg');
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
  await userEvent.click(within(form).getByRole('button',{name:'保存修改并重新审核'}));
  await waitFor(()=>expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0][1]).toBe('A03');expect(JSON.stringify(save.mock.calls[0][2])).toContain('avg');
  expect(onBasisSaved).toHaveBeenCalledWith(next);
});

it('retains the unsaved editor and keeps approval disabled when the server rejects a change',async()=>{
  const current=state();vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current));vi.spyOn(api,'editDirection').mockRejectedValue(new Error('会话已更新，请刷新'));
  render(<BusinessPlanReview {...props(current)} onBasisSaved={vi.fn()}/>);
  await userEvent.click(await screen.findByRole('button',{name:'修改此方向：辅助销售汇总'}));
  await userEvent.click(screen.getByRole('button',{name:'保存修改并重新审核'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('会话已更新');
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
});

it('focuses default review on directions and hides calculation details without hiding gaps',async()=>{
  const current=state();const view=reviewFixture(current);
  view.directions[0].gaps=['需要补充统计口径'];view.can_approve=false;
  vi.spyOn(api,'review').mockResolvedValue(view);
  render(<BusinessPlanReview {...props(current)}/>);
  await screen.findByText('03 · 请确认分析方向');
  expect(screen.queryByText('03 · 分析范围与统计口径')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading',{name:'数据粒度与指标定义'})).not.toBeInTheDocument();
  const note=screen.getAllByText('拟用统计口径：销售额 · 合计')[0];expect(note).not.toBeVisible();
  expect(screen.getByText('需要补充统计口径')).toBeVisible();
  await userEvent.click(screen.getAllByText('查看计算说明')[0]);expect(note).toBeVisible();
  expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
});

it('retains explicit time, exclusion and output requirements visibly instead of folding them away',async()=>{
  const current=state();vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current,{conditions:[
    {label:'时间范围',text:'只看2026年',verification:'已核对分析步骤',source:'constraints.time_range'},
    {label:'筛选范围',text:'排除已取消',verification:'已核对分析步骤',source:'constraints.filters[0]'},
    {label:'分析要求',text:'取前三名',verification:'已核对分析步骤',source:'constraints.analysis_limits[0]'},
    {label:'拟用统计口径',text:'拟用统计口径：销售额 · 合计',verification:'来自当前方案',source:'plan.tasks.A01.steps.S01'},
  ]}));
  render(<BusinessPlanReview {...props(current)}/>);await screen.findByText('03 · 请确认分析方向');
  expect(screen.getByText('时间范围：只看2026年')).toBeVisible();
  expect(screen.getByText('筛选范围：排除已取消')).toBeVisible();
  expect(screen.getByText('分析要求：取前三名')).toBeVisible();
  expect(screen.getAllByText('拟用统计口径：销售额 · 合计').every(el=>!el.closest('details')?.hasAttribute('open'))).toBe(true);
});

it('keeps different task filters visible while the corresponding calculations are collapsed',async()=>{
  const current=state();vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current));
  render(<BusinessPlanReview {...props(current)}/>);await screen.findByText('03 · 请确认分析方向');
  expect(screen.getByLabelText('高额记录地区排名的数据范围')).toHaveTextContent('18000');
  expect(screen.getByLabelText('整体销售额的数据范围')).toHaveTextContent('未设置额外筛选');
  expect(screen.getByLabelText('高额记录地区排名的数据范围')).toBeVisible();
});
