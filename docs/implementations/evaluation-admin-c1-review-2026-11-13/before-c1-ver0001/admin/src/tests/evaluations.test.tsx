import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { currentNavigation } from '../app/navigation';
import { isDatasetDetail, isRunDetail } from '../api/evaluations';
import type { DatasetDetail, DatasetListPage, RunDetail, RunListPage } from '../types/evaluations';
// Fixtures are the response bodies captured from the real B1/B2 API (docs/evaluations/evaluation-admin-b2-2026-11-13).
import runsPageJson from './fixtures/evaluations/runs-page.json';
import datasetsPageJson from './fixtures/evaluations/datasets-page.json';
import runGfJson from './fixtures/evaluations/run-gf-legacy.json';
import runRgJson from './fixtures/evaluations/run-rg-legacy.json';
import datasetGoldenJson from './fixtures/evaluations/dataset-golden.json';
import error404Json from './fixtures/evaluations/error-404-run.json';

const clone = <T,>(value: unknown) => structuredClone(value) as T;
const GF = 'gf_20261112-143406_cde1fd', RG = 'rg_20261112-133157_f04289', GOLDEN = 'requirement-fidelity-golden-v1';

function view(path: string) { render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>); }
function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } }); }
function apiError(status: number, code: string, details: Record<string, unknown> = {}, message = '服务内部信息') {
  return json({ error: { code, message, node_name: null, retryable: false, details } }, status);
}
function stub(handler: (url: URL) => Response | Promise<Response>) {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => handler(new URL(String(input))));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
const urls = (fetcher: ReturnType<typeof stub>) => fetcher.mock.calls.map(call => new URL(String(call[0])));
function caseRow(caseId: string) {
  const row = screen.getByRole('table', { name: 'Case Results' }).querySelector(`tr[data-case="${caseId}"]`);
  if (!row) throw new Error('missing row ' + caseId);
  return within(row as HTMLElement);
}

function verifiedRun(): RunDetail {
  const run = clone<RunDetail>(runGfJson);
  run.run_id = 'gf_20261113-090000_abcdef'; run.provenance = 'recorded'; run.agent_id = 'insightflow'; run.agent_version = 'agent-1.4.0';
  run.dataset_version = 'golden-v1'; run.unverified_fields = [];
  run.integrity = { ...run.integrity, status: 'VERIFIED', trusted: true, reasons: [], files: [{ ref: 'cases/RF-01/result.json', role: 'case_result', case_id: 'RF-01', status: 'ok' }] };
  run.evaluator_manifest = [
    { evaluator_id: 'insightflow.golden.oracle', evaluator_version: 'oracle-2', config_sha256: 'a'.repeat(64), required: true, requirement: 'required', scope: 'e2e' },
    { evaluator_id: 'insightflow.node.requirement_fidelity', evaluator_version: 'rf-1', config_sha256: null, required: false, requirement: 'optional', scope: 'node' },
  ];
  run.metrics = { ...run.metrics, trust: 'verified', trusted: true, oracle_evaluator_id: 'insightflow.golden.oracle' };
  run.cases = run.cases.map(c => ({ ...c, case_integrity: 'VERIFIED', provenance: 'recorded' }));
  return run;
}
function invalidRun(): RunDetail {
  const run = verifiedRun();
  run.integrity = { ...run.integrity, status: 'INVALID', trusted: false, reasons: ['file_mismatch'],
    files: [{ ref: 'cases/RF-02/result.json', role: 'case_result', case_id: 'RF-02', status: 'mismatch' }, { ref: '/Users/someone/outside.json', role: 'artifact', case_id: null, status: 'outside_run' }] };
  run.metrics = { ...run.metrics, trust: 'partial_verified', trusted: false, included_case_ids: ['RF-01', 'RF-03', 'RF-04', 'RF-05'],
    excluded: [{ case_id: 'RF-02', reason: 'evidence_integrity_invalid' }],
    e2e_confirmed_success_rate: { numerator: 1, denominator: 4, rate: 0.25 }, decidable_pass_rate: { numerator: 1, denominator: 4, rate: 0.25 },
    evaluation_coverage: { numerator: 4, denominator: 4, rate: 1 }, execution_completion_rate: { numerator: 1, denominator: 4, rate: 0.25 } };
  run.cases = run.cases.map(c => c.case_id === 'RF-02' ? { ...c, case_integrity: 'INVALID', attribution: { value: 'evidence_integrity', basis: 'x' } } : c);
  return run;
}
function incompleteRun(): RunDetail {
  const run = verifiedRun();
  run.lifecycle_status = 'INCOMPLETE'; run.finished_at = null;
  run.integrity = { ...run.integrity, status: 'INCOMPLETE', trusted: false, reasons: ['final_manifest_missing'] };
  run.case_counts = { total: 5, present: 2, missing: 3, not_started: 0, unreadable: 0 };
  run.missing_case_ids = ['RF-03', 'RF-04', 'RF-05'];
  run.metrics = { ...run.metrics, trust: 'incomplete', trusted: false, included_case_ids: ['RF-01', 'RF-02'] };
  run.cases = run.cases.map(c => ['RF-03', 'RF-04', 'RF-05'].includes(c.case_id)
    ? { ...c, case_state: 'missing', execution_status: null, blocking_stage: null, e2e_verdict: null, e2e_gate: null, e2e_reason: null,
      attribution: { value: 'not_executed', basis: 'missing' }, case_integrity: 'INCOMPLETE', provenance: null } : c);
  return run;
}

