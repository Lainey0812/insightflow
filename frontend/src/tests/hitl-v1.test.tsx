import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import App from '../App';
import { api } from '../api/client';
import { PlanReviewCard } from '../components/PlanReviewCard';
import { PlanImport } from '../components/PlanImport';
import { ExecutionPreview } from '../components/ExecutionPreview';
import type { Session } from '../types/contracts';
import fixture from './fixtures/hitl-v1.json';
import { reviewFixture } from './review-fixtures';

const initial = fixture as Session;
function state() { return structuredClone(initial); }
function card(current: Session, overrides: Parameters<typeof reviewFixture>[1] = {}, confirm = vi.fn(), remove = vi.fn()) {
  vi.spyOn(api, 'review').mockResolvedValue(reviewFixture(current, overrides));
  render(<PlanReviewCard plan={current.review_plan!} session={current} busy={false} onConfirm={confirm} onRemove={remove}/>);
  return {confirm, remove};
}
it('shows business directions and gaps with technical details collapsed', async () => {
  const current = state();
  const response = reviewFixture(current);
  response.directions[2] = {...response.directions[2], readiness:'暂时无法分析', executable:false, gaps:['缺少利润字段']};
  const {remove} = card(current, response);
  expect(await screen.findByText('缺少利润字段')).toBeInTheDocument();
  expect(screen.getAllByText('补充分析').length).toBeGreaterThan(0);
  expect(screen.getByText('技术详情').closest('details')).not.toHaveAttribute('open');
  expect(screen.queryByText(/辅助销售汇总 · P2 · F0/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', {name: '删除辅助销售汇总'}));
  expect(remove).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button',{name:'确认移除并重新审核'}));
  expect(remove).toHaveBeenCalledWith('A03');
});
it('requires explicit acknowledgement for partial coverage', async () => {
  const current = state();
  const {confirm} = card(current, {warnings:[{id:'partial_coverage',label:'我了解本方案只能回答部分核心问题。'}]});
  const button = screen.getByRole('button', {name: /确认并开始分析/});
  expect(button).toBeDisabled();
  await userEvent.click(await screen.findByRole('checkbox'));
  await userEvent.click(button);
  expect(confirm).toHaveBeenCalledWith(['partial_coverage']);
});
it('obeys server blocked eligibility even with executable optional tasks', async () => {
  const current = state(); card(current, {can_approve:false,coverage:'核心问题目前无法分析',issues:[{code:'COVERAGE_BLOCKED',message:'核心问题目前无法分析。',next_step:'请补充数据或重新提出需求。'}]});
  expect(await screen.findByText('核心问题目前无法分析。')).toBeInTheDocument();
  expect(screen.getByRole('button', {name: /确认并开始分析/})).toBeDisabled();
});
it('shows unresolved conditions with an actionable next step', async () => {
  const current = state(); card(current, {can_approve:false,issues:[{code:'UNVERIFIED_CONSTRAINTS',message:'仅华东：当前步骤未完整满足此条件。',next_step:'请明确范围后重新提出需求。'}]});
  expect(await screen.findByText(/仅华东：当前步骤未完整满足此条件/)).toBeInTheDocument();
  expect(screen.getByText('请明确范围后重新提出需求。')).toBeInTheDocument();
  expect(screen.getByRole('button', {name: /确认并开始分析/})).toBeDisabled();
});
it('retains deletion and describes an implemented transformation without raw enums', async () => {
  const current = state(); const directions = reviewFixture(current).directions;
  directions[0].readiness='完成已支持的数据转换后可分析';card(current,{directions});
  expect(await screen.findByText('完成已支持的数据转换后可分析')).toBeInTheDocument();
  expect(screen.getByRole('button', {name:'删除高额记录地区排名'})).toBeEnabled();
});
it('does not approve invalid JSON and submits an explicit plan to validation', async () => {
  const onSave = vi.fn(); const current = state(); render(<PlanImport session={current} busy={false} onSave={onSave}/>);
  fireEvent.change(screen.getByLabelText('计划与意图 JSON'), {target:{value:'invalid'}});
  await userEvent.click(screen.getByRole('button', {name:'保存并调用 Validator'}));
  expect(screen.getByRole('alert')).toHaveTextContent('有效的 JSON'); expect(onSave).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('计划与意图 JSON'), {target:{value:JSON.stringify({plan:current.review_plan!.validated_plan.plan, intent:current.review_plan!.validated_plan.intent_snapshot})}});
  await userEvent.click(screen.getByRole('button', {name:'保存并调用 Validator'})); expect(onSave).toHaveBeenCalledOnce();
});
it('renders the real persisted engine preview and failures', async () => {
  vi.spyOn(api,'execution').mockResolvedValue({execution_id:'exec_test',approval_id:'approval_test',plan_id:'sales',plan_version:2,dataset_id:'dataset',dataset_version:'hash',execution_status:'partial_success',warnings:[],tasks:[
    {task_id:'A01',status:'success',failure_reason:null,row_count:1,result:{result_id:'result_test',rows:[{region:'华东',amount:157000}],columns:[{field:'region',label:'地区',logical_type:'text',role:'dimension',unit:null},{field:'amount',label:'销售额',logical_type:'number',role:'metric',unit:null}],truncated:false,total_result_rows:1}},
    {task_id:'A02',status:'failed',failure_reason:'真实内核失败',row_count:0,result:null},
  ]});
  render(<ExecutionPreview executionId="exec_test" sessionId={initial.id}/>);
  expect(await screen.findByRole('cell',{name:'157000'})).toBeInTheDocument();
  expect(screen.getByText('真实内核失败')).toBeInTheDocument();
  expect(api.execution).toHaveBeenCalledWith('exec_test',initial.id);
});
it('confirmation in the real chat uses approval plus engine and refreshes saved state', async () => {
  const current = state(); const approved: Session = {...current,status:'APPROVED',review_status:'approved'};
  localStorage.setItem('insightflow.session',current.id);
  vi.spyOn(api,'health').mockResolvedValue({status:'ok',mode:'real',service:'insightflow',version:'0.1.0'});
  vi.spyOn(api,'list').mockResolvedValue([current]);
  vi.spyOn(api,'session').mockResolvedValue(current);
  const approve = vi.spyOn(api,'approveReal').mockResolvedValue(approved);
  const engine = vi.spyOn(api,'executeReal').mockResolvedValue({} as never);
  const legacy = vi.spyOn(api,'execute');
  vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current));
  render(<App/>);
  await userEvent.click(await screen.findByRole('button',{name:/确认并开始分析/}));
  await waitFor(() => expect(engine).toHaveBeenCalledWith(approved));
  expect(approve).toHaveBeenCalledWith(current,[]);
  expect(legacy).not.toHaveBeenCalled();
});

it.each([
  { issue: '样本范围有限', reason: '需要谨慎解释' },
  { description: '样本范围有限', impact: '需要谨慎解释' },
])('retains uncertainty text and warning IDs across Intent wire versions: %j', async (names) => {
  const current = state();
  current.review_plan!.validated_plan.intent_snapshot.uncertainties = [
    { id: 'U1', action: 'annotate', resolve_at: 'plan_approval', ...names },
  ];
  const {confirm} = card(current, {warnings:[{id:'uncertainty_U1',label:'样本范围有限；影响：需要谨慎解释'}]});
  expect(await screen.findByText(/样本范围有限；影响：需要谨慎解释/)).toBeInTheDocument();
  expect(screen.getByRole('button', {name: /确认并开始分析/})).toBeDisabled();
  await userEvent.click(screen.getByRole('checkbox'));
  await userEvent.click(screen.getByRole('button', {name: /确认并开始分析/}));
  expect(confirm).toHaveBeenCalledWith(['uncertainty_U1']);
});
