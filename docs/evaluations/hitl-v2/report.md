# HITL V2 交付与浏览器验收

日期：2026-10-27。目标：让普通业务人员审核“分析什么、什么范围、什么口径、有哪些缺口”，并用确定性证明替代 V1 对约束的一律拒绝。没有新增展示模型调用或报告能力。

## 交付

新增独立 Plan Presentation Mapper / ReviewPresentation、服务端资格接口和 ConstraintAuditor。页面按目标 → 范围口径 → 方向 → 待确认 → 操作展示。原始字段 ID、参数、Schema/摘要/枚举仅在技术详情中；优先级与可执行性采用业务文字。实际映射与文件清单详见 [HITL V2 文档](../../hitl-v2.md)，编码前方案见 [设计记录](design.md)。

两个核心截图已人工查看，文字可读、条件与拟用口径区分明确，未显示未经计算的结论：

- [核心目标、需求条件与拟用口径](review-goal-and-scope.jpg)
- [业务问题、真实缺口、确认与重新提出需求](review-directions-and-actions.jpg)
- [未映射时间条件保留阻断](jobs-blocked.jpg)
- [删除后新版本阻断、旧版结果保留](projects-after-delete.jpg)

截图使用用户现有浏览器视口，没有为了截图缩小字体或扩大视口。当前浏览器已恢复到用户原 60 行销售会话，等待用户确认，未代为批准。

## 审批审计结果

原 Validator 只证明字段/类型/操作链，不能证明自然语言约束。V2 审批仍使用同一事务、版本检查、警告确认和快照，批准时额外重新核对每条 Intent 条件。只有所有证明通过才设置原有 constraints_confirmed 并原子写入不可变 plan_constraint_audits；客户端不能提交资格或这个布尔值。Engine、Validator、六类操作、Intent/Planner Prompt 和共享契约均未修改，10/10 核心文件哈希保持一致，见 [保护清单](protected-modules.json)。

每条证明记录完整来源路径、原始表达、真实字段 ID、匹配的任务/步骤/参数和结论；原 Intent validation_status 仍保留 unverified，不伪造模型状态。审计绑定准确数据集/计划/校验/能力版本与完整输入摘要，批准记录另绑定会话。所有执行方向完整继承条件；禁止用不同任务各自满足一半条件来冒充整体通过。缺字段、不支持能力、defer、错误步骤、歧义和未知表达继续阻断。

这证明的是 Intent 条件与计划结构一致，不证明整个自然语言业务目标绝无遗漏或业务理解达到全量语义验收。方案口径明确作为拟用内容展示，最后仍需用户审核。

### 用户已有销售需求（未替用户执行）

真实文件 insightflow_sales_orders_test.csv，画像 60 行、12 列。原 Intent 约束：2026 年、华东地区、已完成订单、销售额、按照城市汇总并降序排名取前三名。

审计完整追踪到真实 Planner 产生的地区/状态过滤、extract_year 后 eq 2026、城市分组 sum 销售额和降序 top_n=3。F1 转换以业务文字展示。全部条件通过，当前 can_approve=true，仍无审批或执行。原始状态与逐条证明见 [用户当前方案](user-sales-current-review.json)，最终界面见 [DOM](final-user-review-dom.txt)。

## 真实浏览器端到端

采用正常页面上传、提交和批准按钮，没有把受控 Provider 冒充模型。四类合成源文件位于 examples/hitl-v2，内容实际存储、画像与执行。模型仍为 qwen3.8-flash，原 Prompt intent-v1.3.3 / planner-v1.2，enable_thinking=false，30 秒超时、最多 2 次尝试。五个测试会话共 [10 次真实模型返回](live-model-calls.json)：5 次 Intent + 5 次 Planner，全为 is_mock=false。没有新的展示模型、报告调用或自动修复节点。

| 场景 | 请求与实际状态 | 独立 Pandas / Engine 一致结果 |
| --- | --- | --- |
| 销售订单 | 2026、华东、已完成，城市销售额降序前三；实际点击确认，完成后刷新恢复 | 南京 300，济南 200，上海 100 |
| 招聘信息（首次） | “只看2026年发布”未被有限语法识别；页面明确阻断，按钮禁用，无批准/执行 | 不计算、不补造结果 |
| 招聘信息（重新提出） | 明确“发布日期为2026年”，在招、城市招聘人数合计降序前三；新会话重新规划后真实批准 | 北京 5，上海 3，杭州 2 |
| 客服工单 | 创建日期2026、已解决，城市响应分钟均值、升序前三；真实批准 | 上海 10，杭州 20，北京 30 |
| 项目任务 | 开始日期2026、已完成，城市工时合计降序前三；真实批准 | 北京 30，杭州 20，上海 10 |

