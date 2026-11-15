import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { isDatasetDetail, isDatasetListPage, isRunDetail, isRunListPage } from '../api/evaluations';

// Real HTTP responses from the B1/B2 backend for scripted scenario runs plus the historical TC run
// (docs/evaluations/evaluation-admin-c1-review-2026-11-13/review_backend.py dump).
interface Captured { request: string; status: number; body: Record<string, unknown> }
const files = import.meta.glob<Captured>('./fixtures/evaluations/review/*.json', { eager: true, import: 'default' });
const captured = Object.fromEntries(Object.entries(files).map(([path, value]) => [path.split('/').pop()!.replace('.json', ''), value]));
const body = <T = Record<string, unknown>,>(name: string) => structuredClone(captured[name].body) as T;
const RUNS = {
  verified: 'gf_20990101-000000_a1a1a1', invalid: 'gf_20990101-000000_a2a2a2', incomplete: 'gf_20990101-000000_a3a3a3',
  empty: 'gf_20990101-000000_a4a4a4', evaluator_error: 'gf_20990101-000000_a5a5a5', rf04_pending: 'gf_20990101-000000_a6a6a6',
  invalid_all: 'gf_20990101-000000_a7a7a7', legacy_mismatch: 'gf_20990101-000000_c2c2c2', tc: 'rg_20261112-133157_f04289',
};
const GOLDEN = 'requirement-fidelity-golden-v1';

function respond(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } }); }
function serve(overrides: Record<string, Captured> = {}) {
  const table = new Map<string, Captured>();
  for (const item of [...Object.values(captured), ...Object.values(overrides)]) table.set(item.request, item);
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    url.searchParams.delete('page_size');
    const key = url.pathname + (url.searchParams.toString() ? '?' + url.searchParams : '');
    const hit = table.get(key);
    return hit ? respond(hit.body, hit.status) : respond({ error: { code: 'NOT_CAPTURED', details: {} } }, 404);
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
function view(path: string) { return render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>); }
function row(table: string, key: string) {
  const found = within(screen.getByRole('table', { name: table })).getByText(key).closest('tr');
  if (!found) throw new Error('missing row ' + key);
  return within(found as HTMLElement);
}
function noBrokenText() {
  expect(document.body.textContent).not.toMatch(/undefined|NaN|\[object Object\]/);
}

describe('real backend responses satisfy the frontend contract', () => {
  it('validates every captured body with the page validators', () => {
    for (const [name, item] of Object.entries(captured)) {
      if (item.status !== 200) continue;
      const ok = name.startsWith('run-') ? isRunDetail(item.body) : name.startsWith('runs-') ? isRunListPage(item.body)
        : name.includes('datasets-page') ? isDatasetListPage(item.body) : isDatasetDetail(item.body);
      expect(ok, name).toBe(true);
    }
  });
});

