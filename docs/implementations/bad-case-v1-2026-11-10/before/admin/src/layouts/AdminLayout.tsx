import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { ChevronRight, ChevronDown, Layers3, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useEffect, useState } from 'react';
import { currentNavigation, dashboardIcon as DashboardIcon, dashboardNavigation, navigationGroups } from '../app/navigation';

export function AdminLayout() {
  const [expanded, setExpanded] = useState(() => typeof window === 'undefined' || window.innerWidth > 680);
  const { pathname } = useLocation();
  const { page, group } = currentNavigation(pathname);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  useEffect(() => { if (group) setOpenGroups(previous => ({ ...previous, [group.key]: true })); }, [group]);
  const closeOnSmallScreen = () => { if (window.innerWidth <= 680) setExpanded(false); };
  return <div className={`admin-shell ${expanded ? '' : 'sidebar-collapsed'}`}>
    <a className="skip-link" href="#main-content">跳转到内容</a>
    {expanded && <button className="sidebar-backdrop" aria-label="关闭导航" onClick={() => setExpanded(false)} />}
    <aside id="admin-sidebar" className="sidebar" aria-label="管理台侧边栏">
      <NavLink className="brand" to="/traces" onClick={closeOnSmallScreen}><span className="brand-symbol"><Layers3 size={23} /></span><span>InsightFlow<small>ADMIN CONSOLE</small></span></NavLink>
      <div className="nav-section-label">测试管理</div>
      <nav aria-label="主导航">
        <button type="button" disabled aria-disabled="true" title="暂未开放" aria-label={dashboardNavigation.label} className="nav-item nav-disabled"><DashboardIcon size={19} strokeWidth={1.7} /><span>{dashboardNavigation.label}</span></button>
        {navigationGroups.map(({ key, label, icon: Icon, children }) => {
          const enabled = children.some(child => child.enabled);
          const isOpen = enabled && (openGroups[key] ?? group?.key === key);
          return <div className="nav-group" key={key}>
            <button type="button" disabled={!enabled} aria-disabled={!enabled} title={enabled ? undefined : '暂未开放'} className={`nav-group-toggle ${enabled && group?.key === key ? 'contains-active' : ''}`} aria-expanded={isOpen} aria-controls={'nav-' + key} onClick={() => setOpenGroups(previous => ({ ...previous, [key]: !isOpen }))}>
              <Icon size={19} strokeWidth={1.7} /><span>{label}</span>{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            <div id={'nav-' + key} className="nav-children" hidden={!isOpen}>{children.map(child => child.enabled ? <Link key={child.key} to={child.path} onClick={closeOnSmallScreen} aria-label={child.label} aria-current={page?.key === child.key ? 'page' : undefined} className={`nav-item nav-child ${page?.key === child.key ? 'active' : ''}`}>
              <span>{child.label}</span>{child.later && <small className="nav-later">后期</small>}
            </Link> : <span key={child.key} role="link" aria-disabled="true" aria-label={child.label + (child.later ? '（后期）' : '')} title="暂未开放" className="nav-item nav-child nav-disabled"><span>{child.label}</span>{child.later && <small className="nav-later">后期</small>}</span>)}</div>
          </div>;
        })}
      </nav>
      <div className="sidebar-footer"><span className="local-marker">LOCAL / V0.3</span><p>测试与追溯</p><small>已接入功能使用真实记录。</small></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="topbar-start"><button className="icon-button" aria-label={expanded ? '收起侧边栏' : '展开侧边栏'} aria-controls="admin-sidebar" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}</button><span className="breadcrumb">管理控制台 <ChevronRight size={14} />{group && <><span>{group.label}</span><ChevronRight size={14} /></>}<strong>{page?.label ?? '页面不存在'}</strong></span></div><span className="preview-badge">V0.3 · 测试管理</span></header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        <div className="framework-notice"><span className="neutral-dot" />当前仅开放运行追踪与 Prompt 管理；其他模块暂未开放。</div>
        <Outlet />
        <footer className="page-footer"><span>InsightFlow Admin Console</span><span>仅展示已采集记录 · 缺失信息不推断</span></footer>
      </main>
    </div>
  </div>;
}
