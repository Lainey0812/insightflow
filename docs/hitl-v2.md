# HITL V2：业务友好的分析方案确认

本轮新增独立展示映射与确定性约束审计，不增加 LLM 节点。界面沿用单页聊天结构，仍使用原计划、版本、批准和执行接口。本阶段只展示拟分析内容与已支持的真实计算，不新增报告、图表或自然语言修订能力。

## 页面与数据映射

| 顺序 | 默认展示 | 真实来源 |
| --- | --- | --- |
| 1 核心分析目标 | 一句话业务目标、核心覆盖提示 | intent_snapshot.analysis_goal.business_goal；覆盖来自 Validator |
| 2 分析范围与统计口径 | 用户指定条件与审计状态；另列方案拟用维度、统计方式和排序/Top N | 原 Intent constraints.raw_text；实际 steps 参数，经字段名和别名映射 |
| 3 分析方向 | 任务标题、业务问题、重要性、拟用口径、真实缺口 | AnalysisTask；ValidationResult；missing_inputs |
| 4 待确认事项 | 阻断原因、解决方式、需确认的重要限制 | 约束审计、uncertainties、目标覆盖、可执行任务；空方案合并同因提示 |
| 5 确认与操作 | 确认并开始分析、移除方向、重新提出需求、技术详情 | 服务端资格；原删除/批准/执行接口；前端新建会话 |

P0/P1/P2 显示为“核心分析/辅助分析/补充分析”。F2 显示“可以分析”，F1 显示“完成已支持的数据转换后可分析”，F0 显示“暂时无法分析”并列出数据或能力缺口。F1 的拟用步骤明确列出日期提取，不宣称语义转换已实现。

“用户指定条件”与“方案拟用口径”分别展示来源。例如用户仅指定“销售额”，而实际方案使用 sum，显示“拟用统计口径：销售额 · 合计”，不把该口径伪称为用户已确认。原字段 ID 与生成别名换成真实列名；未知字段显示缺口，不补造。数值只可能是请求中的年/Top N、真实画像概况或执行后的结果；确认页没有模型编造的分析结论。

原始字段 ID、操作参数、枚举、校验版本、内容摘要与完整审计记录只在可展开的“技术详情”中展示。“版本与审批记录”实际读取不可变计划、审批和对应约束证明。默认页面没有无法工作的 AI 修改按钮。修改范围通过“重新提出需求”创建新会话，旧方案、批准及结果保留。

展示不调用模型，也不修改 IntentResult、AnalysisPlan、ValidatedAnalysisPlan、PlanVersion、ReviewApproval、ApprovedExecutionSnapshot 或 ExecutionResult Schema。

## 现有审批规则审计与最小接线

V1 Validator 负责字段、类型、能力和顺序，不能证明自然语言约束已落实。旧 approve_v1 对非空 constraints 一律拒绝。原 Engine 已有服务端 constraints_confirmed、准确版本与不可变审批快照核对，无需重写。

新增 ConstraintAuditor 为每条约束保留：原字段路径、完整原话、识别的真实字段、实际任务/步骤/参数、通过或失败原因。Intent 原始 validation_status 仍为 unverified，旁存审计结果并不修改模型提取结果。

批准时仍在原 SQLite BEGIN IMMEDIATE 事务内核对当前计划与 expected_revision、重新调用原 Validator、比较保存快照。仅把旧“约束非空即拒绝”谓词替换为“当前所有约束的确定性证明必须通过”。调用失败、语义不明、漏条件、口径不符均拒绝。

真正收到原批准请求后，服务端才设置原快照已有的 constraints_confirmed，并将证明与批准记录原子落盘。客户端不能提交这个布尔值、审计结论或资格。没有自动批准，没有放宽 defer/clarify，没有修改 Engine 闸门。审批仍绑定 dataset/plan/validation 版本；删除仍生成不可变新版本并撤销当前审批；幂等规则不变。

新增 plan_constraint_audits 表以 approval_id 关联原审批，记录 session、批准时间、完整审计、dataset/plan/validation/registry 绑定及内容摘要，配置禁止 UPDATE/DELETE 的触发器。摘要覆盖完整已验证计划、意图与真实画像。没有批准的方案不会创建批准证明；GET 读取时确定性计算当前展示与审计，完整原输入已保存，可追溯重算。

## 确定性映射规则与保守边界

采用有限完整表达式语法，不是通用自然语言理解。只有完整支持的表达才能通过；不会截取几个关键词就宣布整句已验证。

| 条件 | 核验方式 |
| --- | --- |
| 日历年，如“2026年”“发布日期为2026年” | 唯一真实日期字段，聚合前 gte 年初 + lt 次年初；或受支持 extract_year 后 eq 年份。多日期字段无明确指向则阻断 |
| 精确分类筛选 | 明确原始字段名与取值，例如“岗位状态为在招”；紧凑表达仅在样本值精确、不截断且唯一匹配时接受，不做同义词匹配 |
| 排除 | 显式“排除”映射 ne，逐项核对字段与原始取值；不把“不排除”改成排除 |
| 指标 | 真实原字段 + 明确函数（合计/均值/中位数/极值/去重数等）；裸字段只证明该数值指标参与计算，具体拟用函数另外展示；记录数不等同于 count(field) |
| 分组维度 | 明确“按/按照 + 原字段 + 汇总/分组”等；不能偷偷增加第二个维度 |
| 升降序/Top N | 指向聚合后真实指标别名；排序方向、截取数量、执行位置完整一致。指标不唯一则阻断，不猜测排序依据 |
| 禁止分析某字段 | 对应原字段在所有任务结构中不得被引用，包括不可执行任务；未识别的禁止行为继续阻断 |
| 未指定/非必选/复杂否定 | 不升级为要求或禁令；当前无法结构化证明的表达保留阻断，不通过映射反转语义 |