describe('scenario runs render from real responses', () => {
  it('verified run: trusted metrics and evaluator versions', async () => {
    serve(); view('/evaluations/runs/' + RUNS.verified);
    expect(await screen.findByRole('heading', { name: 'B. 可信指标' })).toBeVisible();
    expect(within(screen.getByLabelText('E2E 确认成功率')).getByText('2 / 5')).toBeVisible();
    const manifest = screen.getByRole('table', { name: 'Evaluator 清单' });
    expect(within(manifest).getByText('golden-oracle-v2')).toBeVisible();
    expect(within(manifest).getByText('适用时必选')).toBeVisible();
    expect(row('Case Results', 'RF-04').getByText('执行失败')).toBeVisible();
    noBrokenText();
  });

  it('INVALID run: partial statistics, excluded RF-02, mismatched file', async () => {
    serve(); view('/evaluations/runs/' + RUNS.invalid);
    expect(await screen.findByRole('heading', { name: /局部统计/ })).toBeVisible();
    expect(screen.getByLabelText('局部 E2E 确认成功率')).toHaveTextContent('1 / 4');
    expect(screen.queryByLabelText('E2E 确认成功率')).not.toBeInTheDocument();
    expect(screen.getByText('已排除 1 个 Case')).toBeVisible();
    expect(screen.getByText('RF-02/result.json')).toBeVisible();
    expect(row('Case Results', 'RF-02').getByText('证据校验失败')).toBeVisible();
    noBrokenText();
  });

  it('INVALID with no verified case: no metric reported', async () => {
    serve(); view('/evaluations/runs/' + RUNS.invalid_all);
    expect(await screen.findByRole('heading', { name: 'B. 运行指标（不报告）' })).toBeVisible();
    expect(screen.getAllByText('不报告').length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText('已排除 5 个 Case')).toBeVisible();
    expect(screen.getByText('没有可统计的 Evaluator 结果。')).toBeVisible();
    noBrokenText();
  });

  it('INCOMPLETE run: missing RF-03 to RF-05, never shown as finished', async () => {
    serve(); view('/evaluations/runs/' + RUNS.incomplete);
    expect(await screen.findByText(/缺失 Case：RF-03、RF-04、RF-05/)).toBeVisible();
    expect(screen.getByText('运行未完成')).toBeVisible();
    expect(screen.queryByText('运行已结束')).not.toBeInTheDocument();
    expect(row('Case Results', 'RF-04').getByText('缺失')).toBeVisible();
    noBrokenText();
  });

  it('run with no recorded case: every denominator is zero', async () => {
    serve(); view('/evaluations/runs/' + RUNS.empty);
    await screen.findByRole('table', { name: 'Case Results' });
    for (const label of ['E2E 确认成功率', '可判定样本通过率', '评测覆盖率', '执行完成率']) {
      const metric = screen.getByLabelText(label);
      expect(within(metric).getByText('无法计算（分母为 0）')).toBeVisible();
      expect(within(metric).getByText('0 / 0')).toBeVisible();
    }
    expect(screen.getByText(/缺失 Case：RF-01、RF-02、RF-03、RF-04、RF-05/)).toBeVisible();
    noBrokenText();
  });

  it('required evaluator error is its own E2E verdict and attribution', async () => {
    serve(); view('/evaluations/runs/' + RUNS.evaluator_error);
    await screen.findByRole('table', { name: 'Case Results' });
    const rf02 = row('Case Results', 'RF-02');
    expect(rf02.getByText('E2E 评测器异常')).toBeVisible();
    expect(rf02.getByText('必选评测器')).toBeVisible();
    expect(rf02.getByText('评测器异常', { selector: 'td' })).toBeVisible();
    const boom = row('Evaluator 健康度', 'boom');
    expect(boom.getByText('100.0%')).toBeVisible();
    noBrokenText();
  });

  it('RF-04 pending must-forbid: E2E NOT_EVALUATED, attribution undetermined', async () => {
    serve(); view('/evaluations/runs/' + RUNS.rf04_pending);
    await screen.findByRole('table', { name: 'Case Results' });
    const rf04 = row('Case Results', 'RF-04');
    expect(rf04.getByText('E2E 未评测')).toBeVisible();
    expect(rf04.getByText('无法判定')).toBeVisible();
    noBrokenText();
  });

  it('legacy run with a different dataset hash keeps dataset id unrecorded', async () => {
    serve(); view('/evaluations/runs/' + RUNS.legacy_mismatch);
    expect(await screen.findByText(/历史运行格式没有 manifest/)).toBeVisible();
    expect(screen.getByText('000000000000…')).toBeVisible();
    noBrokenText();
  });

  it('historical TC run: 15 cases, 14 not started, TC02 recorded', async () => {
    serve(); view('/evaluations/runs/' + RUNS.tc);
    await screen.findByRole('table', { name: 'Case Results' });
    expect(screen.getByRole('table', { name: 'Case Results' }).querySelectorAll('tbody tr')).toHaveLength(15);
    expect(row('Case Results', 'TC01').getByText('未开始')).toBeVisible();
    expect(row('Case Results', 'TC02').getByText('E2E 通过')).toBeVisible();
    expect(screen.getByText(/已记录 1 · 缺失 0 · 未开始 14/)).toBeVisible();
    expect(within(screen.getByRole('table', { name: 'Evaluator 健康度' })).getByText('insightflow.tc.checks')).toBeVisible();
    noBrokenText();
  });
});

describe('datasets from real responses', () => {
  it('golden detail separates 23 hash matches from the mismatched legacy run', async () => {
    serve(); view('/evaluations/datasets/' + GOLDEN);
    const related = await screen.findByRole('table', { name: '关联运行' });
    expect(within(related).getAllByText('哈希一致')).toHaveLength(23);
    expect(row('关联运行', RUNS.legacy_mismatch).getByText('哈希不同')).toBeVisible();
    expect(row('内容哈希', '000000000000…').getByText('不同（另一份内容，不代表损坏）')).toBeVisible();
    noBrokenText();
  });

  it('id conflict across dataset types: list flags both rows, detail refuses with 409', async () => {
    serve({ page: captured['conflict-datasets-page'], detail: captured['conflict-dataset-detail'] });
    view('/evaluations/datasets');
    const table = await screen.findByRole('table', { name: '评测数据集' });
    expect(within(table).getAllByText('ID 冲突')).toHaveLength(2);
    fireEvent.click(within(table).getAllByRole('link', { name: GOLDEN })[0]);
    expect(await screen.findByRole('heading', { name: '数据集 ID 冲突' })).toBeVisible();
    expect(screen.getByText('configured:tc')).toBeVisible();
    expect(screen.queryByRole('region', { name: '元数据' })).not.toBeInTheDocument();
  });
});

