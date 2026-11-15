# InsightFlow Admin — Prompt Registry V0.1 实施任务

## 背景

已完成三个 LLM 节点的 Prompt 加载路径审计。

确认当前 Prompt 不只存在于 prompt.py，还包括服务层的动态组装、重试指令、能力说明、业务范围文案和动态输出 Schema。

现有 Trace 只记录 System Prompt 哈希，无法还原完整 LLM 请求。

## 目标

建立可靠的 Prompt 模板版本管理和 LLM 调用级快照机制，为后续 Prompt Diff、版本对比和回归评测提供基础。

## 第一阶段：数据契约

设计：

1. PromptTemplateSnapshot：不可变的固定指令模板与组合定义。
2. LLMCallRecord：一次实际模型调用的记录。
3. LLMRequestSnapshot：该次调用的最终消息、Schema 和模型配置快照。
4. 与现有 TraceSpan、RunManifest 的关联关系。

优先复用现有 Trace 数据结构，避免重复建立运行事实来源。

## 第二阶段：模板快照

覆盖三个 LLM 节点：

- Intent Parser
- Analysis Planner
- Insight Generator

登记 System Prompt、固定 User 模板、重试指令、固定能力说明及相关组合逻辑版本。

要求不可变、内容哈希稳定、重复登记幂等、版本冲突可检测。

保留 Git Commit 和代码来源，但不能将未经验证的 Git 历史冒充实际部署版本。

## 第三阶段：真实调用捕获

在三个节点最终发起 LLM API 调用的边界统一记录：

- 实际发送的消息内容或受控快照引用。
- 最终输出 Schema。
- 模型名称与实际请求参数。
- 调用序号、重试序号。
- Prompt 模板快照 ID。
- 消息和 Schema 哈希。
- 调用结果、错误、耗时。
- 关联 Run ID、Span ID。

不得通过重新执行 Prompt 拼接逻辑来推测历史请求。

## 第四阶段：一致性保证

确保：

- 模板登记内容与运行时实际加载内容一致。
- 不因 Python 模块导入缓存而错误标记版本。
- 每次重试都有独立调用记录。
- Schema 动态变化能够正确追溯。
- 快照写入失败有明确的失败或降级策略，不能伪造成功记录。
- 原始请求受权限和保留策略保护。

## 第五阶段：兼容性与测试

验证：

1. 三个 LLM 节点正常调用。
2. 首次调用和重试均可追溯。
3. 不同 Evidence ID 产生的 Schema 正确区分。
4. 同一模板版本可关联多个不同调用快照。
5. 旧 Run 缺失完整请求时显示 unavailable。
6. 并发运行不会串联错误的 Call ID。
7. 业务输出不发生非预期变化。
8. 数据库重启后记录可查询。

本轮不修改 Prompt 内容、不调整业务规则、不增加 LLM 节点。

## 交付

- 数据契约和数据库迁移。
- 实际调用捕获实现。
- Trace 关联示例。
- 至少三个节点的真实请求组装测试。
- 自动化测试结果。
- 未覆盖的历史记录和已知限制。

完成后再开发 Prompt Registry 的列表、版本详情与 Diff 页面。
