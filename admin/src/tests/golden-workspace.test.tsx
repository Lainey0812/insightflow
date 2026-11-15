import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { GoldenWorkspacePage } from '../pages/GoldenWorkspacePage';
import { goldenApi } from '../api/goldenSet';
import type { GoldenDocument, GoldenDraft, GoldenVersion } from '../api/goldenSet';
import { ApiError } from '../api/client';
vi.mock('../api/goldenSet');
const original:GoldenDocument={set_id:'golden-test',case_count:1,columns:['编号','城市'],rows:[{'编号':'J01','城市':'上海'}],cases:[{case_id:'G-01',user_input:'按城市计数',oracle:{上海:1},error_controls:[],must_execute:['计数'],must_forbid:[],pass_rule:'上海1条',fail_classes:[]}]};
function frozen(doc:GoldenDocument,version:number):GoldenVersion{return {set_id:doc.set_id,version,case_count:doc.cases.length,row_count:doc.rows.length,content_hash:'hash'+version,document:structuredClone(doc),created_at:'2026-11-16T00:00:00Z',created_by:'tester',change_summary:'initial',frozen:true};}
let current:GoldenVersion,draft:GoldenDraft;
beforeEach(()=>{vi.resetAllMocks();current=frozen(original,1);draft={document:structuredClone(original),base_version:1,revision:1,updated_at:'now',updated_by:'tester'};
  vi.mocked(goldenApi.versions).mockImplementation(async v=>({current_version:current.version,selected:v==='1'?frozen(original,1):current,versions:current.version===1?[current]:[current,frozen(original,1)],notice:'explicit version only'}));
  vi.mocked(goldenApi.draft).mockImplementation(async()=>structuredClone(draft));
  vi.mocked(goldenApi.save).mockImplementation(async body=>{draft={...draft,document:body.document,revision:draft.revision+1};return structuredClone(draft);});
  vi.mocked(goldenApi.publish).mockImplementation(async()=>{current=frozen(draft.document,2);return current;});
});
function view(path:string){render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/evaluations/golden" element={<GoldenWorkspacePage/>}/><Route path="/evaluations/golden/draft" element={<GoldenWorkspacePage/>}/></Routes></MemoryRouter>);}
it('frozen version shows counts and real tables without mutation controls',async()=>{
  view('/evaluations/golden');await screen.findByRole('heading',{name:'V1 · 冻结版本'});
  expect(screen.getByRole('table',{name:'黄金集测试用例'})).toHaveTextContent('G-01');
  expect(screen.getByRole('table',{name:'黄金集源数据记录'})).toHaveTextContent('J01');
  expect(screen.queryByRole('button',{name:'新增用例'})).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'编辑 G-01'})).not.toBeInTheDocument();
});
it('edits draft, saves then confirms, updates current and can view old version',async()=>{
  view('/evaluations/golden/draft');await screen.findByRole('button',{name:'编辑 G-01'});
  fireEvent.click(screen.getByRole('button',{name:'编辑 G-01'}));
  fireEvent.change(screen.getByLabelText('通过规则'),{target:{value:'上海1条，核对记录范围'}});
  fireEvent.click(screen.getByRole('button',{name:'应用到 Draft'}));
  expect(goldenApi.save).not.toHaveBeenCalled();
  expect(screen.getByRole('button',{name:'确认发布为 V2'})).toBeDisabled();
  fireEvent.change(screen.getByLabelText('黄金集操作人'),{target:{value:'tester'}});
  fireEvent.click(screen.getByRole('button',{name:'保存草稿'}));
  await screen.findByText('草稿已保存，冻结版本尚未变化。');
  fireEvent.change(screen.getByLabelText('版本变更说明'),{target:{value:'完善通过规则'}});
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button',{name:'确认发布为 V2'}));
  await screen.findByRole('heading',{name:'V2 · 冻结版本'});
  expect(goldenApi.publish).toHaveBeenCalledWith(expect.objectContaining({expected_revision:2,base_version:1}),'');
  fireEvent.change(screen.getByLabelText('黄金集版本'),{target:{value:'1'}});
  await screen.findByRole('heading',{name:'V1 · 冻结版本'});
  expect(screen.queryByText('上海1条，核对记录范围')).not.toBeInTheDocument();
});
it('draft add and delete remain local until saved, duplicate IDs are rejected',async()=>{
  view('/evaluations/golden/draft');await screen.findByRole('button',{name:'新增用例'});
  fireEvent.click(screen.getByRole('button',{name:'新增用例'}));
  fireEvent.change(screen.getByLabelText('用例 ID'),{target:{value:'G-01'}});fireEvent.change(screen.getByLabelText('用例需求'),{target:{value:'新需求'}});
  fireEvent.change(screen.getByLabelText('正确结果 Oracle'),{target:{value:'{"上海":1}'}});fireEvent.change(screen.getByLabelText('通过规则'),{target:{value:'正确'}});
  fireEvent.click(screen.getByRole('button',{name:'应用到 Draft'}));await screen.findByText('用例ID已存在，请使用唯一ID。');
  fireEvent.change(screen.getByLabelText('用例 ID'),{target:{value:'G-02'}});fireEvent.click(screen.getByRole('button',{name:'应用到 Draft'}));
  await screen.findByRole('button',{name:'删除 G-02'});fireEvent.click(screen.getByRole('button',{name:'删除 G-01'}));
  expect(screen.queryByRole('button',{name:'编辑 G-01'})).not.toBeInTheDocument();
  expect(goldenApi.save).not.toHaveBeenCalled();expect(original.case_count).toBe(1);
});
it('conflict preserves local draft and offers explicit reload',async()=>{
  vi.mocked(goldenApi.save).mockRejectedValue(new ApiError('HTTP_ERROR','conflict',409));
  view('/evaluations/golden/draft');await screen.findByRole('button',{name:'删除 G-01'});fireEvent.click(screen.getByRole('button',{name:'删除 G-01'}));
  fireEvent.change(screen.getByLabelText('黄金集操作人'),{target:{value:'tester'}});fireEvent.click(screen.getByRole('button',{name:'保存草稿'}));
  await screen.findByText(/版本或Draft已被其他操作更新/);
  expect(screen.getByRole('button',{name:'放弃本地修改并重新载入'})).toBeEnabled();expect(goldenApi.publish).not.toHaveBeenCalled();
});

