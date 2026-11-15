import { useRef, type FormEvent, type KeyboardEvent } from 'react';
import { ArrowUp, Compass, FileSpreadsheet, LoaderCircle, Paperclip, Sparkles, X } from 'lucide-react';
import type { AnalysisMode } from '../types/contracts';
import { MockNotice } from './MockNotice';

interface Props {
  text: string; file: File | null; mode: AnalysisMode; busy: boolean; hasSession: boolean; locked: boolean;
  running?: boolean; lockReason?: string;
  headerRow: string; onHeaderRow: (value: string) => void;
  legacyMockProfile?: boolean; realReview?: boolean; realWorkflow?: boolean; clarifying?: boolean;
  onText: (text: string) => void; onFile: (file: File | null) => void; onMode: (mode: AnalysisMode) => void;
  onSubmit: () => void; onNew: () => void;
}
export function MessageComposer({ text, file, mode, busy, hasSession, locked, running = false, lockReason, headerRow, onHeaderRow, legacyMockProfile, realReview, realWorkflow, clarifying = false, onText, onFile, onMode, onSubmit, onNew }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const disabled = busy || locked || running;
  const validHeader = headerRow.trim() !== '' && Number.isInteger(Number(headerRow)) && Number(headerRow) >= 1 && Number(headerRow) <= 100001;
  const canSend = !disabled && (hasSession ? !!text.trim() : !!file && validHeader && (!!text.trim() || (!realReview && mode === 'exploratory')));
  const placeholder = running ? '本次分析运行中，请等待处理完成…' : locked ? (lockReason || '请查看对话中的分析方案与结果。') : clarifying ? '请回答上方问题，补充必要的信息…' : hasSession ? '告诉我怎样调整计划…' : '上传表格，描述你想了解的业务问题…';
  function submit(event: FormEvent) { event.preventDefault(); if (canSend) onSubmit(); }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (canSend) onSubmit(); }
  }
  return <div className="composer-area">
    {running && <p className="composer-running-note" id="composer-lock-notice"><LoaderCircle size={13} className="spin"/>正在处理本次分析，完成前暂不能发送新内容。</p>}
    <form aria-label="聊天输入" className={`composer ${disabled ? 'busy' : ''} ${locked && !running ? 'read-only' : ''}`} onSubmit={submit} onDragOver={event => { if (!hasSession && !disabled) event.preventDefault(); }} onDrop={event => { event.preventDefault(); if (!hasSession && !disabled) onFile(event.dataTransfer.files[0] ?? null); }}>
      {file && !hasSession && <div className="selected-file"><FileSpreadsheet size={20} /><span><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(1)} KB</small></span><button className="icon-button" type="button" aria-label="移除文件" onClick={() => onFile(null)} disabled={disabled}><X size={14} /></button></div>}
      {file && !hasSession && <div className="file-settings"><label htmlFor="header-row">表头在第 <input id="header-row" aria-label="表头行" type="number" min={1} max={100001} step={1} value={headerRow} onChange={event => onHeaderRow(event.target.value)} disabled={disabled} aria-invalid={!validHeader} aria-describedby="header-row-help" /> 行</label><span id="header-row-help">{validHeader ? '表头之前的行不参与分析' : '请输入 1–100001 之间的整数'}</span></div>}
      <textarea aria-label={locked ? '对话输入（暂不可用）' : clarifying ? '补充分析需求' : hasSession ? '修改分析计划' : '分析需求'} aria-describedby={running ? 'composer-lock-notice' : undefined} value={text} onChange={event => onText(event.target.value)} onKeyDown={keyDown} placeholder={placeholder} maxLength={2000} rows={locked && !running ? 1 : 2} disabled={disabled} />
      <div className="composer-toolbar"><div className="composer-options">
        {!hasSession && <><input ref={input} type="file" accept=".csv,.xlsx" hidden aria-label="上传数据文件" onChange={event => { if (!disabled) onFile(event.target.files?.[0] ?? null); event.target.value = ''; }} disabled={disabled} /><button className="attach-button" type="button" onClick={() => input.current?.click()} disabled={disabled}><Paperclip size={18} /><span>上传数据</span></button><span className="toolbar-divider" /><button className={`mode-button ${mode === 'goal_driven' ? 'selected' : ''}`} aria-pressed={mode === 'goal_driven'} type="button" onClick={() => onMode('goal_driven')} disabled={disabled}><Sparkles size={13} />目标驱动</button><button className={`mode-button ${mode === 'exploratory' ? 'selected' : ''}`} aria-pressed={mode === 'exploratory'} type="button" onClick={() => onMode('exploratory')} disabled={disabled}><Compass size={13} />探索分析</button></>}
        {hasSession && <span className="revision-hint">{running ? '运行中' : clarifying ? '补充后继续分析' : locked ? '方案与结果保留在当前对话中' : '历史 Mock 计划修订'}</span>}
      </div>{locked && !busy && !running ? <button className="composer-new" type="button" onClick={onNew}>开始新的咨询</button> : <button className="send-button" type="submit" disabled={!canSend} aria-label="发送">{busy || running ? <LoaderCircle className="spin" size={19} /> : <ArrowUp size={21} />}</button>}</div>
    </form>
    <div className="composer-footnote">{!hasSession && !locked && <span>CSV / XLSX · 单文件不超过 10 MB</span>}<MockNotice legacyMock={legacyMockProfile} realReview={realReview} realWorkflow={realWorkflow}/></div>
  </div>;
}
