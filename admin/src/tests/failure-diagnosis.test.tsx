// Component fault fixtures derived from the frozen C2 sample; not browser or server data.
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { isWorkflow } from '../api/workflows';
import type { WorkflowView } from '../types/workflows';
import fixture from './fixtures/workflow-c2.json';

const source=()=>structuredClone(fixture) as unknown as WorkflowView;
function view(path:string) {render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>);}
function response(value:unknown) {return new Response(JSON.stringify(value),{status:200,headers:{'content-type':'application/json'}});}
function failed() {
  const data=source();const node=data.trace!.nodes.find(n=>n.name==='data_profiler')!;
  node.status='failed';node.error_code='EMPTY_HEADER';
  node.attributes={...node.attributes,input_header_row:5,input_file_extension:'.csv',input_file_size_bytes:2048};
  data.business_lifecycle.status='failed';
  data.failure={category:'file_input',label:'文件或解析参数',hint:'指定的表头行为空。对照输入摘要中的 input_header_row 与文件实际表头位置。',code:'EMPTY_HEADER',
    source:'node',node_name:'data_profiler',node_key:'data_profiler',span_id:node.span_id,inputs:{input_header_row:5,input_file_extension:'.csv',input_file_size_bytes:2048}};
  return {data,node};
}

it('shows failure attribution, the failing node and its input parameters',async()=>{
  const {data,node}=failed();
  vi.stubGlobal('fetch',vi.fn(async()=>response(data)));view('/traces/workflows/'+fixture.workflow_id);
  const detail=await screen.findByRole('complementary',{name:'节点详情'});
  expect(within(detail).queryByRole('tab',{name:'Error Stack'})).not.toBeInTheDocument();
  expect(within(detail).getByText('错误详情')).toBeVisible();
  expect(within(detail).getByText('EMPTY_HEADER')).toBeVisible();
  expect(within(detail).getByText('表头行').nextElementSibling).toHaveTextContent('5');
  expect(document.getElementById('node-'+node.span_id)).toHaveAttribute('aria-pressed','true');
  expect(within(detail).getByText('文件大小（字节）')).toBeInTheDocument();
});

it('omits the failure card for successful runs and explains missing input summaries',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>response(source())));view('/traces/workflows/'+fixture.workflow_id);
  await screen.findByRole('heading',{name:'完整 Workflow'});
  expect(screen.queryByRole('region',{name:'失败定位'})).not.toBeInTheDocument();
  expect(screen.getAllByText(/未采集输入摘要/).length).toBeGreaterThan(0);
});

it('filters the list by failure category and labels the failing node',async()=>{
  const {data}=failed();delete data.trace;
  const fetcher=vi.fn(async(_input:RequestInfo|URL)=>response({schema_version:'workflow-observability-page-v1',items:[data],total:1,limit:20,offset:0,sort:'s',notice:'n'}));
  vi.stubGlobal('fetch',fetcher);view('/traces/workflows');
  expect(await screen.findByText('data_profiler / EMPTY_HEADER')).toBeVisible();
  expect(screen.getByRole('link',{name:'查看详情'})).toHaveAttribute('href','/traces/workflows/'+fixture.workflow_id);
  expect(screen.queryByLabelText('失败归因')).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalled();
});

it('rejects malformed failure payloads',()=>{
  const {data}=failed();
  expect(isWorkflow(data)).toBe(true);
  expect(isWorkflow({...data,failure:{...data.failure,category:'guess'}})).toBe(false);
  expect(isWorkflow({...data,failure:{...data.failure,inputs:null}})).toBe(false);
  expect(isWorkflow({...data,failure:null})).toBe(true);
});
