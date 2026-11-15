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
  expect(await screen.findByRole('region',{name:'报告生成容量'})).toHaveTextContent(view.report_capacity.message);
  expect(screen.getByRole('button',{name:'确认并开始分析'}).hasAttribute('disabled')).toBe(!supported);
});
