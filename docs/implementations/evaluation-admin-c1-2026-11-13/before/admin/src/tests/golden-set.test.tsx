import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import { AdminRoutes } from '../app/routes';

it('shows the frozen five-case golden set and the shared nine rows', () => {
  render(<MemoryRouter initialEntries={['/evaluations/datasets']}><AdminRoutes /></MemoryRouter>);
  const data = screen.getByRole('table', { name: '固定 9 行测试数据' });
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
