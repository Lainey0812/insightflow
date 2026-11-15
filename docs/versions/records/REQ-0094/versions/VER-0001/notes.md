# REQ-0094 报告容量检查与分批生成交付

2026-11-05。完成用户确认的容量预检、分批生成、全局校验及既有失败报告恢复。保留全部核心指标和旧档案，停止本阶段，不自动进行报告UI或业务洞察优化。

## 修改文件

新增：

- `backend/app/reporting/capacity.py`：共享预算与只读审批容量估算。
- `backend/app/reporting/batches.py`：完整指标组分批、真实调用、逐批事实校验、合并与错误隔离。
- `backend/tests/test_report_capacity.py`：17项专项测试。

修改：

- `backend/app/services/analysis_report.py`：接入分批与全量计划核心覆盖，保存批次结果、缺失指标和部分状态；公开AnalysisReport不变。
- `backend/app/domain/review_presentation.py`：新增可选ReportCapacity侧车；历史响应/数据保持可读。
- `backend/app/services/plan_review.py`：展示资格与真实审批事务采用同一容量预检，不修改批准快照或执行权限契约。
- `backend/app/workflow/reporting.py`：硬容量错误明确不可盲目重试，仍复用原队列、批准绑定及C19持久提交路径。
- `backend/app/observability/recorder.py`：允许安全批次诊断字段，保持fail-open及原状态枚举。
- `backend/app/llm/templates.py`：将批次/容量代码纳入真实组合来源登记，最终组合版本0.6，Prompt正文与模型参数不变。
- `frontend/src/types/contracts.ts`、`components/BusinessPlanReview.tsx`：显示真实容量估算，按钮仍绑定服务端资格。
- `frontend/src/components/ReportGenerationCard.tsx`：不可重试硬容量错误不展示无效重试按钮。
- `frontend/src/tests/business-review.test.tsx`、`report-workflow.test.tsx`：容量展示/阻断及不可重试交互。

没有改动Planner、Engine计算内核、HITL批准事务一致性、Root状态转换、Admin源码、数据库Schema或公开AnalysisReport Schema。沒有新Agent、汇总LLM或第三层Trace。

## 验证结果

- 后端1585、Frontend70、Admin88项全部通过；前端与Admin构建通过。
- 固定9核心指标，两次真实模型调用完整覆盖；最终代码独立Pandas一致。
- 冻结S01/S03真实API主流程均完整交付；原单批报告兼容。
- 用户60条上传记录的原执行：9核心/11总指标，2批合并11条合法洞察，complete；原计划、审批、执行载荷及执行次数与备份相同，4任务独立Pandas一致。
- 浏览器点击原“重新生成报告”完成恢复，报告可预览，最终后端重启/刷新后保持可读。report_id=report_f66380c68d99402d8a4363dd24bcc4f6。
- 失败Report Run、旧Prompt/源码、原始评测器失败与初版容量实现均保留。

详细证据见 `docs/evaluations/report-capacity-v1-2026-11-05/README.md`，恢复截图为同目录recovered-report.png，脱敏C19/Trace/调用关联见live-recovery-evidence.json。用户原始请求内容留在受控本地Registry，未存入公开评测文件。

## 预算、风险与运行

每调用8指标组/80证据/160KiB，总计64指标组/8批。预检是估算；实际证据仍核验，超预算不隐瞒失败、不自动删除指标。部分批次失败时保留合法结果并明确partial，全部无有效洞察则失败。空/null核心指标不会因为没有Evidence而被误认为完成。

不支持按批次持久化断点Resume或对已completed的partial报告自动只重试失败批次；沿用既有报告恢复入口。报告文字冗余、长小数与建议质量尚需独立改进。

最终后端已启动在127.0.0.1:8000，前端5173正常，用户可以继续查看恢复报告及新建分析。此次改动不代表整体MVP业务验收通过。
