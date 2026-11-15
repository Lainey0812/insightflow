import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { it, expect, vi } from 'vitest';
import App from '../App';
import { api } from '../api/client';
import type { Session } from '../types/contracts';
import fixture from './fixtures/hitl-v1.json';
import {reviewFixture} from './review-fixtures';

function ready(): Session { return {...structuredClone(fixture) as Session, workflow_kind:'real_v1', workflow_events:[{status:'AWAITING_APPROVAL',recorded_at:'2026-10-27T08:00:00Z'}]}; }
function start(current?:Session) {
  vi.spyOn(api,'health').mockResolvedValue({status:'ok',mode:'real',service:'insightflow',version:'0.1.0'});
  vi.spyOn(api,'list').mockResolvedValue(current?[current]:[]);
  vi.spyOn(api,'review').mockResolvedValue(reviewFixture(ready()));
  if(current) {localStorage.setItem('insightflow.session',current.id);vi.spyOn(api,'session').mockResolvedValue(current);}
}
it('new entry requests real_workflow and persists the returned session credentials',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({id:'real-new',review_access_token:'local-test-token'}),{status:201}));
  await api.create(new File(['a\n1'],'data.csv'),'探索数据','exploratory');
  const data=fetch.mock.calls[0][1]?.body as FormData;
  expect(data.get('real_workflow')).toBe('true');expect(data.has('manual_review')).toBe(false);
  expect(localStorage.getItem('insightflow.access.real-new')).toBe('local-test-token');
});
it('restores a preparing session and polls the real plan without showing JSON import',async()=>{
  const current={...ready(),status:'PLANNING' as const,review_plan:null,current_plan_version:null};
  start(current);const next={...ready(),revision:current.revision+5};
  vi.mocked(api.review).mockResolvedValue(reviewFixture(next));
  vi.mocked(api.session).mockResolvedValueOnce(current).mockResolvedValue(next);
  render(<App/>);
  expect(await screen.findByRole('region',{name:'真实流程状态'})).toHaveTextContent('生成计划中');
  expect(screen.queryByLabelText('计划与意图 JSON')).not.toBeInTheDocument();
  await waitFor(()=>expect(screen.getByRole('region',{name:'分析方案 第1版'})).toBeInTheDocument(),{timeout:2500});
  expect(screen.queryByLabelText('修改分析计划')).not.toBeInTheDocument();
});
it('keeps clarification editable even though real review metadata already exists',async()=>{
  const current={...ready(),status:'WAITING_FOR_CLARIFICATION' as const,review_plan:null,current_plan_version:null};
  start(current);const call=vi.spyOn(api,'clarify').mockResolvedValue(ready());
  const legacy=vi.spyOn(api,'revise');render(<App/>);
  await userEvent.type(await screen.findByLabelText('补充分析需求'),'先探索主要差异');
  await userEvent.click(screen.getByRole('button',{name:'发送'}));
  expect(call).toHaveBeenCalledWith(current,'先探索主要差异');expect(legacy).not.toHaveBeenCalled();
  expect(await screen.findByRole('region',{name:'分析方案 第1版'})).toBeInTheDocument();
});
it('sends a review confirmation reply without revising or uploading again',async()=>{
  const current=ready();
  start(current);
  vi.mocked(api.review).mockResolvedValue(reviewFixture(current,{confirmation_questions:['「华东」要包含哪些地区？']}));
  const answer=vi.spyOn(api,'reviewAnswer').mockResolvedValue({...current,revision:current.revision+1,status:'PARSING_INTENT'});
  const revise=vi.spyOn(api,'revise');const create=vi.spyOn(api,'create');
  render(<App/>);
  expect(await screen.findByRole('article',{name:'待确认问题'})).toHaveTextContent('不用重新上传文件');
  await userEvent.type(await screen.findByLabelText('回复确认问题'),'只要华东');
  await userEvent.click(screen.getByRole('button',{name:'发送'}));
  expect(answer).toHaveBeenCalledWith(current,'只要华东');
  expect(revise).not.toHaveBeenCalled();expect(create).not.toHaveBeenCalled();
});
it('offers explicit preparation retry after failure and does not call execution',async()=>{
  const current={...ready(),status:'FAILED' as const,review_plan:null,current_plan_version:null,error:{code:'LLM_TIMEOUT',message:'模型总超时',retryable:true,node_name:'analysis_planner_v1'}};
  start(current);const retry=vi.spyOn(api,'retryPreparation').mockResolvedValue(ready());const execute=vi.spyOn(api,'executeReal');
  render(<App/>);await userEvent.click(await screen.findByRole('button',{name:'重试准备'}));
  expect(retry).toHaveBeenCalledWith(current);expect(execute).not.toHaveBeenCalled();
  expect(await screen.findByRole('region',{name:'分析方案 第1版'})).toBeInTheDocument();
});
it('new upload returns a visible preparing state then polls to saved real review',async()=>{
  start();const current={...ready(),status:'CREATED' as const,review_plan:null,current_plan_version:null,revision:0};
  vi.spyOn(api,'create').mockResolvedValue(current);vi.spyOn(api,'session').mockResolvedValue({...ready(),revision:10});
  vi.mocked(api.review).mockResolvedValue(reviewFixture({...ready(),revision:10}));
  render(<App/>);await screen.findByText('服务已连接');
  await userEvent.type(screen.getByLabelText('分析需求'),'探索销售数据');
  fireEvent.change(screen.getByLabelText('上传数据文件'),{target:{files:[new File(['a\n1'],'data.csv')]}});
  await userEvent.click(screen.getByRole('button',{name:'发送'}));
  expect(await screen.findByRole('region',{name:'真实流程状态'})).toBeInTheDocument();
  expect(localStorage.getItem('insightflow.session')).toBe(current.id);
  await waitFor(()=>expect(screen.getByRole('region',{name:'分析方案 第1版'})).toBeInTheDocument(),{timeout:2500});
});
it('shows unsatisfied core requirements and unverified constraints without approving',async()=>{
  const current=ready();current.review_plan!.validated_plan.coverage_status='blocked';
  current.review_plan!.validated_plan.unmet_core_requirements=[{requirement_id:'C2',description:'缺少薪资解析能力'}];
  current.review_plan!.validated_plan.intent_snapshot.constraints.filters=[{raw_text:'仅上海',validation_status:'unverified'}];
  start(current);vi.mocked(api.review).mockResolvedValue(reviewFixture(current,{can_approve:false,issues:[{code:'MISSING_FIELD',message:'缺少薪资解析能力',next_step:'请补充数据。'},{code:'UNVERIFIED_CONSTRAINTS',message:'仅上海：尚未核对',next_step:'请明确范围。'}]}));const approve=vi.spyOn(api,'approveReal');render(<App/>);
  expect(await screen.findByText('缺少薪资解析能力')).toBeInTheDocument();
  expect(screen.getByText(/仅上海：尚未核对/)).toBeInTheDocument();
  expect(screen.getByRole('button',{name:/确认并开始分析/})).toBeDisabled();expect(approve).not.toHaveBeenCalled();
});
