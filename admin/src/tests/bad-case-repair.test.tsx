import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { badCaseApi } from '../api/badCases';
import { promptApi } from '../api/prompts';
import type { BadCase, BadCaseSummary } from '../types/badCases';
import fixture from './fixtures/workflow-c2.json';
vi.mock('../api/badCases',async original=>({...await original<typeof import('../api/badCases')>(),badCaseApi:{list:vi.fn(),get:vi.fn(),attribute:vi.fn(),saveRepairDraft:vi.fn(),completeRepair:vi.fn(),transition:vi.fn()}}));
vi.mock('../api/prompts');
const summary:BadCaseSummary={case_id:'bc_repair',workflow_id:fixture.workflow_id,span_id:null,node_name:null,category:'insight',severity:'high',title:'修复样例',created_at:'2026-11-16T00:00:00Z',created_by:'tester',business_status:'succeeded',status:'open',sequence:1,updated_at:'2026-11-16T00:00:00Z'};
let current:BadCase;
const template={template_snapshot_id:'pt_current',node_id:'intent_parser' as const,version:'intent-current',content_hash:'hash',created_at:'now',source_commit:null,provenance:'runtime_source_verified',change_summary:'original'};
beforeEach(()=>{
  vi.resetAllMocks();
  current={...summary,schema_version:'bad-case-v1',observed:'测试问题',expected:'正确结果',evidence_intact:true,evidence_sha256:'abc',evidence_notice:'frozen',events:[{event_id:'e1',sequence:1,created_at:summary.created_at,kind:'created',status:'open',note:'',annotator:'tester'}],evidence:{schema_version:'bad-case-evidence-v1',workflow_id:fixture.workflow_id,root_run_id:fixture.root_run_id,business_lifecycle:{status:'succeeded',execution_status:'success',report_status:'complete',goal_coverage:'complete'},failure:null,quality:null,consistency:{status:'consistent',issues:[]},collection_status:'observed',nodes:[],llm_calls:[],replay_refs:{}}};
  vi.mocked(badCaseApi.get).mockImplementation(async()=>current);
  vi.mocked(badCaseApi.list).mockImplementation(async()=>({schema_version:'bad-case-page-v1',items:[{...summary,status:current.status,sequence:current.sequence,attribution:current.attribution}],total:1,limit:20,offset:0}));
  vi.mocked(badCaseApi.attribute).mockImplementation(async(_id,body)=>{current={...current,status:'in_progress',sequence:2,attribution:{cause:body.cause,node_id:body.node_id,explanation:body.explanation}};return current;});
  const state={latest_registered:template,runtime_registration:'registered' as const,runtime_snapshot_id:'pt_current'};
  vi.mocked(promptApi.catalog).mockResolvedValue({items:[{...state,prompt_id:'intent_parser',node_id:'intent_parser',label:'Intent',version_count:1}],notice:''});
  vi.mocked(promptApi.history).mockResolvedValue({...state,prompt_id:'intent_parser',label:'Intent',items:[template],total:1,limit:20,offset:0});
  vi.mocked(promptApi.detail).mockResolvedValue({...state,template:{...template,system_template:'original prompt',user_composition:{},output_schema_definition:{},source_files:{}},availability:'available',variables_notice:'',variables_schema_availability:'unavailable'});
  vi.mocked(badCaseApi.saveRepairDraft).mockResolvedValue({template_snapshot_id:'pt_repair'});
  vi.mocked(badCaseApi.completeRepair).mockImplementation(async()=>{current={...current,status:'pending_verification',sequence:3,repair:{template_snapshot_id:'pt_repair',node_id:'intent_parser'}};return current;});
});
function view(path:string){render(<MemoryRouter initialEntries={[path]}><AdminRoutes/></MemoryRouter>);}
function fillAttribution(form:HTMLElement){fireEvent.change(within(form).getByLabelText('归因原因'),{target:{value:'prompt'}});fireEvent.change(within(form).getByLabelText('修复节点'),{target:{value:'intent_parser'}});fireEvent.change(within(form).getByLabelText('操作人'),{target:{value:'tester'}});fireEvent.change(within(form).getByLabelText('归因说明'),{target:{value:'缺少明确规则'}});}
it('supports inline attribution in the list and persists processing status',async()=>{
  view('/bad-cases');await screen.findByText('未提交归因');
  fireEvent.click(screen.getByText('编辑归因判断'));
  const form=screen.getByRole('form',{name:'归因判断：修复样例'});fillAttribution(form);
  expect(badCaseApi.attribute).not.toHaveBeenCalled();
  fireEvent.click(within(form).getByRole('button',{name:'确认提交归因'}));
  await screen.findByText('处理中',{selector:'.bc-status'});
  expect(badCaseApi.attribute).toHaveBeenCalledWith('bc_repair',expect.objectContaining({expected_sequence:1,cause:'prompt',node_id:'intent_parser'}),'');
});
it('submitting attribution in detail exposes the exact Prompt repair route',async()=>{
  view('/bad-cases/bc_repair');const form=await screen.findByRole('form',{name:'归因判断：修复样例'});fillAttribution(form);
  fireEvent.click(within(form).getByRole('button',{name:'确认提交归因'}));
  const link=await screen.findByRole('link',{name:'立即修复'});
  expect(link).toHaveAttribute('href','/prompts?node=intent_parser&tab=edit&bad_case=bc_repair');
});
it('saves a changed repair draft before completing and returns to pending verification detail',async()=>{
  current={...current,status:'in_progress',sequence:2,attribution:{cause:'prompt',node_id:'intent_parser',explanation:'缺少规则'}};
  view('/prompts?node=intent_parser&tab=edit&bad_case=bc_repair');
  await waitFor(()=>expect(screen.getByRole('region',{name:'Bad Case 修复来源'})).toHaveTextContent('修复样例'));
  const editor=await screen.findByDisplayValue('original prompt');
  expect(screen.getByRole('button',{name:'确认修复并返回待验证'})).toBeDisabled();
  fireEvent.change(editor,{target:{value:'fixed prompt'}});fireEvent.change(screen.getByLabelText('修复操作人'),{target:{value:'tester'}});
  fireEvent.click(screen.getByRole('button',{name:'确认修复并返回待验证'}));
  await screen.findByText('待验证',{selector:'.bc-status'});
  expect(badCaseApi.saveRepairDraft).toHaveBeenCalledWith('bc_repair',{base_snapshot_id:'pt_current',system_prompt:'fixed prompt',expected_sequence:2},'');
  expect(badCaseApi.completeRepair).toHaveBeenCalledWith('bc_repair',expect.objectContaining({template_snapshot_id:'pt_repair',expected_sequence:2}),'');
});
it('a stale repair stays on the editor and never pretends the case was submitted',async()=>{
  current={...current,status:'in_progress',sequence:2,attribution:{cause:'prompt',node_id:'intent_parser',explanation:'缺少规则'}};
  vi.mocked(badCaseApi.completeRepair).mockRejectedValue(new Error('版本冲突，提交未完成'));
  view('/prompts?node=intent_parser&tab=edit&bad_case=bc_repair');const editor=await screen.findByDisplayValue('original prompt');
  fireEvent.change(editor,{target:{value:'fixed prompt'}});fireEvent.change(screen.getByLabelText('修复操作人'),{target:{value:'tester'}});fireEvent.click(screen.getByRole('button',{name:'确认修复并返回待验证'}));
  await screen.findByText('版本冲突，提交未完成');
  expect(screen.getByRole('textbox',{name:'System Prompt 编辑器'})).toHaveValue('fixed prompt');
  expect(current.status).toBe('in_progress');
});
