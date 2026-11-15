import { LayoutDashboard, Workflow, FileText, GitCompareArrows, Activity, FlaskConical, Bug, Settings2 } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { AdminPermission } from '../auth/AccessBoundary';

export interface NavigationPage {
  key: string;
  path: string;
  label: string;
  permission: AdminPermission;
  description?: string;
  later?: boolean;
  enabled?: boolean;
}
export interface NavigationGroup {
  key: string;
  label: string;
  icon: LucideIcon;
  children: readonly NavigationPage[];
}
export const dashboardNavigation: NavigationPage = { key: 'dashboard', path: '/dashboard', label: '运行总览', permission: 'dashboard:view' };
export const navigationGroups: readonly NavigationGroup[] = [
  { key: 'workflows', label: '工作流管理', icon: Workflow, children: [
    { key: 'workflow-overview', path: '/workflows/overview', label: '工作流概览', permission: 'workflows:view', description: '后续查看各阶段的职责、连接关系与接入状态。工作流管理接口尚未接入。' },
    { key: 'understanding', path: '/workflows/understanding', label: 'Understanding', permission: 'workflows:view', description: '需求理解与数据画像的后台管理入口尚未接入；现有业务模块继续通过原流程运行。' },
    { key: 'planning', path: '/workflows/planning', label: 'Planning', permission: 'workflows:view', description: '分析规划与校验的后台管理入口尚未接入。' },
    { key: 'execution', path: '/workflows/execution', label: 'Execution', permission: 'workflows:view', description: '执行阶段的后台管理接口尚未接入。已采集的报告运行可从运行追踪查看。' },
    { key: 'reporting', path: '/workflows/reporting', label: 'Reporting', permission: 'workflows:view', description: '报告模块专属管理接口尚未接入。已有报告 Trace 仍可在 Run Explorer 中查询。' },
  ] },
  { key: 'prompts', label: 'Prompt 管理', icon: FileText, children: [
    { key: 'prompt-list', path: '/prompts', label: 'Prompt 列表', permission: 'prompts:view', enabled: true },
    { key: 'prompt-versions', path: '/prompts/versions', label: '版本详情与 Diff', permission: 'prompts:view', enabled: true },
    { key: 'playground', path: '/prompts/playground', label: 'Playground', permission: 'prompts:view', later: true, description: '后期提供受控的 Prompt 调试入口，目前不调用模型或提供编辑、运行功能。' },
  ] },
  { key: 'versions', label: '版本与发布', icon: GitCompareArrows, children: [
    { key: 'node-versions', path: '/versions/nodes', label: '节点版本', permission: 'versions:view', description: '节点版本目录与发布管理尚未接入。单次运行已采集的版本可从 RunManifest 查看。' },
    { key: 'workflow-releases', path: '/versions/releases', label: 'Workflow Releases', permission: 'versions:view', description: 'Workflow 发布记录与发布操作尚未实现。' },
    { key: 'version-comparison', path: '/versions', label: '版本对比', permission: 'versions:view' },
  ] },
  { key: 'traces', label: '运行追踪', icon: Activity, children: [
    { key: 'workflow-explorer', path: '/traces/workflows', label: 'Workflow', permission: 'traces:view', enabled: true },
  ] },
  { key: 'evaluations', label: '评测中心', icon: FlaskConical, children: [
    { key: 'test-datasets', path: '/evaluations/datasets', label: '测试数据集', permission: 'evaluations:view', enabled: true },
    { key: 'evaluation-runs', path: '/evaluations/runs', label: 'Evaluation Runs', permission: 'evaluations:view', description: '评测运行列表与调度接口尚未接入，不展示模拟分数或运行结果。' },
    { key: 'regression-comparison', path: '/evaluations/regressions', label: '回归对比', permission: 'evaluations:view', enabled: true },
  ] },
  { key: 'bad-cases', label: 'Bad Case', icon: Bug, children: [
    { key: 'bad-case-list', path: '/bad-cases', label: '问题列表', permission: 'bad-cases:view', enabled: true },
    { key: 'bad-case-replay', path: '/bad-cases/replays', label: '回放结果', permission: 'bad-cases:view', enabled: true },
    { key: 'bad-case-detail', path: '/bad-cases/detail', label: '问题详情', permission: 'bad-cases:view', enabled: true, description: '请先从问题列表或 Workflow 详情选择一条 Bad Case。此入口未预选问题。' },
  ] },
  { key: 'system', label: '系统管理', icon: Settings2, children: [
    { key: 'roles', path: '/settings/roles', label: '权限与角色', permission: 'settings:view', description: '多用户账户、权限与角色管理尚未实现。Trace 沿用现有服务端管理员只读凭证。' },
    { key: 'environment', path: '/settings', label: '环境配置', permission: 'settings:view' },
    { key: 'operation-audit', path: '/settings/audit', label: '操作审计', permission: 'settings:view', description: '管理操作审计 API 尚未接入，工作流 Trace 不等同于管理员操作审计。' },
  ] },
];
export const dashboardIcon = LayoutDashboard;
export const navigationPages = [dashboardNavigation, ...navigationGroups.flatMap(group => group.children)];
export function currentNavigation(pathname: string) {
  const key = pathname.startsWith('/traces') ? 'workflow-explorer' : pathname.startsWith('/prompts/') && !['/prompts/versions', '/prompts/playground'].includes(pathname) ? 'prompt-list'
    : pathname.startsWith('/bad-cases/replays') ? 'bad-case-replay'
    : /^\/bad-cases\/[^/]+$/.test(pathname) ? 'bad-case-detail'
    : pathname.startsWith('/evaluations/regressions/') ? 'regression-comparison' : undefined;
  const page = key ? navigationPages.find(item => item.key === key) : navigationPages.find(item => item.path === pathname);
  const group = navigationGroups.find(item => item.children.some(child => child.key === page?.key));
  return { page, group };
}
