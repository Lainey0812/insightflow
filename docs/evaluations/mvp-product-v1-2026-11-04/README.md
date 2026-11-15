# InsightFlow MVP 产品验收 V1：冻结与真实基线

需求：REQ-0089。日期：2026-11-04。结论：**本轮验收准备与真实基线执行完成；产品业务验收未通过，不建议扩大用户试用。**

## 本轮完成的工作

1. 先归档用户授权，并保存修改前的产品源码基线。
2. 冻结四份明确标注的合成 CSV、16 个真实模型场景（12 core + 4 holdout）、4 个故障场景、评分规则与用户试用协议，建立内容哈希清单。
3. 通过现有业务 API 完成真实上传、意图识别、规划、校验、澄清、审批、执行和报告路径；没有调用 Mock 代替模型。
4. 每例使用独立数据库；保存实际请求、原始模型输出、计划、审批展示、执行结果、独立基准、报告、Presentation、Trace 和 LLMCallRecord。
5. 完成 A–G 分层执行者审阅、失败归因和修复优先级。真实目标用户试用仍待开展，没有伪造用户复核。

本轮只新增验收脚本、5 个验收工具安全测试和交付资料。`backend/app`、`frontend/src`、`admin/src` 均与基线哈希一致，见 protected-source-check.json。未在中途调 Prompt、放宽审批或改变报告事实规则，也没有为了跑通链路删除任务。HITL 自然语言修订尚未开发。

## 冻结与复现

[frozen/manifest.json](frozen/manifest.json) 保存八个冻结输入文件的哈希；评分规则见 [rubric.md](frozen/rubric.md)。CSV 为合成测试资料，与已有真实业务上传文件及历史数据库隔离。固定销售样本共 10 条，符合指定范围 6 条，不是此前 60 条销售样本的复制或重新统计。

模型沿用 qwen3.8-flash；各阶段超时 60 秒；Intent/Planner 最大尝试数均为 2；三个节点 enable_thinking 均为 false；没有显式添加 temperature 等新参数。配置来源为本地既有 `.env`，密钥未输出、未归档。实际 HTTP payload、动态 Schema、模板快照及调用关联保存在每例记录中。Prompt 版本保持 intent-v1.3.3 / planner-v1.2 / report-insights-v1.1.9，未改动。

执行入口：`backend/scripts/run_mvp_acceptance.py`。示例在项目根目录：

```sh
.venv/bin/python backend/scripts/run_mvp_acceptance.py --case S01 --run baseline02
```

必须使用新的 run 名称。脚本独占创建输出，禁止覆盖旧运行。新运行会真实调用配置模型，结果可能不同，不应冒充基线重复读取。运行库在 `var/verification/mvp-product-v1-2026-11-04/<run>/<case>/`。脚本在导入应用前指定隔离目录，不对当前用户会话运行恢复逻辑。

## 实际结果与分母

| 指标 | 本次结果 | 含义 |
| --- | --- | --- |
| 真实模型场景 | 16 | 12 core，4 holdout |
| HTTP 模型调用 | 39/39 正常返回 | Intent 18，Planner 16，Insight 5；不是产品成功率 |
| 明确目标计划核验 | 12/12 | 筛选集合、字段、函数、维度、排序及 Top N 对照本例独立基准；不是通用约束召回率 |
| 开放探索计划 | 2/2 由执行者审阅相关性 | 不代表报告交付成功 |
| 预期能力阻断 | 2/2 正确 | 缺利润、文本薪资区间均值；计为正确阻断，不能计作报告交付 |
| 应交付报告场景 | 14 | 含澄清后继续的两例 |
| 审批阻断 | 9/14 | 计划正确，但约束证明能力不够 |
| 实际 Engine 执行 | 5/5 success | 共 10 个任务的持久化结果与独立 Pandas 参考一致 |
| 报告交付 | 2/14 | 两份均为 partial；完整报告 0/14 |
| 已执行后的报告失败 | 3/5 | 核心覆盖遗漏、引用不合法或自由文本数值被拦截 |
| 未批准执行保护 | 14/14 拒绝 | 使用业务 API 验证，没有先执行后补批准 |
| 执行幂等 | 5/5 | 重放请求返回同一 execution_id |
| 正确触发澄清 | 2/2 | 两例恢复出计划，但均在后续审批阻断，不能算完整恢复成功 |

执行者逐例审阅后的状态：complete 2、partial 2、failed 12、unavailable 0。两个 complete 均为预期阻断场景，不能解释成两份完整分析报告。

