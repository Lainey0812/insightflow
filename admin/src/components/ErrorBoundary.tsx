import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Future error reporting belongs here. Do not ship stack traces or env data
    // to an external service before a real reporting contract is implemented.
  }
  render() {
    if (this.state.failed) return <main className="fatal-error"><span className="eyebrow">INSIGHTFLOW ADMIN</span><h1>管理台暂时无法显示</h1><p>请检查本地配置，或重新加载页面后重试。</p><button className="primary-button" onClick={() => window.location.reload()}>重新加载</button></main>;
    return this.props.children;
  }
}
