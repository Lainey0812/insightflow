# V1.1.1 / report-insights-v1.1.9 最终候选交付

关联 REQ-0041 / REQ-0040；本说明不是新的用户需求或业务验收。

恢复较稳定的原 Prompt 结构；保留所有中间试验。最终源码与哈希在 `final-guard-source` / `final-guard-lock.json`。公开 AnalysisReport、Insight 和 Draft Schema 不变；Planner、Validator、HITL、Engine、Workflow 业务代码哈希未变。

最终冻结真实模型评测：3 complete、9 partial、3 failed、1 unavailable。补齐全时间型结果的稳定性守卫后，用同一批原始响应复验，16/16 状态不变；不是新的模型调用。随后新独立未见集首次评测：2 complete、3 partial、2 failed、1 unavailable。没有在看过新集后继续调实现。

670 后端测试、52 前端测试及构建通过；19 份报告含 unavailable 在隔离 SQLite 保存并重新读取，来源和展示一致。原销售数据数值核对通过，但最终 S01 报告真实生成失败，不冒充报告成功。

A–G 逐例代理审阅发现新集 U02 建议触及客单价禁止边界，报告及展示为硬失败。仍有否定/核查表达误拦及核心语义覆盖不足。因此建议暂不通过 V1.1.1 业务验收。详情与所有 Bad Case 见本目录 README、semantic-review、bad-cases 及 cases。