所有实际执行方向均需满足已识别的明确条件，不能在一个任务证明筛选、另一个任务证明指标后拼成“整体通过”。存在无依据额外筛选、聚合后过滤、提前 Top N、多次聚合或额外分组时阻断。不可执行核心方向和覆盖问题仍按原 Validator/HITL 规则处理。

这个策略故意偏保守：合理的辅助汇总如果不符合全局条件，也可能需要删除或重新提出需求。复杂日期范围、相对时间、自由中文、非连续语义等价、任意数值区间和复杂禁止行为未作通用支持。例如真实招聘案例“只看2026年发布”仍被阻断；重新提出明确的“发布日期为2026年”才通过。不是模型失败，也不会用勾选绕过。

本审计证明的是**保存的 Intent 约束与可执行步骤的结构一致性**，不能证明整个 LLM 意图没有遗漏、用户目标已在业务上完整解决，或已经产生正确统计结论；这些仍需人工审核及原 Engine 计算。没有进行新的大样本模型语义质量验收。

## 接口与服务端资格

新增接口均沿用会话凭证，不接收客户端计划或批准标志：

- GET `/api/v1/sessions/{id}/review`：ReviewPresentation，包括当前 revision/plan ID/版本、目标、条件、方向、问题、原警告 ID、can_approve/can_execute、审计与技术原文。重新读取原画像并运行 Validator。读取不修改批准状态。
- GET `/api/v1/sessions/{id}/constraint-audits`：已批准记录旁存的不可变证明。历史证明不代表新版本已批准。

前端仅在返回的会话、revision、plan ID、版本全部匹配且服务端允许时启用按钮。加载失败、旧响应、并发变更均禁用；重要限制仍需逐项确认。按钮点击后仍由原 POST approvals 与 POST executions 重新核验，不能靠篡改前端授权。

## 文件变更

新增：

- backend/app/domain/review_presentation.py：独立 ViewModel 与审计契约。
- backend/app/review/constraint_audit.py：有限语法、字段/步骤证明与额外范围检查。
- backend/app/review/presentation.py：纯确定性业务展示映射。
- frontend/src/components/BusinessPlanReview.tsx：服务端资格驱动的业务确认卡片。
- backend/tests/review_v2_fixtures.py、test_review_v2.py：四主题真实服务集成和失败用例。
- frontend/src/tests/business-review.test.tsx、review-fixtures.ts、fixtures/review-v2.json：展示、加载失败、过期响应、禁止伪造资格等。
- examples/hitl-v2/*.csv、docs/evaluations/hitl-v2/*：合成源文件、真实浏览器/模型/批准/结果/截图及对照。

修改：

- backend/app/services/plan_review.py：资格与展示入口；原审批事务中增加确定性证明核验/旁存，其他门禁保留。
- backend/app/storage/plan_review_repository.py：仅新增不可变约束证明表与读取。
- backend/app/api/routes.py：两个受原会话凭证保护的只读接口。
- frontend/src/components/PlanReviewCard.tsx：真实分支转交 BusinessPlanReview；历史 Mock 卡片隔离保留。
- frontend/src/components/MessageList.tsx、App.tsx：重新提出需求入口、状态信息转业务语言；不改流程编排。
- frontend/src/components/WorkflowProgress.tsx：技术错误码折叠展示。
- frontend/src/api/client.ts、types/contracts.ts、styles.css：ViewModel、请求与布局。
- frontend/src/tests/hitl-v1.test.tsx、real-workflow.test.tsx：沿用原交互覆盖，适配新服务端资格与业务标签。
- README 与原模块文档：指向 V2，保留历史验收记录。

Engine、Validator、六类内核、Intent/Planner Prompt 与原共享 Schema 等 10 个核心文件哈希未变。没有新依赖、新模型调用或报告实现。

## 测试与实际证据

后端 562 passed（原 527 + 新 35），前端 40 passed（原 30 + 新 10），TypeScript/Vite 构建成功。命令仍为 backend 的 `../.venv/bin/python -m pytest -q`，frontend 的 `npm test`、`npm run build`。

四类场景通过真实浏览器上传、现有模型规划、原批准接口与 Engine 计算，独立 Pandas 对照一致。另保留未映射招聘时间的阻断案例，以及项目方向删除后 v2 不可批准/刷新/重启/原 v1 结果保留的记录。用户原 60 行销售会话未被代为批准，已恢复到新版可确认页面。

详见 [完整浏览器与审计验收](evaluations/hitl-v2/report.md)、[目标与范围截图](evaluations/hitl-v2/review-goal-and-scope.jpg)、[分析方向与操作截图](evaluations/hitl-v2/review-directions-and-actions.jpg)。易用性结论基于字段/文案/交互检查，尚未开展普通业务人员的定时可用性研究。