describe('fixtures match the runtime contract checks', () => {
  it('accepts the real B2 bodies', () => {
    expect(isRunDetail(runGfJson)).toBe(true);
    expect(isRunDetail(runRgJson)).toBe(true);
    expect(isDatasetDetail(datasetGoldenJson)).toBe(true);
  });
});

describe('datasets', () => {
  it('lists datasets with freeze status, null version and relation counts, then opens the detail', async () => {
    const fetcher = stub(url => json(url.pathname.endsWith('/datasets') ? datasetsPageJson : datasetGoldenJson));
    view('/evaluations/datasets');
    const table = await screen.findByRole('table', { name: '评测数据集' });
    const golden = within(table).getByRole('link', { name: GOLDEN });
    expect(golden).toHaveAttribute('href', '/evaluations/datasets/' + GOLDEN);
    expect(within(table).getAllByText('未声明冻结')).toHaveLength(2);
    const goldenRow = within(golden.closest('tr') as HTMLElement);
    expect(goldenRow.getByText('未记录')).toBeVisible();
    expect(goldenRow.getByText(/哈希一致 2/)).toBeVisible();
    expect(within(table).getAllByText('typical-suite-v1')).toHaveLength(2);
    for (const name of [/编辑/, /^发布/, /^冻结/]) expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    expect(urls(fetcher)[0].pathname).toBe('/api/v1/admin/evaluations/datasets');

    fireEvent.click(golden);
    expect(await screen.findByRole('heading', { name: '数据集详情' })).toBeVisible();
    await screen.findByRole('table', { name: '关联运行' });
    expect(screen.getByText('fe52a92cc77bb16fa5425f5618c7d7a9dd633f0790eaf341a3c434554a052142')).toBeVisible();
    expect(screen.getByText(/没有正式冻结声明/)).toBeVisible();
    const related = screen.getByRole('table', { name: '关联运行' });
    expect(within(related).getAllByText('哈希一致')).toHaveLength(2);
    expect(within(related).getByRole('link', { name: GF })).toHaveAttribute('href', '/evaluations/runs/' + GF);
    expect(screen.getByRole('table', { name: '需求保真 Golden Set' })).toBeVisible();
    expect(urls(fetcher).at(-1)?.pathname).toBe('/api/v1/admin/evaluations/datasets/' + GOLDEN);
  });

  it('shows a hash mismatch as a different content version, not as corruption', async () => {
    const detail = clone<DatasetDetail>(datasetGoldenJson);
    detail.hash_variants.push({ dataset_hash: 'b'.repeat(64), matches_current_source: false, run_count: 1 });
    detail.related_runs.push({ ...detail.related_runs[0], run_id: 'gf_20261101-000000_aaaaaa', recorded_dataset_hash: 'b'.repeat(64), relation: 'hash_mismatch' });
    detail.related_runs.push({ ...detail.related_runs[0], run_id: 'gf_20261102-000000_bbbbbb', recorded_dataset_hash: null, relation: 'weak_path' });
    stub(() => json(detail));
    view('/evaluations/datasets/' + GOLDEN);
    const related = await screen.findByRole('table', { name: '关联运行' });
    expect(within(related).getByText('哈希不同')).toBeVisible();
    expect(within(related).getByText('仅目录关联，未校验哈希')).toBeVisible();
    expect(screen.getByText(/运行记录的是另一份内容的哈希.*不代表数据损坏/)).toBeVisible();
    expect(screen.getByText('不同（另一份内容，不代表损坏）')).toBeVisible();
    expect(screen.queryByText(/^数据损坏$|^已损坏$/)).not.toBeInTheDocument();
  });

  it('lists a mismatch count separately and flags duplicate dataset ids from discovery', async () => {
    const page = clone<DatasetListPage>(datasetsPageJson);
    page.items[0].hash_mismatch_run_count = 1;
    page.discovery_warnings.push({ code: 'duplicate_dataset_id', root_id: null, entry: 'tc:dup-suite', detail: 'More than one configured source has this dataset id; every copy is excluded.' });
    stub(() => json(page));
    view('/evaluations/datasets');
    expect(await screen.findByText(/另有 1 次记录的哈希不同/)).toBeVisible();
    const warnings = screen.getByRole('region', { name: '发现提示' });
    expect(within(warnings).getByText(/ID 冲突：所有同名来源都已排除/)).toBeVisible();
  });

  it('refuses to pick a source when the dataset id conflicts', async () => {
    stub(() => apiError(409, 'EVALUATION_DATASET_ID_CONFLICT', { dataset_hashes: ['c'.repeat(64), 'd'.repeat(64)], sources: ['docs/a/cases.json', '/Users/x/b.json'] }));
    view('/evaluations/datasets/dup-suite');
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByRole('heading', { name: '数据集 ID 冲突' })).toBeVisible();
    expect(within(alert).getByText(/不会任选其一/)).toBeVisible();
    expect(within(alert).getByText('cccccccccccc…')).toBeVisible();
    expect(within(alert).getByText('docs/a/cases.json')).toBeVisible();
    expect(screen.queryByText(/\/Users\/x/)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '元数据' })).not.toBeInTheDocument();
  });

  it('filters by dataset type and shows the empty state', async () => {
    const fetcher = stub(url => json(url.searchParams.get('dataset_type') ? { items: [], total: 0, page: 1, page_size: 20, discovery_warnings: [] } : datasetsPageJson));
    view('/evaluations/datasets');
    await screen.findByRole('table', { name: '评测数据集' });
    fireEvent.change(screen.getByLabelText('数据集类型'), { target: { value: 'tc' } });
    expect(await screen.findByText('没有符合条件的数据集')).toBeVisible();
    expect(urls(fetcher).at(-1)?.searchParams.get('dataset_type')).toBe('tc');
    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }));
    await screen.findByRole('table', { name: '评测数据集' });
    expect(urls(fetcher).at(-1)?.searchParams.has('dataset_type')).toBe(false);
  });
});

