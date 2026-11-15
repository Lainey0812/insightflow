// Frozen real C2 response; modified copies are isolated component fault fixtures, never browser/server data.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { isWorkflow, workflowApi } from '../api/workflows';
import type { WorkflowView } from '../types/workflows';
import fixture from './fixtures/workflow-c2.json';
const source=()=>structuredClone(fixture) as unknown as WorkflowView;
function page(items:unknown[]=[source()]) {return {schema_version:'workflow-observability-page-v1',items,total:items.length,limit:20,offset:0,sort:'created_at DESC, workflow_id ASC',notice:'readonly'};}
function view(path:string) {render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>);}
function response(value:unknown,status=200) {return new Response(JSON.stringify(value),{status,headers:{'content-type':'application/json'}});}

it('uses the frozen real C2 sample for list-to-detail and fourteen actual nodes',async()=>{
  const fetcher=vi.fn(async(input:RequestInfo|URL,_init?:RequestInit)=>response(String(input).includes('/workflow-observability/'+fixture.workflow_id)?source():page()));vi.stubGlobal('fetch',fetcher);
  view('/traces/workflows');
  fireEvent.click(await screen.findByRole('link',{name:'查看详情'}));
  expect(await screen.findByRole('heading',{name:'完整 Workflow'})).toBeVisible();
  expect(screen.getAllByTestId('workflow-node')).toHaveLength(14);
  expect(screen.queryByRole('button',{name:/批准|开始分析|恢复执行|重试分析/})).not.toBeInTheDocument();
  const opened=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(opened).getByRole('heading',{name:'数据画像'})).toBeVisible();
  expect(within(opened).getByRole('tab',{name:'Input'})).toBeVisible();
  expect(within(opened).getByRole('tab',{name:'Output'})).toBeVisible();
  expect(within(opened).queryByRole('tab',{name:'API Request/Response'})).not.toBeInTheDocument();
  expect(within(opened).queryByRole('tab',{name:'Prompt & Model'})).not.toBeInTheDocument();
  expect(within(opened).queryByText('错误详情')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/分析执行/}));
  const detail=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(detail).getByRole('heading',{name:'分析执行'})).toBeVisible();
  expect(within(detail).getByRole('tab',{name:'Input'})).toBeVisible();
  expect(within(detail).getByRole('tab',{name:'Output'})).toBeVisible();
  expect(within(detail).queryByRole('tab',{name:'LLM'})).not.toBeInTheDocument();
  fireEvent.click(within(detail).getByRole('tab',{name:'Output'}));
  expect(within(detail).getAllByText(fixture.trace.executions[0].execution_id).length).toBeGreaterThan(0);
  expect(fetcher.mock.calls.every(([,init])=>!init||init.method===undefined||init.method==='GET')).toBe(true);
});

