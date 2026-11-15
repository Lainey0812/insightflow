# InsightFlow Evaluation Platform — Phase 2-C1 实施任务

## 一、目标

你是一名资深 React、TypeScript 前端架构师和 AI 产品工程师。

基于已完成的 Phase 2-B1/B2 后端 API，以及 Phase 2-A 架构设计，实现 InsightFlow Admin 的评测管理页面。

首先阅读：

- `docs/designs/evaluation-admin-v1-2026-11-13/DESIGN.md`
- REQ-0146、REQ-0147、REQ-0150、REQ-0152。
- Admin 现有路由、布局、导航和 API Client。
- 现有 Golden Set、Regression Comparison、Workflow Trace 页面。
- Phase 2-B1/B2 的实际 Pydantic Response Models。

**必须使用真实 API 契约，不得根据任务书中的字段自行猜测后端结构。**

## 二、开发范围

### 1. Dataset List / Detail

复用现有 Golden Set 页面，接入：

- `GET /api/v1/admin/evaluations/datasets`
- `GET /api/v1/admin/evaluations/datasets/{dataset_id}`

展示数据集 ID、类型、版本、哈希、Case 数量、冻结声明和关联运行。

要求：

- `UNDECLARED` 显示为「未声明冻结」。
- 版本为 null 时显示「未记录」。
- 区分 `hash_match`、`hash_mismatch` 和无法验证的关联。
- 不允许将哈希不匹配直接显示为数据损坏。
- 数据集 ID 存在冲突时展示明确错误，不随意选择其中一个来源。
- 支持分页、筛选、加载中、空列表和请求失败状态。

不开发数据集编辑、发布或冻结操作。

### 2. Evaluation Runs

替换现有 Runs 占位页面，接入：

`GET /api/v1/admin/evaluations/runs`

展示：

- Run ID、Run Type。
- Agent ID / Version。
- Dataset ID / Version。
- 创建时间。
- Run Lifecycle Status。
- Integrity Status。
- Case 数量。
- E2E 指标或其可用性说明。

支持运行类型、生命周期、完整性筛选及分页。

要求：

- 不混淆 FINISHED 与 E2E PASS。
- UNVERIFIED 不等于 INVALID。
- INCOMPLETE 不得显示为成功完成。
- 缺失版本显示「未记录」。
- 列表 API 未提供的指标不得由前端猜测。
- 运行点击后进入 `/evaluations/runs/:runId`。

### 3. Run Detail

接入：

`GET /api/v1/admin/evaluations/runs/{run_id}`

页面按以下顺序组织：

**A. 完整性与来源**

展示 Integrity Status、Provenance、数据集及 Evaluator 版本。

**B. 运行指标**

展示：

- E2E 确认成功率。
- 可判定样本通过率。
- 评测覆盖率。
- 执行完成率。
- Evaluator Error Rate。

必须显示指标的分子、分母和可信度。

INVALID 运行只允许展示明确标记的局部统计，不得称为整次运行成功率。

**C. Case Results**

展示：

- Case ID。
- Execution Status。
- E2E Verdict。
- E2E Gate。
- Failure Attribution。
- Case Integrity。
- 必选 Evaluator 的摘要（仅当 API 实际提供）。

支持点击 Case 进入 `/evaluations/runs/:runId/cases/:caseId`。

C1 只实现 Case Detail 导航入口，不开发完整详情内容。

如果目标页面尚未实现，应提供明确的「下一阶段开放」占位页面，不得出现空白页或错误路由。

## 三、状态语义

前端必须独立展示：

1. Run Lifecycle Status。
2. Case Execution Status。
3. Evaluator Verdict。
4. E2E Verdict。
5. Integrity Status。

禁止把上述状态合并为单一的成功/失败。

特别验证：

- RF-01、RF-03：BLOCKED，E2E FAIL。
- RF-04：FAILED，Oracle NOT_EVALUATED。
- RF-02、RF-05：历史 E2E PASS，但 Integrity UNVERIFIED。
- 新 Golden 运行：若证据 VERIFIED，才可展示可信指标。

历史运行的 UNVERIFIED 必须有可见说明。

## 四、前端架构

优先复用现有：

- Admin Layout。
- API Client。
- Table、Pagination、Status Badge。
- Error / Empty State。
- Golden Set 页面结构。

允许抽取公共组件，但不要为了抽象而重构无关页面。

新增 API 类型应尽可能与后端 Pydantic Response Models 对齐。

不得在多个页面重复定义同一状态枚举。

不得将 API 返回的本地路径或内部错误堆栈展示给用户。

## 五、交互与异常处理

至少覆盖：

- Loading。
- Empty。
- API Error。
- 404。
- 409。
- 422。
- Pagination。
- Filter Reset。
- 页面刷新后恢复路由。
- null 字段。
- 指标分母为零。
- UNVERIFIED / INVALID / INCOMPLETE。

对于 API 返回 413，不需要在 C1 实现 Evidence 处理。

所有页面只读，不出现可点击但没有真实功能的「运行评测」「编辑数据集」等操作。

## 六、测试要求

使用 Mock API 测试 UI 行为，但页面实现必须真实连接后端 API。

至少覆盖：

1. Dataset 列表加载与详情。
2. 数据集冻结状态。
3. 数据集哈希不匹配。
4. 数据集 ID 冲突。
5. Run 列表与筛选分页。
6. Run Detail。
7. 五种状态独立展示。
8. 历史 Golden 的 RF-01～RF-05。
9. INVALID 的局部统计标识。
10. INCOMPLETE 的缺失 Case。
11. 版本为 null。
12. 指标分母为零。
13. API 404、409、422、500。
14. 空列表与 Loading。
15. Case Detail 占位路由。
16. 不影响 Regression Comparison。
17. 不修改 `/traces` 路由。
18. TypeScript Typecheck。
19. Admin Build。
20. 历史文件哈希不变。

额外执行一次前后端联调，验证页面请求与真实 B1/B2 API 的字段一致。

## 七、严格禁止

- 不修改 Agent、Planner、Engine、HITL。
- 不修改 Phase 1 Evaluator。
- 不修改 Golden Set。
- 不修改历史运行。
- 不修改 `/traces` 路由。
- 不开发 Case Detail 正式页面。
- 不开发 Evidence Trace。
- 不开发 Bad Case 自动回流。
- 不新增数据库。
- 不开发 Admin 启动评测。
- 不进入 Phase 2-C2。

## 八、交付报告

完成后提供：

1. 新增和修改文件。
2. 页面路由与导航结构。
3. API 对接情况。
4. Dataset / Runs / Run Detail 页面截图或可验证的渲染证据。
5. 自动化测试、Typecheck、Build 结果。
6. 前后端联调结果。
7. 历史数据完整性验证。
8. 已知限制。
9. 是否达到 Phase 2-C2 的进入条件。

测试与截图证据保存到新的独立目录，不覆盖此前记录。

**完成 Phase 2-C1 后停止，等待审核，不自动进入 C2。**
