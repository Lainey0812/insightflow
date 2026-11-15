import { ChartNoAxesCombined, Compass, Layers3 } from 'lucide-react';
import { Brand } from './Brand';

const suggestions = [
  { icon: ChartNoAxesCombined, title: '看清业务趋势', prompt: '帮我分析销售额的变化趋势，以及不同产品的销售贡献。' },
  { icon: Layers3, title: '找到关键贡献', prompt: '帮我比较不同产品的销售贡献，找出值得关注的产品。' },
  { icon: Compass, title: '探索数据可能', prompt: '探索这份数据，帮助我发现值得关注的现象。' },
];
export function Welcome({ onSuggestion, disabled = false }: { onSuggestion: (value: string, exploratory: boolean) => void; disabled?: boolean }) {
  return <div className="welcome">
    <div className="welcome-symbol"><Brand /></div>
    <h1>今天，想从数据中了解什么？</h1>
    <p className="welcome-description">上传一份表格，聊聊你的业务问题。<br />我们一起确认分析方案，再让数据给出答案。</p>
    <div className="suggestions" aria-label="分析问题示例">{suggestions.map((item, index) =>
      <button key={item.title} disabled={disabled} onClick={() => onSuggestion(item.prompt, index === 2)}><item.icon size={16} /><span>{item.title}</span></button>
    )}</div>
    <p className="welcome-note">从一个具体问题开始，也可以先探索数据。</p>
  </div>;
}