独立 Pandas 从原 CSV 过滤和汇总，不调用 Engine 内核。四个真实计算结果逐行一致：见 [对照记录](pandas-verification.json)。可在项目根目录执行 `.venv/bin/python docs/evaluations/hitl-v2/verify_saved_results.py` 复核，不会调用模型或修改批准。

### 原始记录

- 销售：[保存方案/证明/批准/完整结果](sales-browser.json)、[审核 DOM](sales-review-dom.txt)、[刷新后结果 DOM](sales-completed-dom.txt)。
- 招聘未映射：[完整阻断状态](jobs-blocked-browser.json)、[页面 DOM](jobs-blocked-dom.txt)。未通过的方案未被删除，也未被自动改写。
- 招聘明确字段：[真实方案与执行](jobs-browser.json)、[审核 DOM](jobs-review-dom.txt)、[结果 DOM](jobs-completed-dom.txt)。
- 客服：[真实方案与执行](tickets-browser.json)、[审核 DOM](tickets-review-dom.txt)、[结果 DOM](tickets-completed-dom.txt)。
- 项目 v1：[真实方案与执行](projects-browser.json)、[审核 DOM](projects-review-dom.txt)、[结果 DOM](projects-completed-dom.txt)。

### 删除、版本、刷新、重启和技术详情

四类主问题均由真实模型生成单个核心任务，没有为测试而伪造辅助任务。项目 v1 完成后，在独立测试会话中有意删除唯一核心方向，验证 v2 变为空方案、原批准指针清空、原目标保留、按钮禁用。页面刷新及后端重启后仍为 v2/不可批准，v1 执行结果仍可读。普通文字说明“分析方向已全部移除，当前方案不能开始”，没有用成功的历史结果伪装当前 v2 已执行。

对应 [删除后状态与不可变版本](projects-after-delete.json)、[刷新 DOM](projects-after-delete-dom.txt)、[截图](projects-after-delete.jpg)。技术详情中实际加载版本、审批与 constraint_audits，见 [技术详情 DOM](projects-technical-dom.txt)。

非必要任务的删除→重新审计→新版本可批准、旧版本请求失效，另由真实 API 集成测试确定性覆盖；前端保留原删除回调并传递准确任务 ID。**浏览器删除案例是有意删除核心任务的阻断验证，不把它声称为辅助任务删除。**

完整过程核验见 [browser-verification.json](browser-verification.json)。测试服务保留在原本地验收数据目录 var/workflow-v1-e2e，没有覆盖默认用户数据目录。

## 自动化测试

- 后端 **562 passed**：原 527 + 新 35 个实例，含四领域、错误年份/地区/状态/指标/维度/排序/Top N、额外筛选/分组、提前截取、聚合后过滤、多次汇总、辅助方向漏筛选、跨任务拼凑证明、未知/否定/注入语言、排除、禁止、F0/F1、defer、删除、版本、伪造、不可变表、权限、相同样本歧义与重复列名。
- 前端 **40 passed**：原 30 项覆盖适配新业务标签与服务端资格，新增 10 项验证加载前/失败禁用、重试、四种身份或版本错配、服务端拒绝不能自推允许、技术详情折叠、真实重新提出需求入口、删除后旧响应不覆盖新版本。
- TypeScript / Vite 构建成功。既有 Starlette/httpx 弃用警告 1 条保留，没有新增测试失败。

测试命令、结果见 [test-results.json](test-results.json)。离线 API 测试使用人工结构化计划和显式受控测试 Provider，不能算成真实模型质量；真实模型证据仅为上述 10 次记录。四个离线映射样例：[销售](sales-mapping.json)、[招聘](jobs-mapping.json)、[客服](tickets-mapping.json)、[项目](projects-mapping.json)。

## Bad Case 与剩余限制

1. 保留真实 Bad Case：“只看2026年发布”无法被有限语法完整映射。虽有唯一发布日期列，仍未猜测自然语言缩略；通过新入口明确原始字段后才通过。没有为该模型返回临时放宽审计。
2. 开发时发现“按照”被正则短前缀“按”提前匹配的问题，已调整为最长前缀并加入 3 条固定复合约束回归；修复前没有批准记录，不把错误吞掉。
3. 复杂时间/相对日期、中文大数字、数值区间、多指标排序歧义、语义等价改写和复杂禁止行为仍可能阻断。这里只支持原始字段和已实现步骤，不提供任意自然语言约束证明。
4. 每个实际执行方向均需完整符合已识别约束，某些合理辅助方向会被保守阻断，需要删除或重新提出需求；不自动削减或偷偷改写方案。
5. defer 仍没有解决工具；不能通过勾选解除。没有自然语言方案修改、报告生成或新图表承诺。
6. 显示的业务问题及删除理由仍来自原 Planner，映射层不声称完成新的语义质量验证。截图与自动检查不等同于已完成普通业务人员的正式可用性研究。
7. 沿用本地单进程、SQLite、会话凭证与检查点机制；没有扩展多用户或复杂基础设施。
