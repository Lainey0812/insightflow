import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { it, expect, vi } from 'vitest';
import ReportPage, { ReportDocument } from '../reporting/ReportPage';
import { api } from '../api/client';
import type { AnalysisReport, ReportPresentation } from '../types/report';
import reportFixture from './fixtures/sales-report.json';
import viewFixture from './fixtures/business-sales-report.json';

vi.mock('../reporting/InteractiveChart', () => ({default:({title}:{title:string})=><div role="img" aria-label={title}>真实结果图表</div>}));
const report=reportFixture as unknown as AnalysisReport;
const view=viewFixture as unknown as ReportPresentation;

it('puts dataset overview before summary and directions, preserving historical facts in details',async()=>{
  render(<ReportDocument report={report} presentation={view}/>);
  expect(screen.getByRole('heading',{level:1})).toHaveTextContent(view.title);
  expect(screen.getAllByRole('heading',{level:2}).map(h=>h.textContent)).toEqual(['数据概况','执行摘要','各分析方向','整体总结与下一步建议','分析范围与统计口径','数据局限与证据']);
  const overview=screen.getByRole('region',{name:'数据概况'});
  expect(within(overview).getAllByText('未统计').length).toBeGreaterThanOrEqual(2);
  await userEvent.click(screen.getByText('查看关键业务指标',{exact:true}));
  for(const amount of ['21,250','4.9%','87.8%'])expect(screen.getByText(amount,{exact:true})).toBeVisible();
  await userEvent.click(screen.getByText('历史报告补充解读',{exact:true}));
  expect(screen.getByText(/约为济南的 27.1%/,{selector:'p'})).toBeVisible();
  expect(screen.getByText(/并不是它们在整个地区/)).toBeVisible();
  expect(screen.getByRole('link',{name:'下载报告（HTML）'})).toBeVisible();
});

it('reveals evidence and compatible chart/table interactions without generating new analysis',async()=>{
  const create=vi.spyOn(api,'create');const generate=vi.spyOn(api,'generateReport');
  render(<ReportDocument report={report} presentation={view}/>);
  expect(screen.getByLabelText(`${report.charts[0].title}图表类型`)).toBeVisible();
  await userEvent.click(screen.getByText('查看关键业务指标',{exact:true}));
  const card = screen.getByText('占前三名合计').closest('article')!;
  await userEvent.click(within(card).getByText(/查看证据与统计口径/));
  expect(within(card).getByText(/分母仅为前三名合计/)).toBeVisible();
  const selector=await screen.findByLabelText(`${report.charts[0].title}图表类型`);
  fireEvent.change(selector,{target:{value:'table'}});
  expect(await screen.findByRole('table')).toHaveTextContent('20,250');
  expect(create).not.toHaveBeenCalled();expect(generate).not.toHaveBeenCalled();
});

it('loads persisted report and presentation without a model call and keeps partial status visible',async()=>{
  vi.spyOn(api,'analysisReport').mockResolvedValue({...report,goal_coverage:'partial',report_status:'partial'});
  vi.spyOn(api,'reportPresentation').mockResolvedValue(view);
  render(<ReportPage reportId={report.report_id}/>);
  await screen.findByRole('heading',{name:view.title});
  expect(screen.getByText('报告部分生成')).toBeVisible();
  expect(screen.getByText('目标部分覆盖')).toBeVisible();
});

it('keeps the stored report accessible when presentation loading fails',async()=>{
  vi.spyOn(api,'analysisReport').mockResolvedValue(report);
  vi.spyOn(api,'reportPresentation').mockRejectedValue(new Error('展示暂时不可用'));
  render(<ReportPage reportId={report.report_id}/>);
  expect(await screen.findByRole('heading',{name:report.summary.headline})).toBeInTheDocument();
});

it('renders composed saved insights with E references and does not add legacy rule findings',()=>{
  const unified: ReportPresentation={...view,presentation_version:'business-report-v1.1',kind:'general',
    findings:report.insights.map(i=>({title:i.finding,body:i.implication,evidence_refs:i.evidence_refs})),
    recommendations:report.recommendations.map(r=>r.text),evidence:[]};
  render(<ReportDocument report={report} presentation={unified}/>);
  expect(screen.queryByText('核心发现与业务解读')).not.toBeInTheDocument();
  expect(screen.queryByText(/V001 ·/)).not.toBeInTheDocument();
  for(const i of report.insights){
    expect(screen.getByText(i.finding,{exact:true})).toBeVisible();
    expect(screen.getAllByText(i.implication,{exact:true})[0]).toBeVisible();
  }
  for(const r of report.recommendations)expect(screen.getByText(r.text,{exact:true})).toBeVisible();
});