describe('evaluation runs list', () => {
  it('shows lifecycle and integrity separately, null versions, and no guessed E2E metric', async () => {
    const fetcher = stub(() => json(runsPageJson));
    view('/evaluations/runs');
    const table = await screen.findByRole('table', { name: '评测运行' });
    const link = within(table).getByRole('link', { name: GF });
    expect(link).toHaveAttribute('href', '/evaluations/runs/' + GF);
    const row = within(link.closest('tr') as HTMLElement);
    expect(row.getByText('运行已结束')).toHaveAttribute('data-kind', 'lifecycle');
    expect(row.getByText('未校验')).toHaveAttribute('data-kind', 'integrity');
    expect(row.queryByText(/^通过$|E2E 通过|成功/)).not.toBeInTheDocument();
    expect(row.getAllByText('未记录').length).toBeGreaterThanOrEqual(3);
    expect(row.getByText('列表接口不提供，进入详情查看')).toBeVisible();
    expect(within(table).getByText('TC 回归')).toBeVisible();
    expect(screen.queryByRole('button', { name: /运行评测|启动/ })).not.toBeInTheDocument();
    const first = urls(fetcher)[0];
    expect(first.pathname).toBe('/api/v1/admin/evaluations/runs');
    expect(first.searchParams.get('page_size')).toBe('20');
    expect(['run_type', 'status', 'integrity_status', 'page'].some(k => first.searchParams.has(k))).toBe(false);
  });

  it('puts filters and page in the request, resets them, and restores them from the URL', async () => {
    const many = clone<RunListPage>(runsPageJson);
    const fetcher = stub(url => json({ ...many, total: 45, page: Number(url.searchParams.get('page') || 1) }));
    view('/evaluations/runs');
    await screen.findByRole('table', { name: '评测运行' });
    fireEvent.change(screen.getByLabelText('运行类型'), { target: { value: 'golden' } });
    await waitFor(() => expect(urls(fetcher).at(-1)?.searchParams.get('run_type')).toBe('golden'));
    fireEvent.change(screen.getByLabelText('完整性'), { target: { value: 'UNVERIFIED' } });
    await waitFor(() => expect(urls(fetcher).at(-1)?.searchParams.get('integrity_status')).toBe('UNVERIFIED'));
    fireEvent.click(await screen.findByRole('button', { name: '下一页' }));
    await waitFor(() => expect(urls(fetcher).at(-1)?.searchParams.get('page')).toBe('2'));
    expect(urls(fetcher).at(-1)?.searchParams.get('run_type')).toBe('golden');
    expect(await screen.findByText(/第 2 \/ 3 页/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }));
    await waitFor(() => expect(['run_type', 'integrity_status', 'page'].some(k => urls(fetcher).at(-1)?.searchParams.has(k))).toBe(false));
  });

  it('restores lifecycle filter and page after a reload', async () => {
    const fetcher = stub(url => json({ ...clone<RunListPage>(runsPageJson), items: [], total: 0, page: Number(url.searchParams.get('page') || 1) }));
    view('/evaluations/runs?status=INCOMPLETE&page=2');
    expect(await screen.findByText('没有符合条件的评测运行')).toBeVisible();
    expect(screen.getByLabelText('生命周期')).toHaveValue('INCOMPLETE');
    expect(urls(fetcher)[0].searchParams.get('status')).toBe('INCOMPLETE');
    expect(urls(fetcher)[0].searchParams.get('page')).toBe('2');
  });

  it('shows loading and then an empty list', async () => {
    let release: (r: Response) => void = () => {};
    stub(() => new Promise<Response>(resolve => { release = resolve; }));
    view('/evaluations/runs');
    expect(screen.getByRole('status')).toHaveTextContent('正在读取评测运行');
    release(json({ items: [], total: 0, page: 1, page_size: 20, discovery_warnings: [] }));
    expect(await screen.findByText('没有符合条件的评测运行')).toBeVisible();
    expect(screen.getByText('配置的评测目录中还没有可识别的运行。')).toBeVisible();
  });

  it.each([
    [422, 'VALIDATION_ERROR', '请求参数无效'],
    [500, 'INTERNAL_ERROR', '无法加载评测运行'],
  ])('handles %s on the list without leaking server text', async (status, code, title) => {
    stub(() => apiError(status, code, {}, 'Traceback at /Users/someone/backend/app.py'));
    view('/evaluations/runs?status=BROKEN');
    expect(await screen.findByRole('heading', { name: title })).toBeVisible();
    expect(screen.queryByText(/Traceback|\/Users\/someone/)).not.toBeInTheDocument();
    expect(screen.queryByRole('table', { name: '评测运行' })).not.toBeInTheDocument();
  });

  it('treats a malformed response as an error, not as data', async () => {
    stub(() => json({ items: [{ run_id: 'x' }], total: 1, page: 1, page_size: 20, discovery_warnings: [] }));
    view('/evaluations/runs');
    expect(await screen.findByRole('heading', { name: '接口返回结构不正确' })).toBeVisible();
  });
});

