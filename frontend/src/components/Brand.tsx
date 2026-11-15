import { ChartNoAxesCombined } from 'lucide-react';

export function Brand({ small = false }: { small?: boolean }) {
  return <span className={`brand-mark ${small ? 'small' : ''}`} aria-hidden="true"><ChartNoAxesCombined size={small ? 17 : 23} strokeWidth={2} /></span>;
}