it('paginates the workflow list without query filters or a control API',async()=>{
  const fetcher=vi.fn(async(_input:RequestInfo|URL)=>response({...page(),total:21}));vi.stubGlobal('fetch',fetcher);
  view('/traces/workflows');await screen.findByText('21 条真实 Workflow');
  expect(screen.queryByRole('button',{name:'查询'})).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Workflow ID')).not.toBeInTheDocument();
  await waitFor(()=>expect(screen.getByRole('button',{name:'下一页'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'下一页'}));
  await waitFor(()=>expect(String(fetcher.mock.calls.at(-1)?.[0])).toContain('offset=20'));
});

it('keeps delivered business status when Trace is unavailable without fabricating nodes',async()=>{
  const data=source();data.trace!.nodes=[];data.trace!.events=[];data.trace!.llm_calls=[];
  data.collection.status='incomplete';data.collection.findings=[{category:'executed_trace_missing',code:'EXECUTION_SPAN_NOT_COLLECTED',evidence_refs:[fixture.trace.executions[0].execution_id]}];
  vi.stubGlobal('fetch',vi.fn(async()=>response(data)));view('/traces/workflows/'+fixture.workflow_id);
  expect(await screen.findByText('暂无可读取的实际节点')).toBeVisible();
  expect(screen.queryAllByTestId('workflow-node')).toHaveLength(0);
  expect(screen.queryByText('已执行，Trace 缺失')).not.toBeInTheDocument();
});

it('distinguishes explicit skip, incomplete observation, inconsistency and unknown',async()=>{
  const data=source();data.collection.findings=[
    {category:'not_executed',code:'NO_EVIDENCE',evidence_refs:['unit_skip_event']},
    {category:'observation_incomplete',code:'RECORDED_COLLECTION_GAP',evidence_refs:[]},
    {category:'inconsistent',code:'WORKFLOW_TRACE_IDENTITY_MISMATCH',evidence_refs:[]},
    {category:'unknown',code:'ROOT_NOT_COLLECTED',evidence_refs:[]}];data.collection.status='incomplete';
  vi.stubGlobal('fetch',vi.fn(async()=>response(data)));view('/traces/workflows/'+fixture.workflow_id);
  expect(await screen.findByRole('heading',{name:'完整 Workflow'})).toBeVisible();
  expect(screen.getAllByTestId('workflow-node')).toHaveLength(14);
  expect(screen.queryByText('明确未执行')).not.toBeInTheDocument();
});

it('renders retry metadata and events without an executable retry button',async()=>{
  const data=source();data.trace!.llm_calls[0].retry_index=1;data.trace!.llm_calls[0].retry_of_call_id='call_unit_previous';
  vi.stubGlobal('fetch',vi.fn(async()=>response(data)));view('/traces/workflows/'+fixture.workflow_id);
  await screen.findAllByTestId('workflow-node');
  fireEvent.click(screen.getByRole('button',{name:/需求理解/}));
  const detail=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(detail).getByRole('heading',{name:'需求理解'})).toBeVisible();
  expect(within(detail).getByRole('tab',{name:'Output'})).toHaveAttribute('aria-selected','true');
  fireEvent.click(within(detail).getByRole('tab',{name:'LLM'}));
  expect(within(detail).getByText(/请求重试 #1/)).toBeVisible();
  expect(within(detail).getByText(/call_unit_previous/)).toBeVisible();
  expect(within(detail).queryByRole('tab',{name:'Prompt & Model'})).not.toBeInTheDocument();
  fireEvent.click(within(detail).getByRole('tab',{name:'Output'}));
  expect(await within(detail).findByText('没有已保留的结构化输出。')).toBeVisible();
});
it('shows retrieval chunks only on a retrieval node',async()=>{
  const data=source();const node=data.trace!.nodes[0];
  node.name='retriever';
  node.attributes={node_type:'rag',query_string:'检索词',top_k:4,retrieved_chunks:[{text:'切片甲',source_file_name:'orders.csv',score:0.82}]};
  vi.stubGlobal('fetch',vi.fn(async()=>response(data)));view('/traces/workflows/'+fixture.workflow_id);
  const detail=await screen.findByRole('complementary',{name:'节点详情'});
  expect(within(detail).getByText('知识库检索')).toBeVisible();
  fireEvent.click(within(detail).getByRole('tab',{name:'Knowledge Chunks'}));
  expect(within(detail).getByText('切片甲')).toBeVisible();
  expect(within(detail).getByText(/orders.csv/)).toBeVisible();
  expect(within(detail).getByText(/0\.82/)).toBeVisible();
  expect(within(detail).queryByRole('tab',{name:'Prompt & Model'})).not.toBeInTheDocument();
});
it('loads the retained model text and the dataset profile parameters',async()=>{
  const data=source();
  const profiler=data.trace!.nodes.find(node=>node.name==='data_profiler')!;
  profiler.attributes={...profiler.attributes,dataset_id:'dataset_unit',dataset_version:'a'.repeat(64)};
  const call=data.trace!.llm_calls.find(item=>item.node_id==='intent_parser')!;
  const summary={call:{...call,outcome_scope:'provider_protocol',retry_reason:null,error_code:null,started_at:'2026-10-29T00:00:00Z',finished_at:null},request_snapshot:{request_snapshot_id:call.request_snapshot_id,template_snapshot_id:call.template_snapshot_id,messages_hash:'h',schema_hash:'h',request_hash:'h',model_parameters:{model:'unit-model',temperature:0.2},client_config:{timeout_seconds:30},created_at:'',expires_at:null},provider_observation:{endpoint:'https://llm.example.test/v1/chat/completions'},trace_available:true,raw_availability:'retained',response_availability:'retained',redaction:{messages:'hidden'}};
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
    const url=String(input);
    if(url.endsWith('/request'))return response({request_snapshot_id:call.request_snapshot_id,payload:{messages:[{role:'system',content:'SYS_MARKER'},{role:'user',content:'USER_MARKER'}]}});
    if(url.endsWith('/response'))return response({call_id:call.call_id,call_status:'succeeded',error_code:null,kind:'content',content:'RAW_MARKER',truncated:false,content_sha256:'abc'});
    if(url.endsWith('/summary'))return response(summary);
    if(url.includes('/profile'))return response({dataset_id:'dataset_unit',dataset_version:'a'.repeat(64),file_format:'csv',row_count:60,column_count:1,options:{header_row:5,encoding:'utf-8-sig',delimiter:',',sheet_name:null},fields:[{field_id:'field_0001',position:1,display_name:'城市',physical_type:'string',logical_type:'text',missing_count:1,missing_rate:1,non_missing_count:0,unique_count:0,samples:[{value:'HIDDEN_CELL'}]}],quality_issues:[{code:'EMPTY_COLUMNS',severity:'warning',message:'空列',affected_count:1,field_ids:['field_0001'],example_row_numbers:[2]}]});
    return response(data);
  }));
  view('/traces/workflows/'+fixture.workflow_id);
  const detail=await screen.findByRole('complementary',{name:'节点详情'});
  expect(await within(detail).findByText('表头行')).toBeVisible();
  expect(within(detail).getByText('表头行').nextElementSibling).toHaveTextContent('5');
  expect(detail).toHaveTextContent('行数 60');
  expect(detail).toHaveTextContent('质量信号 1');
  fireEvent.click(within(detail).getByRole('tab',{name:'Output'}));
  expect(within(detail).getByText('城市')).toBeVisible();
  expect(within(detail).getByText('EMPTY_COLUMNS')).toBeVisible();
  expect(within(detail).queryByText('HIDDEN_CELL')).not.toBeInTheDocument();
  expect(within(detail).queryByRole('tab',{name:'API Request/Response'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/需求理解/}));
  fireEvent.click(within(screen.getByRole('complementary',{name:'节点详情'})).getByRole('tab',{name:'LLM'}));
  expect(await screen.findByText(/SYS_MARKER/)).toBeVisible();
  expect(screen.getByText(/USER_MARKER/)).toBeVisible();
  expect(screen.getByText('RAW_MARKER')).toBeVisible();
  expect(screen.getByText('unit-model')).toBeVisible();
  expect(screen.getByText('https://llm.example.test/v1/chat/completions')).toBeVisible();
});
it('keeps the snapshot form when the saved model text is locked',async()=>{
  const data=source();
  const call=data.trace!.llm_calls.find(item=>item.node_id==='intent_parser')!;
  const summary={call:{...call,outcome_scope:'provider_protocol',retry_reason:null,error_code:null,started_at:'2026-10-29T00:00:00Z',finished_at:null},request_snapshot:null,trace_available:false,raw_availability:'retained',response_availability:'retained',redaction:{messages:'hidden'}};
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>response(String(input).includes('/llm-calls/')?summary:data,String(input).includes('/llm-calls/')&&!String(input).endsWith('/summary')?403:200)));
  view('/traces/workflows/'+fixture.workflow_id);
  fireEvent.click(await screen.findByRole('button',{name:/需求理解/}));
  fireEvent.click(within(screen.getByRole('complementary',{name:'节点详情'})).getByRole('tab',{name:'LLM'}));
  expect(await screen.findByLabelText('快照读取凭证')).toBeVisible();
  expect(screen.queryByText('SYS_MARKER')).not.toBeInTheDocument();
});
it('shows intent input, output and associated calls without another run',async()=>{
  const data=source();
  const node=data.trace!.nodes.find(item=>item.name==='intent_parser')!;
  node.intent_result={user_query:'FALLBACK_QUERY',clarification_answers:['补充甲'],dataset_ref:{dataset_id:'dataset_saved',dataset_version:'b'.repeat(64)},analysis_mode:'goal_driven',next_action:'proceed',analysis_goal:{analysis_object:'对象甲',business_goal:'目标甲',decision_goal:null},constraints:{time_range:null,filters:[],metric_requirements:[],analysis_limits:[]},uncertainties:[],clarification_questions:[]};
  const call=data.trace!.llm_calls.find(item=>item.node_id==='intent_parser')!;
  const retry={...call,call_id:'call_retry_unit',call_sequence:2,retry_index:1,retry_of_call_id:call.call_id,status:'failed',error_code:'INTENT_SCHEMA_INVALID',duration_ms:10};
  data.trace!.llm_calls.push(retry);
  const instruction={user_query:'QUERY_MARKER',clarification_answers:[],dataset_context:{dataset_name:'file',row_count:48,sample_rows:[],columns:[{field_id:'field_0001',name:'城市',physical_type:'string',logical_type:'text'}]}};
  const output={analysis_mode:'exploratory',next_action:'proceed',analysis_goal:{analysis_object:'对象乙',business_goal:'目标乙',decision_goal:null},constraints:{time_range:null,filters:[{raw_text:'CONSTRAINT_MARKER',validation_status:'unverified'}],metric_requirements:[],analysis_limits:[]},uncertainties:[],clarification_questions:[]};
  const summary=(item:typeof call & {error_code?:string|null},availability:'retained'|'expired')=>({call:{...item,outcome_scope:'provider_protocol',retry_reason:null,error_code:item.error_code??null,started_at:'2026-10-29T00:00:00Z',finished_at:'2026-10-29T00:00:02Z'},request_snapshot:{request_snapshot_id:item.request_snapshot_id,template_snapshot_id:item.template_snapshot_id,messages_hash:'h',schema_hash:'h',request_hash:'h',model_parameters:{model:'unit-model',temperature:0.7,top_p:0.8,max_tokens:8192},client_config:{timeout_seconds:30},created_at:'',expires_at:null},provider_observation:{input_tokens:11,output_tokens:7},trace_available:true,raw_availability:availability,response_availability:availability,redaction:{messages:'hidden'}});
  const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
    const url=String(input);
    if(url.includes('/call_retry_unit/summary'))return response(summary(retry,'expired'));
    if(url.endsWith('/summary'))return response(summary(call,'retained'));
    if(url.endsWith('/request'))return response({request_snapshot_id:call.request_snapshot_id,payload:{messages:[{role:'system',content:'SYS'},{role:'user',content:JSON.stringify(instruction)}]}});
    if(url.endsWith('/response'))return response({call_id:call.call_id,call_status:'succeeded',error_code:null,kind:'content',content:JSON.stringify(output),truncated:false,content_sha256:'abc'});
    if(url.includes('/versions/'))return response({template:{version:'intent-v1.3.3',template_snapshot_id:call.template_snapshot_id,node_id:'intent_parser',system_template:'s',user_composition:{},source_files:{prompt:{source:'unit'}}}});
    return response(data);
  });
  vi.stubGlobal('fetch',fetcher);
  view('/traces/workflows/'+fixture.workflow_id);
  fireEvent.click(await screen.findByRole('button',{name:/需求理解/}));
  const detail=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(detail).getByRole('tab',{name:'Output'})).toHaveAttribute('aria-selected','true');
  expect(await within(detail).findByText('目标乙')).toBeVisible();
  expect(within(detail).getByText('CONSTRAINT_MARKER')).toBeVisible();
  expect(within(detail).getByText('未给出')).toBeVisible();
  expect(within(detail).queryByText('操作符')).not.toBeInTheDocument();
  expect(within(detail).queryByText('FALLBACK_QUERY')).not.toBeInTheDocument();
  const reads=fetcher.mock.calls.length;
  fireEvent.click(within(detail).getByRole('tab',{name:'Input'}));
  expect(within(detail).getByText('QUERY_MARKER')).toBeVisible();
  expect(within(detail).getByText(/未传入质量信号/)).toBeVisible();
  expect(within(detail).getByText(/城市 · text · string/)).toBeVisible();
  fireEvent.click(within(detail).getByRole('tab',{name:'LLM'}));
  expect(within(detail).getByText(call.call_id)).toBeVisible();
  expect(within(detail).getByText('call_retry_unit')).toBeVisible();
  expect(within(detail).getByText('INTENT_SCHEMA_INVALID')).toBeVisible();
  expect(within(detail).getByText(/模型原始返回未保留或已过期/)).toBeVisible();
  expect(within(detail).getAllByText('11').length).toBeGreaterThan(0);
  expect(within(detail).getAllByText('intent-v1.3.3').length).toBeGreaterThan(0);
  fireEvent.click(within(detail).getByRole('tab',{name:'Output'}));
  expect(fetcher.mock.calls.length).toBe(reads);
});
it('shows planner input, tasks and calls without treating feasibility as approval',async()=>{
  const data=source();
  const node=data.trace!.nodes.find(item=>item.name==='analysis_planner')!;
  const call=data.trace!.llm_calls.find(item=>item.node_id==='analysis_planner')!;
  const retry={...call,call_id:'call_plan_retry',call_sequence:2,retry_index:1,retry_of_call_id:call.call_id,status:'failed',error_code:'PLANNER_INVALID_JSON',duration_ms:12};
  data.trace!.llm_calls.push(retry);
  node.planner_result={approval_required:true,coverage_status:'complete',executable_task_ids:['T01'],blocked_task_ids:[],unmet_core_requirements:[],intent_snapshot:{analysis_mode:'exploratory',next_action:'proceed',analysis_goal:{analysis_object:'对象',business_goal:'GOAL_MARKER',decision_goal:null},constraints:{time_range:null,filters:[],metric_requirements:[],analysis_limits:[]},uncertainties:[]},plan:{plan_id:'plan_unit',plan_version:1,tasks:[{task_id:'T01',title:'TASK_MARKER',business_question:'QUESTION_MARKER',priority:'P0',priority_reason:'核心问题',requirement_ids:['C01'],depends_on:[],missing_inputs:[],steps:[{step_id:'S01',operation:'aggregate',params:{field:'field_0001'}}]}],core_requirements:[{requirement_id:'C01',description:'GOAL_MARKER'}]},validation_results:[{task_id:'T01',feasibility:'F2',reason_code:'READY',validation_issues:[],executable:true}]};
  const instruction={intent:{analysis_mode:'exploratory',next_action:'proceed',analysis_goal:{analysis_object:'对象',business_goal:'GOAL_MARKER',decision_goal:null},constraints:{time_range:null,filters:[{raw_text:'CONSTRAINT_PLAN',validation_status:'unverified'}],metric_requirements:[],analysis_limits:[]},uncertainties:[]},core_requirements:[{requirement_id:'C01',description:'GOAL_MARKER'}],profile:{dataset_id:'dataset_unit',dataset_version:'v',file_name:'unit.xlsx',row_count:48,fields:[{field_id:'field_0001',name:'FIELD_MARKER',logical_type:'numeric',physical_type:'float',missing_rate:0}],quality_issues:[]},capabilities:{version:'cap-1',operations:{aggregate:{supported:true},group_aggregate:{supported:true}},aggregate_functions:['count'],derive_functions:['extract_year'],execution_scope:'tested'}};
  const summary=(item:typeof call & {error_code?:string|null},availability:'retained'|'expired')=>({call:{...item,outcome_scope:'provider_protocol',retry_reason:null,error_code:item.error_code??null,started_at:'2026-10-29T00:00:00Z',finished_at:'2026-10-29T00:00:02Z'},request_snapshot:{request_snapshot_id:item.request_snapshot_id,template_snapshot_id:item.template_snapshot_id,messages_hash:'h',schema_hash:'h',request_hash:'h',model_parameters:{model:'unit-model',enable_thinking:false,stream:false},client_config:{timeout_seconds:30},created_at:'',expires_at:null},provider_observation:availability==='retained'?{input_tokens:11,output_tokens:7}:{},trace_available:true,raw_availability:availability,response_availability:availability,redaction:{messages:'hidden'}});
  const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
    const url=String(input);
    if(url.includes('/call_plan_retry/summary'))return response(summary(retry,'expired'));
    if(url.endsWith('/summary'))return response(summary(call,'retained'));
    if(url.endsWith('/request'))return response({request_snapshot_id:call.request_snapshot_id,payload:{messages:[{role:'user',content:JSON.stringify(instruction)}]}});
    if(url.endsWith('/response'))return response({call_id:call.call_id,call_status:'succeeded',error_code:null,kind:'content',content:JSON.stringify({tasks:[{task_id:'DRAFT'}]}),truncated:false,content_sha256:'abc'});
    if(url.includes('/versions/'))return response({template:{version:'planner-v1.2',template_snapshot_id:call.template_snapshot_id,node_id:'analysis_planner',system_template:'s',user_composition:{},source_files:{prompt:{source:'unit'}}}});
    return response(data);
  });
  vi.stubGlobal('fetch',fetcher);
  view('/traces/workflows/'+fixture.workflow_id);
  fireEvent.click(await screen.findByRole('button',{name:/分析规划/}));
  const detail=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(detail).getByRole('tab',{name:'Output'})).toHaveAttribute('aria-selected','true');
  expect(within(detail).queryByRole('tab',{name:'Diagnostics'})).not.toBeInTheDocument();
  expect(within(detail).queryByRole('tab',{name:'Prompt & Model'})).not.toBeInTheDocument();
  expect(within(detail).getAllByText(/TASK_MARKER/).length).toBeGreaterThan(0);
  expect(within(detail).getByText(/P0 核心/)).toBeVisible();
  expect(within(detail).getByText(/F2 可以分析/)).toBeVisible();
  expect(within(detail).getByText(/需要用户审批/)).toBeVisible();
  expect(within(detail).queryByText('已审批')).not.toBeInTheDocument();
  expect(within(detail).queryByText(/Validator 已通过/)).not.toBeInTheDocument();
  fireEvent.click(within(detail).getByRole('tab',{name:'Input'}));
  expect(await within(detail).findByText('CONSTRAINT_PLAN')).toBeVisible();
  expect(within(detail).getAllByText('GOAL_MARKER').length).toBeGreaterThan(0);
  expect(within(detail).getByText(/FIELD_MARKER · numeric · float/)).toBeVisible();
  expect(within(detail).getByText(/本次传入的质量信号为 0 条/)).toBeVisible();
  expect(within(detail).getByText('aggregate')).toBeVisible();
  fireEvent.click(within(detail).getByRole('tab',{name:'LLM'}));
  expect(within(detail).getByText(call.call_id)).toBeVisible();
  expect(within(detail).getByText('call_plan_retry')).toBeVisible();
  expect(within(detail).getByText('PLANNER_INVALID_JSON')).toBeVisible();
  expect((await within(detail).findAllByText('planner-v1.2')).length).toBeGreaterThan(0);
  expect(within(detail).getByText(/模型原始返回未保留或已过期/)).toBeVisible();
  const reads=fetcher.mock.calls.length;
  fireEvent.click(within(detail).getByRole('tab',{name:'Output'}));
  fireEvent.click(within(detail).getByRole('tab',{name:'Input'}));
  expect(fetcher.mock.calls.length).toBe(reads);
  fireEvent.click(screen.getByRole('button',{name:/需求理解/}));
  expect(within(screen.getByRole('complementary',{name:'节点详情'})).getByRole('heading',{name:'需求理解'})).toBeVisible();
});
it('keeps validator, approval, execution and report details on their own nodes',async()=>{
  const data=source();
  const projection={source:'initial_plan_save',plan_id:'plan_unit',plan_version:1,validation_results:[{task_id:'T01',feasibility:'F2',reason_code:'READY',executable:true,validation_issues:[]}],executable_task_ids:['T01'],blocked_task_ids:[],plan:{plan_id:'plan_unit',plan_version:1,tasks:[{task_id:'T01',title:'TASK_ONLY_ON_VALIDATOR',priority:'P0',steps:[{operation:'aggregate'}]}]},corrected_plan:null};
  data.trace!.nodes.filter(item=>item.name==='plan_validator').forEach(item=>{item.validator_view=projection;});
  const hitl=data.trace!.nodes.find(item=>item.name==='hitl')!;
  hitl.approval_view={matched_approval:true,history:[{plan_id:'plan_unit',plan_version:1,change_type:'created',created_at:'2026-10-31T00:00:00Z',change_summary:'保存'}],history_complete:false,decision:{status:'approved',approval_id:'approval_unit',plan_id:'plan_unit',plan_version:1,approved_at:'2026-10-31T00:00:01Z'},executed:[{execution_id:'exec_unit',plan_id:'plan_unit',plan_version:1,approved_plan_version:1,execution_status:'success'}]};
  const engine=data.trace!.nodes.find(item=>item.name==='analysis_engine')!;
  engine.execution_view={execution_id:engine.attributes?.execution_id,plan_id:'plan_unit',plan_version:1,approved_plan_version:1,execution_status:'partial_success',rows_omitted:true,tasks:[{task_id:'T01',status:'success',effective_row_count:4,input_row_count:48,output_row_count:1,rule:{fields:['field_0001'],filters:[{field:'field_0001',operator:'eq',value:'FILTER_MARKER'}],dimensions:['field_0002'],metrics:[{function:'count',field:null}]},result_columns:[{field:'metric',label:'结果'}],result_preview:[{metric:7}]},{task_id:'T02',status:'failed',failure_reason:'FAIL_MARKER',rule:null}]};
  data.trace!.nodes.filter(item=>item.name==='insight_generator').forEach(item=>{item.report_view={report_id:'report_unit',report_status:'partial',goal_coverage:'partial',fact_validation:'structured_facts_verified_interpretations_unverified',result_rows_omitted:true,summary:{headline:'HEADLINE_MARKER',overview:'概述'},insights:[{insight_id:'ins_1',task_id:'T01',finding:'FINDING_MARKER',evidence_refs:['ev_1']}],limitations:[],evidence:[],charts:[]};});
  vi.stubGlobal('fetch',vi.fn(async()=>response(data)));
  view('/traces/workflows/'+fixture.workflow_id);
  fireEvent.click((await screen.findAllByRole('button',{name:/计划校验/}))[0]);
  const validator=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(validator).getByText(/没有返回修正后的计划/)).toBeVisible();
  fireEvent.click(within(validator).getByRole('tab',{name:'Input'}));
  expect(within(validator).getByText(/保存计划时的再次校验/)).toBeVisible();
  expect(within(validator).queryByRole('button',{name:'批准'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/人工审核/}));
  const approval=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(approval).getByText('已批准')).toBeVisible();
  expect(within(approval).getAllByText('一致').length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button',{name:/分析执行/}));
  const execution=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(execution).getByText('部分成功')).toBeVisible();
  fireEvent.click(within(execution).getByRole('tab',{name:'Input'}));
  expect(within(execution).getAllByText(/FILTER_MARKER/).length).toBeGreaterThan(0);
  expect(within(execution).getAllByText(/field_0002/).length).toBeGreaterThan(0);
  fireEvent.click(within(execution).getByRole('tab',{name:'Output'}));
  expect(within(execution).getByText('FAIL_MARKER')).toBeInTheDocument();
  expect(within(execution).queryByText('FINDING_MARKER')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/洞察生成/}));
  const report=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(report).getByText('FINDING_MARKER')).toBeInTheDocument();
  expect(within(report).getByText(/解释性陈述未验证/)).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:/分析执行/}));
  expect(screen.getByRole('complementary',{name:'节点详情'}).textContent||'').not.toContain('FINDING_MARKER');
});
it('shows the saved insight request beside the conclusion',async()=>{
  const data=source();
  const node=data.trace!.nodes.find(item=>item.name==='insight_generator')!;
  const call=data.trace!.llm_calls.find(item=>item.node_id==='analysis_planner')!;
  const insight={...call,call_id:'call_insight_unit',span_id:node.span_id,node_id:'insight_generator'};
  data.trace!.llm_calls.push(insight);
  node.report_view={report_id:'report_unit',report_status:'complete',fact_validation:'structured_facts_verified_interpretations_unverified',summary:{headline:'标题'},insights:[{insight_id:'ins_1',task_id:'T01',finding:'FINDING_MARKER',evidence_refs:['ev_1']}],limitations:[],evidence:[],charts:[],result_rows_omitted:true};
  const instruction={analysis_goal:{analysis_object:'对象',business_goal:'GOAL_INPUT',decision_goal:null},constraints:{time_range:null,filters:[{raw_text:'CONSTRAINT_INPUT',validation_status:'unverified'}],metric_requirements:[],analysis_limits:[]},task_sample_context:[{task_id:'T01',status:'success',valid_sample_count:4}],evidence:[{evidence_id:'ev_1',task_id:'T01',evidence_type:'metric',statement:'证据陈述',calculation:'count',result_field:'metric',value:{value:7,unit:null},data_ref:'result_1',source_row_indices:[1]}]};
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
    const url=String(input);
    if(url.endsWith('/summary'))return response({call:{...insight,outcome_scope:'provider_protocol',retry_reason:null,error_code:null,started_at:'2026-10-29T00:00:00Z',finished_at:'2026-10-29T00:00:02Z'},request_snapshot:{request_snapshot_id:insight.request_snapshot_id,template_snapshot_id:insight.template_snapshot_id,messages_hash:'h',schema_hash:'h',request_hash:'h',model_parameters:{model:'unit-model'},client_config:{timeout_seconds:30},created_at:'',expires_at:null},provider_observation:{},trace_available:true,raw_availability:'retained',response_availability:'retained',redaction:{messages:'hidden'}});
    if(url.endsWith('/request'))return response({request_snapshot_id:insight.request_snapshot_id,payload:{messages:[{role:'user',content:JSON.stringify(instruction)}]}});
    if(url.endsWith('/response'))return response({call_id:insight.call_id,call_status:'succeeded',error_code:null,kind:'content',content:'{}',truncated:false,content_sha256:'abc'});
    if(url.includes('/versions/'))return response({template:{version:'insight-v1',template_snapshot_id:insight.template_snapshot_id,node_id:'insight_generator',system_template:'s',user_composition:{},source_files:{prompt:{source:'unit'}}}});
    return response(data);
  }));
  view('/traces/workflows/'+fixture.workflow_id);
  fireEvent.click(await screen.findByRole('button',{name:/洞察生成/}));
  const detail=screen.getByRole('complementary',{name:'节点详情'});
  expect(within(detail).getByText('FINDING_MARKER')).toBeInTheDocument();
  fireEvent.click(within(detail).getByRole('tab',{name:'Input'}));
  expect(await within(detail).findByText('GOAL_INPUT')).toBeVisible();
  expect(within(detail).getByText('CONSTRAINT_INPUT')).toBeVisible();
  expect(within(detail).getAllByText(/value 7/).length).toBeGreaterThan(0);
  expect(within(detail).queryByText('source_row_indices')).not.toBeInTheDocument();
});
it('supports empty filtered results',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>response(page([]))));view('/traces/workflows?session_id=missing');
  expect(await screen.findByRole('heading',{name:'没有匹配的 Workflow'})).toBeVisible();
});
it('shows authorization failure rather than simulated records',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>response({},403)));view('/traces/workflows');
  expect(await screen.findByRole('heading',{name:'需要管理员只读访问'})).toBeVisible();
});
it('rejects wrong ownership in API payloads',async()=>{
  expect(isWorkflow(source())).toBe(true);const wrong=source();wrong.trace!.root_run_id='other';expect(isWorkflow(wrong)).toBe(false);
  vi.stubGlobal('fetch',vi.fn(async()=>response(wrong)));
  await expect(workflowApi.get(fixture.workflow_id)).rejects.toThrow('Workflow 详情结构或归属不正确');
});

it('does not invent historical content for an unknown Workflow ID',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>response({},404)));view('/traces/workflows/wf_not_registered');
  expect(await screen.findByRole('heading',{name:'Workflow 不存在或未登记'})).toBeVisible();
  expect(screen.queryAllByTestId('workflow-node')).toHaveLength(0);
});
