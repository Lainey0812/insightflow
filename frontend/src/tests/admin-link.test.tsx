import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WorkflowProgress } from '../components/WorkflowProgress';
import { adminBaseUrl, adminWorkflowUrl } from '../config/admin';
import type { Session } from '../types/contracts';

const session: Session = {
  id: 's1', title: '分析销售', status: 'AWAITING_APPROVAL', revision: 3, updated_at: '2026-11-09T10:00:00Z',
  created_at: '2026-11-09T10:00:00Z', data_source: 'uploaded', workflow_kind: 'real_v1',
  file: { id: 'file', name: 'sales.csv', size: 12, extension: '.csv' },
  user_goal: '分析销售', analysis_mode: 'goal_driven', current_plan_version: null, approved_plan_version: null,
  plans: [], messages: [], report: null, error: null,
};

describe('admin link', () => {
  it('builds the workflow detail URL from the configured admin base', () => {
    expect(adminBaseUrl(undefined)).toBe('http://127.0.0.1:5174');
    expect(adminBaseUrl('https://admin.example.com/')).toBe('https://admin.example.com');
    expect(adminBaseUrl('javascript:alert(1)')).toBeNull();
    expect(adminBaseUrl('not a url')).toBeNull();
    expect(adminWorkflowUrl('wf_a/b', 'http://127.0.0.1:5174')).toBe('http://127.0.0.1:5174/traces/workflows/wf_a%2Fb');
    expect(adminWorkflowUrl('wf_1', null)).toBeNull();
  });

  it('shows the workflow id and opens the matching admin detail page', () => {
    render(<WorkflowProgress session={{ ...session, workflow_id: 'wf_123' }} busy={false} onRetry={() => {}}/>);
    expect(screen.getByText('wf_123')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: '在 Admin 中查看' });
    expect(link).toHaveAttribute('href', 'http://127.0.0.1:5174/traces/workflows/wf_123');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('hides the admin entry for sessions without a registered workflow', () => {
    render(<WorkflowProgress session={session} busy={false} onRetry={() => {}}/>);
    expect(screen.queryByText('运行编号')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '在 Admin 中查看' })).not.toBeInTheDocument();
  });
});
