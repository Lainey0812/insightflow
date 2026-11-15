import { Link } from 'react-router-dom';
import { EmptyState } from '../components/EmptyState';
import { Workflow } from 'lucide-react';
import type { NavigationPage } from '../app/navigation';

export function ModulePlaceholderPage({ page }: { page: NavigationPage }) {
  if (!page.enabled) return <>
    <div className="page-heading"><span className="eyebrow">INSIGHTFLOW ADMIN</span><h1>{page.label}</h1><p>当前开放运行追踪、Prompt 管理、Bad Case 与回归对比。</p></div>
    <EmptyState icon={Workflow} title="暂未开放" statusLabel="暂未开放" description="此模块暂不开放访问，请使用运行追踪或 Prompt 管理。" note="可从左侧进入已开放功能。" />
    <p><Link className="primary-button" to="/traces/workflows">打开 Workflow</Link></p>
  </>;
  const detail = page.key === 'trace-detail';
  return <>
    <div className="page-heading"><span className="eyebrow">INSIGHTFLOW ADMIN</span><h1>{page.label}</h1><p>{page.later ? '后期功能' : detail ? '选择真实运行查看详情' : '后台模块入口'}</p></div>
    <EmptyState statusLabel={detail ? '请选择真实运行' : page.later ? '后期功能' : undefined} icon={Workflow} title={detail ? '尚未选择运行' : page.later ? '后期开放' : '尚未接入'} description={page.description || '本模块尚未接入管理接口。'} note={detail ? '从真实运行列表进入，保留完整的运行 ID 和来源。' : '当前仅提供导航与页面框架，不展示模拟业务数据或不可用的操作。'} />
    {detail && <p><Link className="primary-button" to="/traces/workflows">打开 Workflow</Link></p>}
  </>;
}