it('case detail shows exact input, expected behavior and scoring rules from selected version',async()=>{
  current.document.cases[0]={...current.document.cases[0],must_forbid:['不得去重'],error_controls:[{code:'COUNT_DISTINCT',label:'错误去重',result:{上海:0}}],fail_classes:['count_mismatch']};
  view('/evaluations/golden');await screen.findByRole('button',{name:'查看详情 G-01'});
  fireEvent.click(screen.getByRole('button',{name:'查看详情 G-01'}));
  const detail=screen.getByRole('region',{name:'测试用例详情'});
  expect(detail).toHaveTextContent('测试输入');expect(detail).toHaveTextContent('按城市计数');
  expect(detail).toHaveTextContent('预期行为');expect(detail).toHaveTextContent('不得去重');
  expect(detail).toHaveTextContent('评测规则');expect(detail).toHaveTextContent('上海1条');expect(detail).toHaveTextContent('COUNT_DISTINCT');
  fireEvent.click(screen.getByRole('button',{name:'关闭详情'}));expect(screen.queryByRole('region',{name:'测试用例详情'})).not.toBeInTheDocument();
  expect(goldenApi.save).not.toHaveBeenCalled();expect(goldenApi.publish).not.toHaveBeenCalled();
});
it('draft detail reflects local edits and marks unsaved source',async()=>{
  view('/evaluations/golden/draft');await screen.findByRole('button',{name:'编辑 G-01'});
  fireEvent.click(screen.getByRole('button',{name:'编辑 G-01'}));fireEvent.change(screen.getByLabelText('通过规则'),{target:{value:'草稿新规则'}});fireEvent.click(screen.getByRole('button',{name:'应用到 Draft'}));
  fireEvent.click(screen.getByRole('button',{name:'查看详情 G-01'}));
  expect(screen.getByRole('region',{name:'测试用例详情'})).toHaveTextContent('草稿新规则');
  expect(screen.getByRole('region',{name:'测试用例详情'})).toHaveTextContent('含本地未保存更改');
});
