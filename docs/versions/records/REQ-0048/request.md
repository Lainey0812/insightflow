# InsightFlow Admin — Prompt Registry V1

## 目标

在现有 InsightFlow Admin 中建立 Prompt 版本管理能力，支持 Intent Parser、Analysis Planner 和 Insight Generator 三个 LLM 节点的 Prompt 历史查询、版本详情、文本 Diff 和 Trace 关联。

本轮只读，不实现在线修改或发布。

## 第一阶段：审计

检查三个 LLM 节点当前的：

- Prompt 文件与加载方式。
- System/User Prompt 的组成。
- Prompt 版本标识。
- 模型配置及输出 Schema。
- RunManifest 是否记录实际 Prompt 版本。
- 现有 Trace API 和 Admin 前端结构。

重点判断：目前是否真正保存了历史 Prompt 内容，还是只保存了版本号。

先输出审计结论与最小数据契约，不要直接重构 Prompt 加载机制。

## 第二阶段：Prompt Registry

设计并实现 PromptVersion 数据契约，至少包含：

- prompt_id
- node_id
- version
- content_hash
- system_template
- user_template
- variables_schema
- output_schema_ref
- source_commit
- change_summary
- created_at

PromptVersion 一旦登记不可修改；允许创建新版本。

历史内容必须来自真实保存的文件或快照，不能根据当前 Prompt 反推旧版本。

## 第三阶段：只读 API

基于现有 Admin API 风格提供：

- Prompt 列表。
- 指定 Prompt 的版本历史。
- 指定版本详情。
- 两个版本的文本 Diff。
- 根据 Run ID 查询实际使用的 Prompt 版本。

复用现有鉴权、脱敏与错误处理机制。

## 第四阶段：Admin 页面

开发：

1. `/prompts`：Prompt 列表。
2. `/prompts/:promptId`：版本历史。
3. `/prompts/:promptId/versions/:version`：版本详情。
4. Prompt Compare：左右并排的文本 Diff。

支持按节点筛选、版本选择、复制内容、空状态和错误状态。

## 第五阶段：Trace 集成

在 Run Detail 和 LLM Node Inspector 中展示实际 Prompt 版本。

支持跳转到对应 PromptVersion。

如果历史 Run 没有版本信息，显示 unknown，不允许使用当前 Prompt 代替。

## 第六阶段：验收

- 三个 LLM 节点均能查询真实 Prompt。
- 历史版本内容不可变。
- 任意两个已有版本可以比较。
- Trace 能关联实际版本。
- 旧 Run 缺失版本时正确处理。
- Admin 构建和后端测试通过。
- 不改变现有业务工作流行为。

## 交付要求

先提交审计报告和数据契约，确认后再实施代码。

完成后提供修改文件、API 示例、真实版本对比示例、测试结果和剩余限制。
