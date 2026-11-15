import { Navigate, Route, Routes } from 'react-router-dom';
import { AdminLayout } from '../layouts/AdminLayout';
import { DashboardPage } from '../pages/DashboardPage';
import { WorkflowsPage } from '../pages/WorkflowsPage';
import { WorkflowDetailPage } from '../pages/WorkflowDetailPage';
import { TracesPage } from '../pages/TracesPage';
import { TraceComparisonPage } from '../pages/TraceComparisonPage';
import { TraceDetailPage } from '../pages/TraceDetailPage';
import { VersionsPage } from '../pages/VersionsPage';
import { SettingsPage } from '../pages/SettingsPage';
import { ModulePlaceholderPage } from '../pages/ModulePlaceholderPage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { AccessBoundary } from '../auth/AccessBoundary';
import type { AccessResolver } from '../auth/AccessBoundary';
import { navigationPages } from './navigation';
import { PromptsPage } from '../pages/PromptsPage';
import { PromptHistoryPage } from '../pages/PromptHistoryPage';
import { PromptVersionPage } from '../pages/PromptVersionPage';
import { PromptComparePage } from '../pages/PromptComparePage';
import { PromptCallPage } from '../pages/PromptCallPage';
import { BadCasesPage } from '../pages/BadCasesPage';
import { BadCaseDetailPage } from '../pages/BadCaseDetailPage';
import { RegressionsPage } from '../pages/RegressionsPage';
import { RegressionDetailPage } from '../pages/RegressionDetailPage';

const pages = { 'regression-comparison': RegressionsPage, 'bad-case-list': BadCasesPage, 'workflow-explorer': WorkflowsPage, dashboard: DashboardPage, 'run-explorer': TracesPage, 'version-comparison': VersionsPage, environment: SettingsPage, 'prompt-list': PromptsPage, 'prompt-versions': PromptComparePage };
export function AdminRoutes({ resolveAccess }: { resolveAccess?: AccessResolver }) {
  return <Routes><Route element={<AdminLayout />}>
    <Route index element={<Navigate to="/traces" replace />} />
    {navigationPages.map(page => {
      const Page = pages[page.key as keyof typeof pages];
      return <Route key={page.key} path={page.path} element={<AccessBoundary permission={page.permission} resolve={resolveAccess}>{page.enabled && Page ? <Page /> : <ModulePlaceholderPage page={page} />}</AccessBoundary>} />;
    })}
    <Route path="/traces/workflows/:workflowId" element={<AccessBoundary permission="traces:view" resolve={resolveAccess}><WorkflowDetailPage /></AccessBoundary>} />
    <Route path="/traces/compare" element={<AccessBoundary permission="traces:view" resolve={resolveAccess}><TraceComparisonPage /></AccessBoundary>} />
    <Route path="/traces/:runId" element={<AccessBoundary permission="traces:view" resolve={resolveAccess}><TraceDetailPage /></AccessBoundary>} />
    <Route path="/evaluations/regressions/:runId" element={<AccessBoundary permission="evaluations:view" resolve={resolveAccess}><RegressionDetailPage /></AccessBoundary>} />
    <Route path="/bad-cases/:caseId" element={<AccessBoundary permission="bad-cases:view" resolve={resolveAccess}><BadCaseDetailPage /></AccessBoundary>} />
    <Route path="/prompts/calls/:callId" element={<AccessBoundary permission="prompts:view" resolve={resolveAccess}><PromptCallPage /></AccessBoundary>} />
    <Route path="/prompts/:promptId/versions/:snapshotId" element={<AccessBoundary permission="prompts:view" resolve={resolveAccess}><PromptVersionPage /></AccessBoundary>} />
    <Route path="/prompts/:promptId" element={<AccessBoundary permission="prompts:view" resolve={resolveAccess}><PromptHistoryPage /></AccessBoundary>} />
    <Route path="*" element={<NotFoundPage />} />
  </Route></Routes>;
}