describe('real run list with pagination', () => {
  it('pages through 25 runs and filters TC from the real list responses', async () => {
    const fetcher = serve();
    view('/evaluations/runs');
    const table = await screen.findByRole('table', { name: '评测运行' });
    expect(table.querySelectorAll('tbody tr')).toHaveLength(20);
    expect(screen.getByText(/第 1 \/ 2 页/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => expect(screen.getByRole('table', { name: '评测运行' }).querySelectorAll('tbody tr')).toHaveLength(5));
    expect(screen.getByText(/第 2 \/ 2 页/)).toBeVisible();
    fireEvent.change(screen.getByLabelText('运行类型'), { target: { value: 'tc_regression' } });
    await waitFor(() => expect(screen.getByRole('table', { name: '评测运行' }).querySelectorAll('tbody tr')).toHaveLength(1));
    expect(new URL(String(fetcher.mock.calls.at(-1)?.[0])).searchParams.has('page')).toBe(false);
    expect(screen.getByRole('link', { name: RUNS.tc })).toHaveAttribute('href', '/evaluations/runs/' + RUNS.tc);
  });
});

async function settle() {
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
}
function withoutKey(source: Record<string, unknown>, path: string[]) {
  const copy = structuredClone(source);
  let node: Record<string, unknown> = copy;
  for (const key of path.slice(0, -1)) node = node[key] as Record<string, unknown>;
  delete node[path.at(-1)!];
  return copy;
}

describe('a field missing from the backend response never renders broken text', () => {
  const run = body('run-verified');
  const runPaths = [
    ...Object.keys(run).map(k => [k]),
    ...Object.keys(run.metrics as object).map(k => ['metrics', k]),
    ...Object.keys(run.integrity as object).map(k => ['integrity', k]),
    ...Object.keys((run.cases as object[])[0]).map(k => ['cases', '0', k]),
    ...Object.keys(run.case_counts as object).map(k => ['case_counts', k]),
  ];
  it.each(runPaths.map(p => [p.join('.'), p]))('run detail without %s', async (_label, path) => {
    serve({ x: { request: '/api/v1/admin/evaluations/runs/' + RUNS.verified, status: 200, body: withoutKey(run, path as string[]) } });
    view('/evaluations/runs/' + RUNS.verified);
    await settle();
    const contract = screen.queryByRole('heading', { name: '接口返回结构不正确' });
    if (!contract) expect(screen.getByRole('table', { name: 'Case Results' })).toBeVisible();
    noBrokenText();
  });

  const dataset = body('dataset-golden');
  const datasetPaths = [...Object.keys(dataset).map(k => [k]), ...Object.keys((dataset.related_runs as object[])[0]).map(k => ['related_runs', '0', k])];
  it.each(datasetPaths.map(p => [p.join('.'), p]))('dataset detail without %s', async (_label, path) => {
    serve({ x: { request: '/api/v1/admin/evaluations/datasets/' + GOLDEN, status: 200, body: withoutKey(dataset, path as string[]) } });
    view('/evaluations/datasets/' + GOLDEN);
    await settle();
    if (!screen.queryByRole('heading', { name: '接口返回结构不正确' })) expect(screen.getByRole('table', { name: '关联运行' })).toBeVisible();
    noBrokenText();
  });

  const runsPage = body('runs-page-1'), datasetsPage = body('datasets-page');
  it.each([
    ...Object.keys((runsPage.items as object[])[0]).map(k => ['runs', k]),
    ...Object.keys((datasetsPage.items as object[])[0]).map(k => ['datasets', k]),
    ['runs', 'total'], ['datasets', 'discovery_warnings'],
  ])('%s list without %s', async (list, key) => {
    const source = list === 'runs' ? runsPage : datasetsPage;
    const path = ['total', 'discovery_warnings'].includes(key) ? [key] : ['items', '0', key];
    const request = '/api/v1/admin/evaluations/' + list;
    serve({ x: { request, status: 200, body: withoutKey(source, path) } });
    view('/evaluations/' + list);
    await settle();
    expect(screen.getByRole('heading', { name: '接口返回结构不正确' })).toBeVisible();
    noBrokenText();
  });
});
