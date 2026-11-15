# InsightFlow Admin — Prompt Snapshot Foundation V0.1

## 背景

InsightFlow 已完成 Admin 基础框架和 Trace V0.1/V0.2，但当前三个 LLM 节点没有保存完整的历史 Prompt 内容。

需要建立不可变 Prompt 快照机制，为后续 Prompt Registry、版本 Diff、Trace 追溯和回归评测提供可靠数据。

## 目标

建立 Git Prompt 源文件 → 不可变 Prompt Snapshot → LLM Runtime → Trace/RunManifest 的一致性链路。

## 第一阶段：现状审计

检查 Intent Parser、Analysis Planner、Insight Generator：

1. Prompt 实际定义位置及加载方式。
2. System/User Prompt 是否存在动态拼接。
3. Prompt 版本号如何生成。
4. 模型请求最终使用哪些消息。
5. Trace 和 RunManifest 已保存哪些版本字段。
6. Git 历史是否能恢复部分历史 Prompt。

先输出审计结果及方案，不直接大规模重构。

## 第二阶段：不可变快照

设计 PromptSnapshot 数据模型，保存完整模板、组合配置、变量定义、内容哈希、版本标识、Git Commit、创建时间和变更说明。

要求：

- 快照创建后不可修改。
- 同一内容重复登记应幂等。
- 相同版本号但内容不同必须检测冲突。
- 历史缺失内容不能伪造。
- 模板哈希算法稳定且有测试覆盖。

## 第三阶段：运行时绑定

在三个 LLM 节点接入统一的 Prompt 快照解析机制。

要求：

- 实际使用的模板必须与登记快照一致。
- 在发起模型调用前确定 snapshot_id。
- Trace/RunManifest 记录实际 snapshot_id。
- Prompt 渲染失败、快照缺失、内容不匹配时有明确错误语义。
- 不改变现有 Prompt 内容、业务逻辑或模型参数。
- 明确快照存储故障时的失败策略，不能静默记录错误版本。

## 第四阶段：历史版本恢复

尝试从 Git 历史恢复 Prompt 内容。

区分：

- verified：有可靠证据证明版本与实际部署对应。
- reconstructed：从 Git 恢复，但无法证明实际部署关系。
- unavailable：无法恢复完整内容。

不得将 reconstructed 自动标记为 verified。

## 第五阶段：测试

覆盖：

- 三个 LLM 节点的真实 Prompt 快照登记。
- 内容哈希一致性。
- 版本冲突检测。
- 重复登记幂等。
- Trace/RunManifest 版本关联。
- 并发运行。
- 历史 Prompt 缺失。
- Prompt 模板动态拼接。
- 数据库重启后的快照读取。
- 原有 LLM 输出与工作流行为不发生非预期变化。

## 交付

1. Prompt 加载与版本现状审计。
2. 数据契约和数据库迁移方案。
3. 修改文件清单。
4. 三个 LLM 节点的真实快照示例。
5. Trace 关联示例。
6. 测试结果及历史恢复限制。

先完成审计和方案确认，再进入实施。