describe('run detail', () => {
  it('orders integrity, metrics and cases and explains the historical UNVERIFIED state', async () => {
    const fetcher = stub(() => json(runGfJson));
    view('/evaluations/runs/' + GF);
    await screen.findByRole('table', { name: 'Case Results' });
    const headings = screen.getAllByRole('heading', { level: 2 }).map(h => h.textContent);
    expect(headings).toEqual(['A. 完整性与来源', 'B. 运行指标（不可信：历史记录无法校验）', 'C. Case Results']);
    expect(screen.getByText(/历史运行格式没有 manifest.*未校验不等于证据损坏/)).toBeVisible();
    expect(screen.getByText('legacy_run_has_no_manifest')).toBeVisible();
    expect(screen.getByText('历史格式投影：从历史运行格式投影，缺失字段保持为空。')).toBeVisible();
    expect(screen.getByText('此运行格式没有记录 Evaluator 清单与版本（未记录）。')).toBeVisible();
    const e2e = screen.getByLabelText('E2E 确认成功率');
    expect(within(e2e).getByText('40.0%')).toBeVisible();
    expect(within(e2e).getByText('2 / 5')).toBeVisible();
    expect(within(e2e).getByText('不可信：历史记录无法校验')).toBeVisible();
    expect(within(screen.getByLabelText('评测覆盖率')).getByText('100.0%')).toBeVisible();
    expect(within(screen.getByLabelText('执行完成率')).getByText('2 / 5')).toBeVisible();
    const health = screen.getByRole('table', { name: 'Evaluator 健康度' });
    expect(within(health).getByText('Oracle')).toBeVisible();
    expect(within(health).getByText('未评测')).toHaveAttribute('data-kind', 'evaluator');
    expect(within(health).getByText('0.0%')).toBeVisible();
    expect(urls(fetcher)[0].pathname).toBe('/api/v1/admin/evaluations/runs/' + GF);
  });

  it('shows RF-01 to RF-05 with five independent states', async () => {
    stub(() => json(runGfJson));
    view('/evaluations/runs/' + GF);
    await screen.findByRole('table', { name: 'Case Results' });
    expect(screen.getByText('运行已结束')).toHaveAttribute('data-kind', 'lifecycle');
    for (const id of ['RF-01', 'RF-03']) {
      const row = caseRow(id);
      expect(row.getByText('受阻')).toHaveAttribute('data-kind', 'execution');
      expect(row.getByText('E2E 未通过')).toHaveAttribute('data-kind', 'e2e');
      expect(row.getByText('任务条件')).toBeVisible();
      expect(row.getByText('Agent 执行')).toBeVisible();
      expect(row.getByText('未校验')).toHaveAttribute('data-kind', 'integrity');
    }
    const rf04 = caseRow('RF-04');
    expect(rf04.getByText('执行失败')).toHaveAttribute('data-kind', 'execution');
    expect(rf04.getByText('E2E 未通过')).toBeVisible();
    expect(rf04.getByText('task_not_completed:FAILED')).toBeVisible();
    for (const id of ['RF-02', 'RF-05']) {
      const row = caseRow(id);
      expect(row.getByText('执行完成')).toBeVisible();
      expect(row.getByText('E2E 通过')).toHaveAttribute('data-kind', 'e2e');
      expect(row.getByText('未校验')).toHaveAttribute('data-kind', 'integrity');
      expect(row.getByText('无失败')).toBeVisible();
    }
    // Oracle NOT_EVALUATED is reported per evaluator by the run detail API (3 cases: RF-01, RF-03, RF-04).
    const oracle = within(screen.getByRole('table', { name: 'Evaluator 健康度' })).getByText('insightflow.golden.score_case').closest('tr') as HTMLElement;
    expect(within(oracle).getByText('未评测').parentElement).toHaveTextContent('未评测 3');
    expect(screen.getByText(/运行详情接口不提供逐 Case 的 Evaluator 结果/)).toBeVisible();
    expect(caseRow('RF-01').getByRole('link', { name: 'RF-01' })).toHaveAttribute('href', `/evaluations/runs/${GF}/cases/RF-01`);
  });

  it('marks only a verified run as trusted and shows evaluator versions', async () => {
    const run = verifiedRun();
    stub(() => json(run));
    view('/evaluations/runs/' + run.run_id);
    expect(await screen.findByRole('heading', { name: 'B. 可信指标' })).toBeVisible();
    expect(within(screen.getByLabelText('E2E 确认成功率')).getByText('可信')).toBeVisible();
    expect(screen.getAllByText('证据已校验')[0]).toHaveAttribute('data-kind', 'integrity');
    const manifest = screen.getByRole('table', { name: 'Evaluator 清单' });
    expect(within(manifest).getByText('oracle-2')).toBeVisible();
    expect(within(manifest).getByText('必选')).toBeVisible();
    expect(within(manifest).getByText('可选')).toBeVisible();
    expect(screen.getByText(/insightflow · 版本 agent-1\.4\.0/)).toBeVisible();
  });

  it('labels INVALID metrics as partial statistics and hides out-of-run paths', async () => {
    const run = invalidRun();
    stub(() => json(run));
    view('/evaluations/runs/' + run.run_id);
    expect(await screen.findByRole('heading', { name: 'B. 局部统计（仅校验通过的 Case，不是整次运行结果）' })).toBeVisible();
    expect(screen.getByLabelText('局部 E2E 确认成功率')).toHaveTextContent('25.0%');
    expect(screen.queryByLabelText('E2E 确认成功率')).not.toBeInTheDocument();
    expect(screen.getByText(/不能称为整次运行成功率/)).toBeVisible();
    expect(screen.getByText('已排除 1 个 Case')).toBeVisible();
    expect(screen.getByText('evidence_integrity_invalid')).toBeVisible();
    expect(caseRow('RF-02').getByText('证据校验失败')).toBeVisible();
    expect(caseRow('RF-02').getByText('证据完整性')).toBeVisible();
    expect(screen.getByText('路径已隐藏')).toBeVisible();
    expect(screen.queryByText(/\/Users\/someone/)).not.toBeInTheDocument();
  });

  it('reports no metric when no INVALID case verified', async () => {
    const run = invalidRun();
    run.metrics = { ...run.metrics, trust: 'none', included_case_ids: [], counts: null, e2e_confirmed_success_rate: null,
      decidable_pass_rate: null, evaluation_coverage: null, execution_completion_rate: null, evaluators: [] };
    stub(() => json(run));
    view('/evaluations/runs/' + run.run_id);
    expect(await screen.findByRole('heading', { name: 'B. 运行指标（不报告）' })).toBeVisible();
    expect(within(screen.getByLabelText('E2E 确认成功率')).getByText('无分子分母')).toBeVisible();
  });

  it('shows INCOMPLETE runs with their missing cases and never as finished', async () => {
    const run = incompleteRun();
    stub(() => json(run));
    view('/evaluations/runs/' + run.run_id);
    expect(await screen.findByText('运行未完成')).toHaveAttribute('data-kind', 'lifecycle');
    expect(screen.queryByText('运行已结束')).not.toBeInTheDocument();
    expect(screen.getByText(/缺失 Case：RF-03、RF-04、RF-05/)).toBeVisible();
    expect(caseRow('RF-03').getByText('缺失')).toBeVisible();
    expect(caseRow('RF-03').getByText('无 E2E 结果')).toBeVisible();
    expect(caseRow('RF-03').getByText('无法确定')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'B. 运行指标（运行未完成，仅覆盖已记录 Case）' })).toBeVisible();
  });

  it('shows a zero denominator as not computable', async () => {
    const run = verifiedRun();
    const zero = { numerator: 0, denominator: 0, rate: null };
    run.metrics = { ...run.metrics, decidable_pass_rate: zero, evaluators: [{ evaluator_id: 'insightflow.golden.oracle', counts: {}, error_rate: zero, not_evaluated_rate: zero }] };
    stub(() => json(run));
    view('/evaluations/runs/' + run.run_id);
    const metric = await screen.findByLabelText('可判定样本通过率');
    expect(within(metric).getByText('无法计算（分母为 0）')).toBeVisible();
    expect(within(metric).getByText('0 / 0')).toBeVisible();
    expect(within(screen.getByRole('table', { name: 'Evaluator 健康度' })).getAllByText('无法计算（分母为 0）')).toHaveLength(2);
  });

  it('shows TC not-started cases and links to the original regression record', async () => {
    stub(() => json(runRgJson));
    view('/evaluations/runs/' + RG);
    await screen.findByRole('table', { name: 'Case Results' });
    expect(caseRow('TC01').getByText('未开始')).toBeVisible();
    expect(caseRow('TC01').getByText('未执行')).toBeVisible();
    expect(caseRow('TC02').getByText('E2E 通过')).toBeVisible();
    expect(screen.getByRole('link', { name: '在回归对比中查看' })).toHaveAttribute('href', '/evaluations/regressions/' + RG);
  });

  it.each([
    [404, 'EVALUATION_RUN_NOT_FOUND', '评测运行不存在'],
    [409, 'EVALUATION_RUN_ID_CONFLICT', '运行 ID 冲突，无法唯一定位'],
    [409, 'EVALUATION_RUN_UNREADABLE', '运行目录存在但无法读取'],
    [422, 'VALIDATION_ERROR', '请求参数无效'],
    [500, 'INTERNAL_ERROR', '无法加载评测运行'],
  ])('handles HTTP %s %s', async (status, code, title) => {
    stub(() => status === 404 ? json(error404Json, 404) : apiError(status, code));
    view('/evaluations/runs/' + GF);
    expect(await screen.findByRole('heading', { name: title })).toBeVisible();
    expect(screen.queryByText('服务内部信息')).not.toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Case Results' })).not.toBeInTheDocument();
  });
});

describe('routing', () => {
  it('opens the Case Detail placeholder without calling the API', () => {
    const fetcher = stub(() => json({}));
    view(`/evaluations/runs/${GF}/cases/RF-01`);
    expect(screen.getByRole('heading', { name: 'Case 详情将在下一阶段开放' })).toBeVisible();
    expect(screen.getByText('下一阶段开放')).toBeVisible();
    expect(screen.getAllByRole('link', { name: '返回运行详情' })[0]).toHaveAttribute('href', '/evaluations/runs/' + GF);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('highlights the evaluation navigation for detail paths and leaves trace and regression paths alone', () => {
    expect(currentNavigation('/evaluations/runs/' + GF).page?.key).toBe('evaluation-runs');
    expect(currentNavigation(`/evaluations/runs/${GF}/cases/RF-01`).page?.key).toBe('evaluation-runs');
    expect(currentNavigation('/evaluations/datasets/' + GOLDEN).page?.key).toBe('test-datasets');
    expect(currentNavigation('/evaluations/regressions/' + RG).page?.key).toBe('regression-comparison');
    expect(currentNavigation('/traces/workflows').page?.key).toBe('workflow-explorer');
  });
});