core：complete 1 / partial 2 / failed 9。holdout：complete 1 / partial 0 / failed 3。原始 runner 的两个 pending_review 记录保留不动；agent-case-review.json 单独记录对正确阻断的审阅结论。

本轮没有模型超时。实测单次调用中位数 / 最大值：Intent 3.315 / 5.124 秒；Planner 6.083 / 20.020 秒；Insight 7.573 / 8.304 秒。这是小样本观测，不是延迟 SLA。

## 逐例业务结果

| 案例 | 分组 | 用户需求 | 审阅状态 | 发现 |
| --- | --- | --- | --- | --- |
| P01 | core | 统计2026年每个月创建的任务数量，按月份升序。 | failed | 2026年筛选、月份派生、月计数与升序链正确，任务数量和月份排序的约束证明不足，审批阻断。 |
| P02 | core | 只统计已完成任务，按项目汇总工时总和，不包含丙项目。 | failed | 完成状态、排除丙及按项目工时合计计划正确；“只统计已完成任务”“不包含丙项目”无法映射，审批阻断。 |
| P03 | core | 探索这份项目任务数据的主要分布与差异。 | failed | 项目、状态、工时三个探索任务相关且计算正确。三个候选均未将 primary_evidence_id 放入 evidence_refs，事实校验正确拒绝，无报告。 |
| P04 | holdout | 计算平均工时，不要求计算工时中位数。 | failed | “不要求中位数”未升级为禁令或强制目标，只计算平均工时。LLM 在自由局限文本写入真实但未绑定证据的缺失数1，触发 NUMERIC 拒绝，无报告。 |
| R01 | core | 统计各城市岗位数量，按数量降序排名。 | failed | 各城市计数与降序计划正确，约束审计不识别“岗位数量”和相关排序表达，阻断审批。 |
| R02 | core | 计算薪资区间的平均值，不使用薪资元字段替代，也不要自行解析区间。 | complete | 文本区间均值不可执行且禁止替代/解析，P0/F0 与缺失能力被明确保留，无执行；正确停止。 |
| R03 | core | 帮我处理一下。 | failed | 初始模糊请求正确澄清，补充后形成正确城市计数计划；后续仍被岗位数量审计阻断，不能称澄清闭环完成。 |
| R04 | holdout | 统计各城市岗位数量，不排除北京，按数量降序排列。 | failed | “不排除北京”未被反转，计划保留全部城市，但岗位数量和范围边界审计不支持，阻断审批。 |
| S01 | core | 帮我分析2026年华东地区已完成订单的销售额，按照城市汇总并降序排名，取前三名。 | partial | 明确目标、范围、合计与排名均正确。上海比较候选中的待验证原因表达被 UNSUPPORTED_ASSERTION 拦截；两条合法发现保存，Top3 分母限定清楚，仍是 partial。 |
| S02 | core | 只统计各城市订单数量，不分析销售额。 | failed | 订单计数与禁止销售额在计划中得到遵守，但审批无法识别“订单数量”“不分析销售额”，用户不能继续。 |
| S03 | core | 帮我探索这份销售数据的主要特征和差异。 | failed | 四项探索方向总体相关且计算一致；LLM 仅选择产品类别和时间趋势证据，没有覆盖两个 P0 方向，Report 正确拒绝完整交付。 |
| S04 | holdout | 按城市比较利润总额。 | complete | 利润字段缺失，P0/F0 保留且覆盖 blocked，无虚构利润计算；正确停止，不计入报告交付成功。 |
| T01 | core | 按团队比较平均响应分钟。 | partial | 团队均值计算正确，保留一条合法比较；否定因果边界的候选被误拦截。KPI 对较高响应时间使用“领先幅度”，有业务方向误导风险。 |
| T02 | core | 只看已解决工单，按优先级统计工单数量，降序取前两名。 | failed | 已解决筛选、优先级计数及降序Top2计划正确；工单数量和复合排序限制无法核验，审批阻断。 |
| T03 | core | 比较指定团队的平均响应分钟。 | failed | 缺失团队正确澄清，补充一组/二组后计划正确；枚举范围表达未被审计支持，阻断审批。 |
| T04 | holdout | 比较各团队已解决工单数量，不要分析利润，也不要推断团队差异的原因。 | failed | 禁止利润与推断原因均保留，没有增加违禁任务；审批对业务计数和边界表达不支持，阻断。 |

## 代表性真实记录

销售 S01：Workflow `wf_ee0a8b01ec634b718a1b2d5363bd59c6`，Execution `exec_eaf846e13e46475b888fc789984873c6`，Report `report_5ac6ab143ec841548e189b2bbc27328b`。

