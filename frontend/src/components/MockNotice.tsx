import { FlaskConical } from 'lucide-react';
export function MockNotice({ legacyMock = false, realReview = false, realWorkflow = false }: { legacyMock?: boolean; realReview?: boolean; realWorkflow?: boolean }) {
  return <div className="mock-notice"><FlaskConical size={15} /><span>{realWorkflow ? '真实数据与 AI 规划 · 人工批准后计算并生成报告' : realReview ? '真实画像、计划校验与计算 · 计划需人工提交，报告尚未接入' : legacyMock ? '历史会话 · 画像、计划与报告均为 Mock 示例' : '数据画像使用真实文件 · 计划与报告仍为 Mock 示例'}</span></div>;
}
