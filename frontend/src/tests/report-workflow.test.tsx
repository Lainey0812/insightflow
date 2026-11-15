import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { it, expect, vi } from 'vitest';
import { api } from '../api/client';
import App from '../App';
import { ReportGenerationCard } from '../components/ReportGenerationCard';
import { ReportDocument } from '../reporting/ReportPage';
import type { ReportGeneration, Session } from '../types/contracts';
import type { AnalysisReport } from '../types/report';
import sessionFixture from './fixtures/hitl-v1.json';
import reportFixture from './fixtures/report-v1.json';
import { reviewFixture } from './review-fixtures';

const job: ReportGeneration = {execution_id:'exec_test',session_id:'session',status:'generating',attempt:1,report_id:null,error:null,queued_at:'now',started_at:null,finished_at:null};
it('shows pending report separately from saved execution, then previews without forced download',()=>{
  const {rerender}=render(<ReportGenerationCard executionId="exec_test" sessionId="session" record={job}/>);
  expect(screen.getByRole('status')).toHaveTextContent('正在生成报告');
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  rerender(<ReportGenerationCard executionId="exec_test" sessionId="session" record={{...job,status:'completed',report_id:'report_test'}}/>);
  expect(screen.getByRole('link',{name:'预览分析报告'})).toHaveAttribute('href','/reports/report_test');
  expect(screen.queryByRole('link',{name:/下载/})).not.toBeInTheDocument();
});
it('retries only the failed report attempt, never reruns the engine',async()=>{
  const call=vi.spyOn(api,'generateReport').mockResolvedValue({...job,status:'queued',attempt:2});
  const engine=vi.spyOn(api,'executeReal');const changed=vi.fn();
  render(<ReportGenerationCard executionId="exec_test" sessionId="session" record={{...job,status:'failed',error:{code:'LLM_TIMEOUT',message:'模型超时，结果已保留。',retryable:true}}} onChange={changed}/>);
  fireEvent.click(screen.getByRole('button',{name:'重新生成报告'}));
  await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
  expect(call).toHaveBeenCalledWith('exec_test','session',1);expect(engine).not.toHaveBeenCalled();
});
it('continues polling a completed calculation until its persisted report is ready after refresh',async()=>{
  const current={...structuredClone(sessionFixture),workflow_kind:'real_v1',status:'COMPLETED',engine_execution_ids:['exec_test'],report_generations:[job]} as Session;
  // A real completed execution is bound to the currently approved plan version.
  current.approved_plan_version=current.current_plan_version;
  current.report_generations![0].session_id=current.id;
  const next={...current,revision:current.revision+2,report_generations:[{...job,session_id:current.id,status:'completed' as const,report_id:'report_test'}]};
  localStorage.setItem('insightflow.session',current.id);
  vi.spyOn(api,'health').mockResolvedValue({status:'ok',mode:'real',service:'insightflow',version:'0.1.0'});
  vi.spyOn(api,'list').mockResolvedValue([current]);vi.spyOn(api,'review').mockResolvedValue(reviewFixture(current));
  vi.spyOn(api,'execution').mockResolvedValue({execution_id:'exec_test',approval_id:'approval',plan_id:'plan',plan_version:1,dataset_id:'dataset',dataset_version:'v',execution_status:'success',warnings:[],tasks:[]});
  const read=vi.spyOn(api,'session').mockResolvedValueOnce(current).mockResolvedValue(next);
  render(<App/>);
  expect(await screen.findByText('正在生成报告')).toBeInTheDocument();
  await waitFor(()=>expect(screen.getByRole('link',{name:'预览分析报告'})).toBeInTheDocument(),{timeout:2500});
  expect(read.mock.calls.length).toBeGreaterThan(1);
  expect(screen.getByText('查看原始计算结果').closest('details')).not.toHaveAttribute('open');
});
it('opens original stored result only on request and downloads only on explicit click',async()=>{
  const report={...reportFixture,execution_source:'engine'} as unknown as AnalysisReport;
  const raw=vi.spyOn(api,'reportExecution').mockResolvedValue({execution_id:report.execution_id,approval_id:'approval',plan_id:'plan',plan_version:1,dataset_id:'dataset',dataset_version:'v',execution_status:'success',warnings:[],tasks:[]});
  const download=vi.spyOn(api,'downloadReport').mockResolvedValue();
  render(<ReportDocument report={report}/>);
  expect(raw).not.toHaveBeenCalled();expect(download).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'查看原始计算结果'}));
  expect(await screen.findByText('计算状态：计算成功')).toBeInTheDocument();expect(raw).toHaveBeenCalledWith(report.report_id);
  fireEvent.click(screen.getByRole('link',{name:'下载报告（HTML）'}));
  await waitFor(()=>expect(download).toHaveBeenCalledWith(report.report_id));
});
it('attaches local session credentials to engine-backed report reads',async()=>{
  localStorage.setItem('insightflow.access.owner','test-only-token');
  const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}',{status:200}));
  await api.analysisReport('report_test');
  expect(fetch.mock.calls[0][1]?.headers).toMatchObject({'X-Session-Keys':JSON.stringify({owner:'test-only-token'})});
});
it('does not offer blind retry for a hard report capacity failure',()=>{
  render(<ReportGenerationCard executionId="exec_test" sessionId="session" record={{...job,status:'failed',error:{code:'REPORT_CONTEXT_TOO_LARGE',message:'证据上下文超限，计算结果保留。',retryable:false}}}/>);
  expect(screen.getByRole('alert')).toHaveTextContent('证据上下文超限');
  expect(screen.queryByRole('button',{name:'重新生成报告'})).not.toBeInTheDocument();
});
