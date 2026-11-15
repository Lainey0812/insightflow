import { expect, it, vi } from 'vitest';
import { api } from '../api/client';

it('serializes the selected header row as an upload parameter', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 201 }));
  await api.create(new File(['a\n1'], 'data.csv'), 'test', 'goal_driven', 6);
  const options = fetchMock.mock.calls[0][1];
  expect((options?.body as FormData).get('header_row')).toBe('6');
});
