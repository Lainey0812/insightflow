import { Link } from 'react-router-dom';
import { FileQuestion } from 'lucide-react';

export function NotFoundPage() {
  return <section className="not-found"><FileQuestion size={38} strokeWidth={1.4} aria-hidden="true" /><span className="eyebrow">404</span><h1>页面不存在</h1><p>请检查地址，或从侧边栏进入管理页面。</p><Link className="primary-button" to="/traces/workflows">返回运行追踪</Link></section>;
}
