# InsightFlow Evaluation Platform — Phase 2-A：Admin 架构设计与实施规划

## 一、任务背景

Phase 1 已完成评测内核：

- EvaluationRun、CaseExecution、EvaluatorResult、E2ESummary 统一契约。
- Golden / TC 历史运行适配。
- Evaluator Protocol 和 E2E Hard Gates。
- MustForbidEvaluator 与 Constraint Coverage Mapping。
- Manifest 文件完整性校验。
- 统一指标计算与 trusted_metrics()。
- 历史评测结果只读兼容。

现在进入 Phase 2：将已有评测能力接入 InsightFlow Admin，形成可操作的评测结果查看与问题定位工作流。

**本阶段只设计，不编码。**

## 二、产品目标

Admin 的目标用户是 AI 产品经理、评测工程师、算法工程师和质量负责人。

核心任务是让用户回答：

1. 当前有哪些测试集？
2. 某次评测使用了哪个数据集、Agent 版本和 Evaluator 配置？
3. 哪些 Case 通过、失败或无法评判？
4. 失败是 Agent 执行问题、业务质量问题，还是评测基础设施问题？
5. 具体哪个 Evaluator 失败，依据是什么？
6. 能否查看对应的 Trace、计划和执行证据？
7. 这次评测结果是否完整、可信？

本阶段不提供从 Admin 启动评测、编辑测试集或自动创建 Bad Case 的能力。

## 三、Stage A：现有代码审查

检查实际仓库中的：

- Admin 路由及导航。
- Golden Set 页面。
- Evaluation Runs 占位页面。
- Regression Comparison 页面。
- Workflow Trace 页面。
- Bad Case 页面。
- 后端现有 Admin API。
- Phase 1 的 evaluation 模块。
- 现有数据读取、分页和错误处理模式。

输出复用矩阵：

| 现有模块 | 当前能力 | 可复用部分 | 需要新增 | 潜在冲突 |
|---|---|---|---|---|

特别检查 `/traces` 的历史路由冲突，不要未经分析就修改路由。

## 四、Stage B：页面信息架构

设计四个页面。

### 1. Dataset List / Detail

展示：

- Dataset ID。
- Dataset Version。
- Case 数量。
- 数据集 Hash。
- 冻结状态。
- 关联的 Evaluation Runs。

注意：只有存在明确版本和冻结证据时才能显示 Frozen；历史静态数据不能自动推断为正式发布版本。

### 2. Evaluation Runs

统一展示 Golden 和 TC。

建议字段：

- Run ID。
- Agent。
- Dataset。
- Run Type。
- Created At。
- Execution / Run Status。
- Integrity Status。
- E2E Success Rate。
- Evaluated Case Count。

必须区分：

- 运行未完成。
- 运行完成但存在失败。
- 运行完成但证据不可信。
- 历史数据无法验证完整性。

### 3. Run Detail

分为：

**运行概览**

展示配置、版本、完整性、指标和 Case 状态分布。

**Case Results**

展示每条 Case 的：

- Case ID。
- Execution Status。
- E2E Verdict。
- Failure Origin。
- Required Evaluator Results。
- Integrity Status。

**Case Detail**

展示：

- 用户任务或测试目标。
- 执行结果。
- Oracle 结果。
- MustForbid 结果。
- Node Fidelity 结果。
- Hard Gate 失败原因。
- Evidence References。
- Plan / Engine 证据。
- Trace 入口。

需要明确哪些数据来自历史投影，哪些来自新版本的真实记录。

### 4. Trace / Evidence

优先复用现有 Workflow Trace 组件。

如果评测运行只有本地 Trace JSON，而没有可查询的 Workflow ID，设计只读证据查看方案，不允许生成虚假的 Workflow ID。

## 五、Stage C：API 契约

设计最小只读 API：

- GET /api/admin/evaluations/datasets
- GET /api/admin/evaluations/datasets/{dataset_id}
- GET /api/admin/evaluations/runs
- GET /api/admin/evaluations/runs/{run_id}
- GET /api/admin/evaluations/runs/{run_id}/cases/{case_id}
- GET /api/admin/evaluations/runs/{run_id}/cases/{case_id}/evidence

以上路径是候选方案，需要结合现有 FastAPI 路由规范确认。

每个 API 明确：

- Request 参数。
- Response Schema。
- 分页、排序与筛选。
- 404、409、422、500 等错误语义。
- 历史缺失字段的处理。
- 数据完整性状态。
- 数据来源及投影标识。

禁止直接把本地文件绝对路径返回给前端。

### 安全边界

- 只能读取配置允许的评测根目录。
- 不允许通过 Run ID 或 Case ID 拼接任意文件路径。
- Evidence 输出需要限制大小并明确脱敏策略。
- 不得暴露模型 API Key、完整连接凭据或不必要的原始用户输入。
- INVALID 的运行不能显示为可信的质量结果。

## 六、Stage D：指标与状态展示规则

必须分别设计：

1. Run Lifecycle Status。
2. Case Execution Status。
3. Evaluator Verdict。
4. E2E Verdict。
5. Integrity Status。

不得合并为单一 Success/Failure。

区分：

- E2E 确认成功率。
- 可判定样本通过率。
- 评测覆盖率。
- 执行完成率。
- Evaluator Error Rate。

历史 UNVERIFIED 与新运行 VERIFIED 不得在没有说明的情况下混合汇总为可信指标。

INVALID 结果不得直接进入可信质量统计。

特别处理：

- TC 历史运行没有 Manifest。
- 历史 Golden 的 Evaluator Version 为空。
- Agent Version 为空。
- RF-01、RF-03 的 BLOCKED。
- RF-04 的 FAILED。
- 必选 Evaluator NOT_EVALUATED。
- INCOMPLETE 运行。

## 七、Stage E：实施拆分

将 Phase 2 后续开发拆为可独立验收的小阶段。

建议：

**Phase 2-B：后端只读 API**

实现统一 Run 索引、Dataset 查询、Run Detail、Case Detail、Evidence API。

**Phase 2-C：Admin 页面**

实现 Dataset、Run List、Run Detail、Case Detail，并复用现有 Trace。

**Phase 2-D：端到端验收**

从历史 Golden、历史 TC、新 Golden 运行验证完整查看流程。

请根据实际仓库依赖调整拆分，但不得将所有功能合并为一次大改造。

## 八、交付要求

最终输出：

1. 现有 Admin 代码审查结果。
2. 页面信息架构及页面间跳转关系。
3. API 契约与 JSON 示例。
4. 后端模块划分及数据流。
5. 前端组件复用方案。
6. 历史兼容方案。
7. 数据完整性和权限边界。
8. Phase 2-B / 2-C / 2-D 的开发任务及验收标准。
9. 潜在风险和需要产品决策的问题。

如发现已有模块可以直接复用，不得重复开发。

如发现 Phase 1 数据契约不足以支持某个页面字段，应明确列出缺口，不得伪造字段。

**完成 Phase 2-A 设计后停止，等待架构审核，不自动进入编码。**