it('retains rejected candidate reasons in collapsed report details',async()=>{
  const withRejection: AnalysisReport={...report,report_status:'partial',execution_metadata:{
    T01:{...report.execution_metadata.T01,insight_generation_version:'evidence-composition-v1.1',
      rejected_insights:[{candidate_index:2,primary_evidence_id:'E0011',error_code:'REPORT_UNVERIFIED_FACT'}]}}};
  render(<ReportDocument report={withRejection} presentation={{...view,presentation_version:'business-report-v1.1'}}/>);
  expect(screen.getByText('报告部分生成')).toBeVisible();
  await userEvent.click(screen.getByText('报告来源与版本',{exact:true}));
  await userEvent.click(screen.getByText('候选洞察校验记录',{exact:true}));
  expect(screen.getByText(/候选 3 · 证据 E0011 · REPORT_UNVERIFIED_FACT/)).toBeVisible();
});

it('shows a saved fact once and a recommendation once when presentation is unavailable',()=>{
  const updated: AnalysisReport={...report,summary:{...report.summary,overview:'当前返回结果仅适用于已批准范围。'},
    insights:[{...report.insights[0],finding:'济南与南京的已验证销售额差额为 1,000。',
      fact:'事实依据：E0002、E0003；数值与对象已核对。',recommendation:'比较对应城市订单数量；补充分析尚未执行。'}],
    recommendations:[{text:'比较对应城市订单数量；补充分析尚未执行。',evidence_refs:report.insights[0].evidence_refs}]};
  render(<ReportDocument report={updated}/>);
  expect(screen.getAllByText('济南与南京的已验证销售额差额为 1,000。',{exact:true}).length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText('比较对应城市订单数量；补充分析尚未执行。',{exact:false})).toHaveLength(1);
  expect(screen.getByText('事实核对详情',{exact:true})).toBeVisible();
});

it('does not attach an unrelated measure or missing evidence to a chart',()=>{
  const altered: AnalysisReport={...report, insights:[{...report.insights[0],finding:'不应展示的跨指标解释',evidence_refs:['missing-evidence']}]};
  render(<ReportDocument report={altered} presentation={view}/>);
  const note=screen.getByRole('region',{name:`${report.charts[0].title}图表解读`});
  expect(note).not.toHaveTextContent('不应展示的跨指标解释');
  expect(note).toHaveTextContent('暂无与此指标直接对应的已保存解读');
});

it('binds chart commentary by result and metric rather than task alone',()=>{
  const chart=report.charts[0];
  const matching=report.evidence.find(e=>e.task_id===chart.task_id && e.data_ref===chart.data_ref && chart.metrics.includes(e.result_field))!;
  const altered: AnalysisReport={...report, insights:[{...report.insights[0],finding:'已核对的对应指标发现',evidence_refs:[matching.evidence_id]}]};
  render(<ReportDocument report={altered} presentation={view}/>);
  expect(screen.getByRole('region',{name:`${chart.title}图表解读`})).toHaveTextContent('已核对的对应指标发现');
});

it('uses a linked Engine count, never preview rows, for a single direction',()=>{
  const spec=report.charts[0];
  const only: AnalysisReport={...report, execution_source:'engine', task_metadata:{[spec.task_id]:report.task_metadata[spec.task_id]},
    execution_metadata:{[spec.task_id]:{...report.execution_metadata[spec.task_id],status:'success',result_id:spec.data_ref,effective_row_count:16,
      execution_metadata:{input_row_count:60,steps:[{operation:'group_aggregate',status:'success'}]}}}};
  render(<ReportDocument report={only}/>);
  const overview=screen.getByRole('region',{name:'数据概况'});
  expect(within(overview).getByText('16',{exact:true})).toBeVisible();
  expect(within(overview).getByText('60',{exact:true})).toBeVisible();
  expect(within(overview).getAllByText('未统计')).toHaveLength(2);
});

it('does not merge equal counts from two directions or interpret missing cells as missing rows',()=>{
  const tid=Object.keys(report.task_metadata)[0];
  const multi: AnalysisReport={...report,task_metadata:{...report.task_metadata,other:{title:'另一范围',priority:'P0'}},execution_metadata:{...report.execution_metadata,other:{effective_row_count:16}}};
  render(<ReportDocument report={multi} presentation={{...view,dataset_overview:{field_count:12,missing_cell_count:5,duplicate_row_count:2}}}/>);
  const overview=screen.getByRole('region',{name:'数据概况'});
  expect(within(overview).getByText('分方向统计')).toBeVisible();
  expect(within(overview).getAllByText('未统计')).toHaveLength(2);
  expect(overview).toHaveTextContent('缺失单元格 5 个');
  expect(overview).toHaveTextContent('疑似重复记录 2 条');
  expect(tid).toBeTruthy();
});

it('does not promote imported or unlinked effective row counts into overview facts',()=>{
  const tid=Object.keys(report.task_metadata)[0];
  const imported: AnalysisReport={...report,execution_source:'imported',task_metadata:{[tid]:report.task_metadata[tid]},execution_metadata:{[tid]:{status:'success',result_id:'wrong',effective_row_count:16}}};
  render(<ReportDocument report={imported}/>);
  expect(within(screen.getByRole('region',{name:'数据概况'})).getAllByText('未统计')).toHaveLength(3);
});

