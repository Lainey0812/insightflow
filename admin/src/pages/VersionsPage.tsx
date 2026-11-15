import { Link } from 'react-router-dom';
export function VersionsPage() {
  return <><div className="page-heading"><span className="eyebrow">VERSION COMPARISON</span><h1>版本对比</h1><p>查看历史运行实际保存的版本，核对两次报告生成记录。</p></div>
    <section className="trace-card"><h2>从真实 Run 追溯版本</h2><p>每次运行的不可变 RunManifest 保存当时采集的 Prompt、模型、校验器、源码和输入指纹。没有采集的信息显示 unknown。</p><p><Link className="primary-button" to="/traces">选择两次历史运行</Link> <Link className="trace-link" to="/traces/compare">通过 Run ID 对比</Link></p><p className="muted">本页不提供评测分数、Prompt 编辑或版本发布管理。需求与源码历史档案继续保存在项目本地。</p></section>
  </>;
}
