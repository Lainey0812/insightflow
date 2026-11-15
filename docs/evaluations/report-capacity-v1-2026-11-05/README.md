# REQ-0094 报告容量修复与真实恢复验证

2026-11-05。本轮完成审批前容量估算、按指标组分批生成、全局核心覆盖校验，以及用户既有失败报告的恢复。没有减少核心指标，没有重新执行用户的Engine分析，没有增加Agent或汇总模型。

## 真实用户案例已恢复

- workflow_id：`wf_133270fa002f4008b54baca9ba347a14`
- root_run_id：见 `live-recovery-evidence.json`
- execution_id：`exec_f86303595be2401d9b7541f9fbe0c8af`
- report_id：`report_f66380c68d99402d8a4363dd24bcc4f6`
- 原报告attempt 1：failed / REPORT_CORE_SCOPE_TOO_LARGE。
- 新attempt 2：completed；报告report_status=complete、goal_coverage=complete。
- 原方案4任务、9核心指标、11总指标；实际2次模型调用，各批8条与3条合法候选，0拒绝，合并11条洞察，9/9核心指标覆盖。

通过前端已有“重新生成报告”按钮触发原有Report API，原审批快照、PlanVersion、Execution及执行次数与恢复前SQLite一致性备份逐项相同。未上传新文件、未重新批准或运行Engine。C19持久化receipt绑定同Workflow/Execution，report_persistence真实Span完成后才标记交付。

独立从本地已存上传文件读取60条数据，验证内容SHA后用Pandas参考链核对4项任务，结果均一致。这个核验没有调用Engine，没有生成额外执行Span或修改计算结果。详见 `live-calculation-check.json`。

浏览器已实际打开报告，最终后端重启后刷新仍可读取。截图 `recovered-report.png`。用户原始模型请求留在本地受控Registry，仅保存ID、状态、覆盖和哈希验证到本目录，不复制完整用户数据或会话凭证。

## 实际实现边界

每次模型调用最多8指标组、80候选证据、160KiB输入；整份报告最多64指标组和8次顺序调用。原4MiB执行结果输入保护保留。预算为明确工程保护，不是任意数据量或模型质量保证。

HITL预检显示核心/总指标数、预计调用批次和元数据估算；已知超出总容量时服务端审批拒绝，前端按钮服从can_approve。执行后真实证据大小仍需核验，界面没有承诺估算必然等于实际批次或报告必然成功。

分批以task/result/metric为不可拆单位，保持指标的比较、分母及范围证据在同批；全量指标先枚举，再选择有限候选，不能通过全局80条截断漏算核心组。只调用原Insight Generator，沿用V2选择Schema，不做跨批LLM汇总或新算术。

合并后按批准计划的全部P0聚合别名检查覆盖，而不只检查已有Evidence。这也修复了一个空数据边界：部分指标因空筛选返回null时，不能因为它未产生Evidence就当作已完成。该情况明确partial并列出未覆盖指标。没有合法洞察则失败，无证据继续原unavailable并跳过LLM。

部分批次失败保留合法批次、原图表与完整计算结果，公开partial、失败原因及未覆盖指标。已保存的partial报告仍沿用既有completed生成状态；本轮没有新增“只重试某一批”的断点恢复操作。

实际批次各有真实insight_generator/fact_validator Node Span与HTTP调用，全部直接归属原Root；batch_index明确表示批次，LLMCallRecord retry_index=0，没有创建第三层或独立Attempt。Report Run仍保存历史生成尝试。不可变llm_output快照每Run只写一次聚合投影，完整原始调用由Registry分别保存。

## 自动化验证

|项目|结果|
|---|---|
|最终完整后端|1585 passed，约82.81秒|
|新增后端专项|17项，包括参数化场景|
|Frontend|70 passed，构建通过|
|Admin|88 passed，类型检查与构建通过|
|警告|既有Starlette/httpx弃用警告；无新增失败|

覆盖9/17指标、单任务跨批、全量核心保留、唯一洞察ID、部分/全部批次失败、Schema合法但缺核心、跨批引用拒绝、65指标审批及调用前拒绝、字节预算、仅P1成功时核心blocked、Trace/Registry真实请求关联、唯一脱敏快照、不可重试容量错误，以及空筛选null核心指标。

旧报告Schema和历史载荷保持，原审批、Engine、Root CAS、Report stale callback及C19测试在完整回归内。没有数据库迁移或业务状态权威切换。

## 真实模型验证，分开统计

1. 固定合成9指标：真实qwen3.8-flash，两次HTTP，报告complete，9/9核心覆盖，与独立Pandas一致。明确标记为imported确定性内核结果，不伪造HITL/Workflow关联。原始请求和返回见 `fixed-nine-real01`。
2. 最终覆盖校验代码确认：`fixed-nine-real-final`，同一9指标两次真实调用，complete，Pandas一致。组合版本composition-v0.6-report-capacity-v1。
3. 冻结真实API主流程S01/S03：分别3次HTTP，两例均complete，独立目标及操作链计算通过。原始文件在 `../mvp-product-v1-2026-11-04/runs/capacity01/`。探索计划由真实模型生成，本次恰好落在单次容量，不能拿它代替固定9指标或用户真实2批证明。
4. 用户恢复：2次真实HTTP，9/9核心覆盖，完整交付。原始实际请求受原Registry权限/保留策略保护，脱敏核验见 `live-recovery-evidence.json`。

上述为不同输入、不同验证层，不合并成一个质量百分比。模型和思考参数未更换，Prompt正文仍report-insights-v2.0；仅组合来源版本更新。没有通过重复运行挑选优例。

## 保留的工具失败与迭代

- 首个固定9指标真实调用已经生成完整报告，但评测器错误假定“两列各4个函数”，读取不存在的field_0003_min而失败。实际冻结输入是销售额6指标、成本2指标加行数。保留 `run-real-nine.py`、原模型输出与failure.json，以 `verify-real-nine.py` 只读纠正预期，没有覆盖原记录或重调模型掩盖失败。
- 真实恢复核验工具首次误用了payload表id字段，正确键为snapshot_id，改正后完成本地只读核验。未修改数据库。
- 最初分批实现后发现空指标可能从Evidence中消失，新增失败测试保留在日志；修复为按批准计划全量核对。初版源码另存initial-batching-source.zip，组合版本从0.5更新至0.6，用户已恢复的旧报告内容未重写。

## 备份与剩余限制

恢复前使用SQLite backup API分别备份业务、Trace和Registry，完整性检查ok；目录在本地 `var/backups/report-capacity-v1-before-recovery-2026-11-05`（本次实际data_dir位于项目上一级var）。没有复制活动WAL主文件冒充一致性备份，备份文件权限0600、目录0700。

容量预检不能提前知道全部运行时证据体积；报告仍可能因真实预算或模型失败而partial/失败。超出硬预算的失败不提供无意义重试。没有批次持久化断点Resume、额外模型总结或全系统Workflow Switch。

长小数、标题技术感、建议重复及业务深度问题仍可见，本轮没有借容量修复重做报告UI或宣称整体验收通过。
