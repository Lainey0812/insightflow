import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import datasetGolden from './fixtures/evaluations/dataset-golden.json';

it('shows the five-case golden set and the shared nine rows inside the golden dataset detail', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(datasetGolden), { status: 200, headers: { 'content-type': 'application/json' } })));
  render(<MemoryRouter initialEntries={['/evaluations/datasets/requirement-fidelity-golden-v1']}><AdminRoutes /></MemoryRouter>);
  const data = await screen.findByRole('table', { name: '固定 9 行测试数据' });
  expect(within(data).getAllByRole('row')).toHaveLength(10);
  expect(within(data).getByText('J09')).toBeVisible();
  expect(within(data).getByText('杭州')).toBeVisible();
  const cases = screen.getByRole('table', { name: '需求保真 Golden Set' });
  for (const caseId of ['RF-01', 'RF-02', 'RF-03', 'RF-04', 'RF-05']) expect(within(cases).getByText(caseId)).toBeVisible();
  expect(within(cases).getByText('不得读取、解析、聚合、筛选或分组薪资、薪资区间。')).toBeVisible();
  expect(within(cases).getByText(/必须正好输出数据中的全部非上海城市/)).toBeVisible();
  expect(within(cases).getByText('深圳 3、北京 1、杭州 1')).toBeVisible();
  expect(within(cases).queryByText('RF-06')).not.toBeInTheDocument();
});

it('does not show the bundled copy when the API reports a different hash', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...datasetGolden, dataset_hash: 'e'.repeat(64) }), { status: 200, headers: { 'content-type': 'application/json' } })));
  render(<MemoryRouter initialEntries={['/evaluations/datasets/requirement-fidelity-golden-v1']}><AdminRoutes /></MemoryRouter>);
  expect(await screen.findByText(/前端打包的 Golden 副本与当前来源哈希不同/)).toBeVisible();
  expect(screen.queryByRole('table', { name: '需求保真 Golden Set' })).not.toBeInTheDocument();
});
