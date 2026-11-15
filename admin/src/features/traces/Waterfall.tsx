import type { TraceSpan } from '../../types/traces';
import { StatusBadge } from './TraceShared';
import { barPlacement, durationText, flattenSpans, nodeLabels, nodeType, nodeTypes, timeScale, traceStatus } from './presentation';

export function WorkflowWaterfall({ phases, selectedId, onSelect }: {
  phases: { label: string; spans: TraceSpan[] }[];
  selectedId?: string;
  onSelect: (spanId: string) => void;
}) {
  return <div className="waterfall" aria-label="Workflow 瀑布流">
    {phases.map(phase => {
      const rows = flattenSpans(phase.spans);
      const scale = timeScale(phase.spans);
      return <div key={phase.label}>
        {phases.length > 1 && <p className="waterfall-phase">{phase.label}</p>}
        <div className="waterfall-axis" aria-hidden="true"><span>节点</span><span>{scale ? `起点 → ${durationText(scale.span)}` : '时间未采集，不估算位置'}</span><span>耗时</span></div>
        {rows.map(({ span, depth, warning }) => {
          const view = traceStatus(span.status);
          const kind = nodeType(span.name);
          const bar = barPlacement(span, scale);
          const selected = selectedId === span.span_id;
          return <button key={span.span_id} type="button" className={`waterfall-row ${view === 'error' || view === 'suspended' ? 'span-failed' : ''} ${selected ? 'span-selected' : ''}`} aria-pressed={selected} onClick={() => onSelect(span.span_id)}>
            <span className="waterfall-name" style={{ paddingLeft: depth * 12 }}><strong>{nodeLabels[span.name] || span.name}</strong><StatusBadge status={span.status} /><small>{kind ? nodeTypes[kind] : '未归类'} · {span.name}</small>{warning && <em>{warning}</em>}</span>
            <span className="waterfall-track">{bar ? <i className={`waterfall-bar waterfall-bar-${view}`} style={{ left: `${bar.left}%`, width: `${bar.width}%` }} /> : <i className="waterfall-bar waterfall-bar-unknown" />}</span>
            <span className="waterfall-duration">{durationText(span.duration_ms)}</span>
          </button>;
        })}
      </div>;
    })}
  </div>;
}