function scalarReport() {
  const chart=report.charts[0];
  const metric={field:'sales_total',label:'销售额 · 合计',logical_type:'number',role:'metric' as const,unit:null};
  const scalar: AnalysisReport={...report,charts:[{...chart,chart_type:'table',dimension:null,metrics:['sales_total'],supported_chart_types:['table']}],
    result_data:{[chart.data_ref]:{result_id:chart.data_ref,columns:[metric],rows:[{sales_total:125040}],total_result_rows:1,truncated:false}}};
  return scalar;
}

it('shows a complete ungrouped aggregate as metric cards and retains the original table',async()=>{
  const scalar=scalarReport();
  render(<ReportDocument report={scalar}/>);
  const cards=screen.getByLabelText(`${scalar.charts[0].title}指标卡片`);
  expect(cards).toHaveTextContent('销售额 · 合计');
  expect(cards).toHaveTextContent('125,040');
  expect(screen.queryByText('图表解读',{exact:true})).not.toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button',{name:'查看结果数据'}));
  expect(screen.getByRole('table')).toHaveTextContent('125,040');
  await userEvent.click(screen.getByRole('button',{name:'收起数据'}));
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

it('keeps a grouped singleton or truncated result in its original table form',()=>{
  const scalar=scalarReport();
  scalar.charts[0].dimension='city';
  render(<ReportDocument report={scalar}/>);
  expect(screen.queryByLabelText(`${scalar.charts[0].title}指标卡片`)).not.toBeInTheDocument();
  expect(screen.getByRole('table')).toBeVisible();
});

it('preserves zero and missing scalar values without fabricating a currency unit',()=>{
  const scalar=scalarReport();const table=scalar.result_data[scalar.charts[0].data_ref];
  table.columns.push({...table.columns[0],field:'sales_avg',label:'销售额 · 均值'});
  table.rows[0]={sales_total:0,sales_avg:null};scalar.charts[0].metrics.push('sales_avg');
  render(<ReportDocument report={scalar}/>);
  const cards=screen.getByLabelText(`${scalar.charts[0].title}指标卡片`);
  expect(within(cards).getByText('0',{exact:true})).toBeVisible();
  expect(within(cards).getByText('—',{exact:true})).toBeVisible();
  expect(cards).not.toHaveTextContent('元');
});

it('shows interpretation only while a graphical chart is selected',()=>{
  render(<ReportDocument report={report}/>);
  const spec=report.charts[0];
  const selector=screen.getByLabelText(`${spec.title}图表类型`);
  expect(screen.getByRole('region',{name:`${spec.title}图表解读`})).toBeVisible();
  fireEvent.change(selector,{target:{value:'table'}});
  expect(screen.queryByRole('region',{name:`${spec.title}图表解读`})).not.toBeInTheDocument();
  expect(screen.getByRole('table')).toBeVisible();
  fireEvent.change(selector,{target:{value:'bar'}});
  expect(screen.getByRole('region',{name:`${spec.title}图表解读`})).toBeVisible();
});

it('shows saved joint row statistics and explicit metric bases instead of placeholders',async()=>{
  const scalar=scalarReport();const spec=scalar.charts[0];
  scalar.execution_source='engine';scalar.task_metadata={[spec.task_id]:report.task_metadata[spec.task_id]};
  scalar.execution_metadata={[spec.task_id]:{status:'success',result_id:spec.data_ref,effective_row_count:6,valid_sample_count:5,
    execution_metadata:{input_row_count:7,steps:[{operation:'aggregate',status:'success'}],sample_statistics:{
      version:'execution-sample-v1',scope:'before_single_aggregate',aggregate_step_id:'S02',input_row_count:6,
      key_fields:[{field:'city',label:'城市',missing_count:2},{field:'sales',label:'销售额',missing_count:1}],
      complete_row_count:3,missing_row_count:3,metrics:{sales_total:{function:'sum',field:'sales',label:'销售额',basis:'non_null_values',participating_count:5}}}}}};
  render(<ReportDocument report={scalar}/>);
  const overview=screen.getByRole('region',{name:'数据概况'});
  expect(within(overview).queryByText('未统计')).not.toBeInTheDocument();
  expect(within(overview).getByText('6',{exact:true})).toBeVisible();
  expect(within(overview).getAllByText('3',{exact:true})).toHaveLength(2);
  await userEvent.click(screen.getByText('样本与指标口径',{exact:true}));
  expect(screen.getByText(/完整记录 3 条；至少一个关键字段缺失 3 条/)).toBeVisible();
  expect(screen.getByText(/按来源字段非空记录参与计算；参与记录 5 条/)).toBeVisible();
});
