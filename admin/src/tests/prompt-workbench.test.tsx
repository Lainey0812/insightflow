import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { PromptWorkbenchPage } from '../pages/PromptWorkbenchPage';
import { promptApi } from '../api/prompts';
import { workbenchApi } from '../api/promptWorkbench';
vi.mock('../api/prompts');
vi.mock('../api/promptWorkbench');
const summary={template_snapshot_id:'pt_current',node_id:'intent_parser' as const,version:'intent-current',content_hash:'123',created_at:'2026-11-15T00:00:00Z',source_commit:null,provenance:'runtime_source_verified',change_summary:'original'};
const newer={...summary,template_snapshot_id:'pt_newer',version:'newer-debug'};
const state={latest_registered:newer,runtime_snapshot_id:'pt_current',runtime_registration:'registered' as const};
beforeEach(()=>{
  vi.resetAllMocks();
  vi.mocked(promptApi.catalog).mockResolvedValue({items:[{...state,node_id:'intent_parser',prompt_id:'intent_parser',label:'Intent Parser',version_count:2}],notice:''});
  vi.mocked(promptApi.history).mockResolvedValue({...state,prompt_id:'intent_parser',label:'Intent Parser',items:[newer,summary],total:2,limit:20,offset:0});
  vi.mocked(promptApi.detail).mockImplementation(async (_node,id)=>({...state,availability:'available',variables_schema_availability:'unavailable',variables_notice:'',template:{...(id==='pt_current'?summary:newer),system_template:id==='pt_current'?'CURRENT SYSTEM':'NEWER SYSTEM',user_composition:{retry_instructions:['retry']},output_schema_definition:{},source_files:{}}}));
  vi.mocked(promptApi.calls).mockResolvedValue({items:[],total:0,offset:0,limit:20});
  vi.mocked(workbenchApi.tests).mockResolvedValue({items:[],total:0,offset:0,limit:20,notice:'only exact links'});
});
function view(query=''){return render(<MemoryRouter initialEntries={['/prompts'+query]}><PromptWorkbenchPage/></MemoryRouter>);}
it('shows all LLM nodes, current version and current text rather than latest registered',async()=>{
  view();await screen.findByDisplayValue('CURRENT SYSTEM');
  expect(screen.getByRole('heading',{name:'intent-current'})).toBeVisible();
  expect(screen.getByRole('complementary',{name:'LLM 节点目录'})).toHaveTextContent('洞察生成');
  expect(screen.getByRole('tab',{name:'编辑'})).toHaveAttribute('aria-selected','true');
});
it('takes edited content into single debug and requires an explicit run',async()=>{
  vi.mocked(workbenchApi.run).mockResolvedValue({test_id:'pdt_real',node_id:'intent_parser',case_name:'case1',created_at:'now',input_hash:'hash',schema_hash:'schema',sides:[],results:[{template_snapshot_id:'pt_draft',operation_id:'op',status:'succeeded',calls:[],output:'{"ok":true}',json_valid:true}],notice:'isolated'});
  view();const editor=await screen.findByDisplayValue('CURRENT SYSTEM');
  fireEvent.change(editor,{target:{value:'EDITED SYSTEM'}});
  fireEvent.click(screen.getByRole('button',{name:/调试此草稿/}));
  expect(screen.getByRole('tab',{name:'单独调试'})).toHaveAttribute('aria-selected','true');
  expect(workbenchApi.run).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('测试名称'),{target:{value:'case1'}});
  fireEvent.change(screen.getByLabelText('调试输入'),{target:{value:'synthetic'}});
  fireEvent.click(screen.getByRole('button',{name:'运行调试'}));
  await screen.findByText('pdt_real');
  expect(workbenchApi.run).toHaveBeenCalledWith(expect.objectContaining({draft_system:'EDITED SYSTEM',instruction:'synthetic',snapshot_ids:['pt_current']}),'','');
});
it('requires different versions for diff and sends the same one test input',async()=>{
  vi.mocked(promptApi.compare).mockResolvedValue({left:summary,right:newer,sections:[],content_hash_equal:false,notice:''});
  vi.mocked(workbenchApi.run).mockResolvedValue({test_id:'pdt_diff',node_id:'intent_parser',case_name:'diff',created_at:'now',input_hash:'hash',schema_hash:'schema',sides:[],results:[],notice:'same input'});
  view('?tab=debug&mode=diff&left=pt_current&right=pt_current');await screen.findByLabelText('左侧版本');
  await screen.findAllByRole('option',{name:'newer-debug'});
  expect(screen.getByRole('button',{name:'运行两个版本'})).toBeDisabled();
  fireEvent.change(screen.getByLabelText('右侧版本'),{target:{value:'pt_newer'}});
  fireEvent.change(screen.getByLabelText('测试名称'),{target:{value:'diff'}});
  fireEvent.change(screen.getByLabelText('调试输入'),{target:{value:'identical test'}});
  fireEvent.click(screen.getByRole('button',{name:'运行两个版本'}));
  await waitFor(()=>expect(workbenchApi.run).toHaveBeenCalledWith(expect.objectContaining({snapshot_ids:['pt_current','pt_newer'],instruction:'identical test'}),'',''));
});
it('shows missing runtime honestly instead of editing newest history silently',async()=>{
  vi.mocked(promptApi.catalog).mockResolvedValue({items:[{...state,prompt_id:'intent_parser',node_id:'intent_parser',label:'Intent',version_count:2,runtime_snapshot_id:null,runtime_registration:'unknown'}],notice:''});
  view();await screen.findByRole('heading',{name:'unknown'});
  expect(screen.queryByDisplayValue('NEWER SYSTEM')).not.toBeInTheDocument();
});
it('filters associated tests by exact version and distinguishes production calls',async()=>{
  view('?tab=related&version=pt_current');await screen.findByText('only exact links');
  expect(workbenchApi.tests).toHaveBeenCalledWith('intent_parser','pt_current',0,expect.any(AbortSignal));
  expect(screen.getByText(/普通分析调用不冒充评测案例/)).toBeVisible();
  fireEvent.change(screen.getByLabelText('筛选 Prompt 版本'),{target:{value:'pt_newer'}});
  await waitFor(()=>expect(workbenchApi.tests).toHaveBeenLastCalledWith('intent_parser','pt_newer',0,expect.any(AbortSignal)));
});
it('history expands stored content and keeps old version links',async()=>{
  view('?tab=history');await screen.findByText('newer-debug');
  const table=screen.getByRole('table',{name:'Prompt 历史版本'});
  expect(table).toHaveTextContent('版本号');
  expect(table).toHaveTextContent('登记时间');
  expect(table).toHaveTextContent('当前运行时');
  fireEvent.click(screen.getAllByText('查看完整 Prompt 内容')[0]);
  await screen.findByText('NEWER SYSTEM');
  expect(screen.getByRole('button',{name:'收起 Prompt 内容'})).toHaveAttribute('aria-expanded','true');
  fireEvent.click(screen.getByRole('button',{name:'收起 Prompt 内容'}));
  expect(screen.queryByText('NEWER SYSTEM')).not.toBeInTheDocument();
  expect(screen.getAllByRole('link',{name:'完整版本详情'})[0]).toHaveAttribute('href','/prompts/intent_parser/versions/pt_newer');
});
