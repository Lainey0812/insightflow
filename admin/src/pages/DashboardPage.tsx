import { LayoutDashboard } from 'lucide-react';
import { EmptyState } from '../components/EmptyState';

export function DashboardPage() {
  return <><div className="page-heading"><span className="eyebrow">OVERVIEW</span><h1>运行总览</h1><p>查看分析工作流的整体运行情况。</p></div>
    <EmptyState icon={LayoutDashboard} title="暂无运行数据" description="运行监控接口尚未接入。接入后，这里将展示真实工作流的运行概况。" note="本阶段仅搭建页面与导航，不计算成功率、运行次数或耗时指标。" /></>;
}