独立基准与执行结果均为济南 21,250、南京 20,250、上海 5,760；前三名合计 47,260。报告保存 4.9% 与返回 Top3 内 87.8% 的确定性证据，未当作全华东占比。报告仍因一条候选被拒绝而为 partial。参考该例 goal-oracle.json、execution-complete.json、analysis-report.json、presentation.json、workflow-trace.json 和 http-03-response.json。

客服 T01：团队均值二组 40、一组约 18.333、三组 5；有效响应记录 7/8。计算一致，但报告只保留一条比较，且 KPI 对较高响应时长使用“领先”，存在方向性误读风险。详见 bad-cases.md。

## A–G 质量审阅

原始候选、保存报告和 Presentation 分开评分，不混成一个平均分。范围覆盖本轮实际产生 Insight 调用的五例；其他没有调用/交付的场景不编造报告评分。详见 [quality-scores.json](quality-scores.json)。0/1/2 规则先冻结，未存在的层记 null。

| 案例 | 层 | A | B | C | D | E | F | G |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | 原始候选 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| S01 | 保存报告 | 2 | 2 | 2 | 2 | 2 | 1 | 2 |
| S01 | Presentation | 2 | 2 | 2 | 2 | 2 | 1 | 2 |
| S03 | 原始候选 | 2 | 0 | 2 | 0 | 2 | 1 | 2 |
| S03 | 报告/Presentation | null | null | null | null | null | null | null |
| T01 | 原始候选 | 2 | 2 | 2 | 2 | 2 | 1 | 1 |
| T01 | 保存报告 | 2 | 1 | 2 | 2 | 2 | 1 | 1 |
| T01 | Presentation | 2 | 1 | 2 | 2 | 2 | 1 | 1 |
| P03 | 原始候选 | 0 | 1 | 2 | 1 | 2 | 1 | 1 |
| P03 | 报告/Presentation | null | null | null | null | null | null | null |
| P04 | 原始候选 | 1 | 1 | 1 | 2 | 2 | 1 | 1 |
| P04 | 报告/Presentation | null | null | null | null | null | null | null |

S01 的主要数值与范围正确，但重复口径/防御性技术表述影响普通用户阅读。T01 的 G=1 表示方向性与无阈值强度措辞尚不能充分验证，不是宣称已通过完整安全语义验收。P03 的 A=0 为引用绑定不合法，系统正确拒绝，没有进入用户报告。

这些评分由当前执行者审阅实际输出，不是独立用户研究结果，更不能证明专业分析师水平。

## 自动化检查

- 四个冻结故障场景映射到五项实际参数化测试，全部通过。涵盖 Engine partial、Report 失败/重试、重启读取、Trace 禁用与写入故障。它们是受控测试，不计入 39 次真实模型调用。
- 新增 5 项验收 oracle 安全测试全部通过：冻结完整性、正确基准、数值碰巧一致却范围错误、错误指标函数、缺 Top N。独立 oracle 未导入 Engine 操作内核。
- Backend 全量：1473 passed，1 项既有 Starlette/httpx 弃用警告。
- Frontend：67 passed，构建通过。
- Admin：首次并行回归 87 passed / 1 failed；原有 Inspector effect 的异步断言竞态。保留失败日志；未改代码，独立重跑 88 passed，构建通过。该偶发问题仍未修复，不宣称所有检查首次全绿。

## 修改和资料清单

新增代码：backend/scripts/run_mvp_acceptance.py、backend/tests/test_mvp_acceptance_oracle.py。没有修改产品运行源码。源码和冻结文件哈希见 source-baseline.json、protected-source-check.json、frozen/manifest.json；交付工具快照见 acceptance-tools.zip。

重要资料：summary.json、agent-case-review.json、quality-scores.json、bad-cases.md、frozen/user-trial-protocol.md、runs/baseline01 下每例原始记录及各测试日志。运行时业务库、Trace DB 和 Registry 保存在独立 var/verification 目录，不将密钥或原始 .env 复制进档案。

## 下一步与准入

根据实际结果，修复顺序明确：先解决真实自然表达与可执行条件之间的约束证明缺口，再修复报告覆盖/引用/边界表达导致的交付失败，同时处理无方向指标的“领先”文案。不能靠改 Gold、换样本、关闭校验或降低核心覆盖要求提高分数。

之后使用同一冻结集做回归，并新增独立表达样本。基础闭环稳定后再做 HITL 自然语言修订；最后按已准备协议招募 3–5 位真实用户。当前没有用户招募与反馈，不能宣称普通业务人员已可独立完成。

本次完成第一阶段基线，不把修复和用户试用混入同一个“通过”结论。
