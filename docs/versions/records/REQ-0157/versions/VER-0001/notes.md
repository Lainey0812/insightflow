# Bad Case归因与修复回流 V1

2026-11-16。REQ-0157，关联REQ-0155。

## 交付行为

列表保留真实BadCase表格、筛选、分页与详情入口，增加当前归因与行内编辑。详情使用同一归因表单，显示实际观察、期望、冻结证据、节点、模型引用和处理历史。归因需人工选择原因、Prompt节点、说明和操作者；未提交选择不改变状态。

新增持久状态in_progress（处理中）与pending_verification（待验证），open展示改为待处理。保留confirmed/fixed/wont_fix/invalid原值与历史，不批量改写旧记录。提交归因追加attribution_submitted事件并进入处理中；重新归因保留旧事件，待验证重新归因也进入处理中。已关闭问题需要先通过既有操作重新打开。

Prompt原因显示“立即修复”，同标签导航到 `/prompts?node=...&tab=edit&bad_case=...`。顶部修复来源卡片显示真实BadCase标题/ID，并验证归因与当前节点。错误节点、无效状态或读取失败不能确认提交。其他原因提供现有Workflow诊断入口；不伪造尚未实现的代码/数据编辑器。未明确原因时没有可执行的自动修复入口。

编辑页底部“确认修复并返回待验证”要求实际Prompt修改与操作者。先保存不可变System草稿，再提交修复引用；只有后端成功响应才导航返回原详情。进入待验证、保存草稿引用、显示“未发布/尚未验证”提示。旧Prompt继续保留，不触发生产模型调用、Workflow、审批、Engine或报告执行。这里“关闭Prompt页面”是同标签路由退出编辑页，不使用新窗口或跨标签关闭。

## 接口、状态与一致性

- POST /admin/bad-cases/{case_id}/attribution：归因提交。
- POST /admin/bad-cases/{case_id}/repair-draft：核对状态/节点/版本序号后保存有变化的草稿。
- POST /admin/bad-cases/{case_id}/repair-completion：核对处理中、Prompt归因、精确节点、草稿来源、哈希、冻结证据及expected_sequence，追加repair_submitted事件进入待验证。
- 原get/list添加可选attribution/repair投影。旧事件、原始问题描述和冻结证据不更新。所有写入仍沿用Admin与标注凭证，本机测试模式继续沿用loopback保护，凭证不进URL或浏览器存储。

不新增数据库Schema；已有append-only BadCase事件JSON携带新元数据、序号CAS原子提交。服务在依据状态作决策前核对读取序号，仓库再次在BEGIN IMMEDIATE事务内检查，以防并发/旧页覆盖。重复提交旧序号拒绝。错误目标节点、原样Prompt、非调试草稿均拒绝。

Registry草稿保存复用现有PromptWorkbench逻辑并抽取save_draft方法，内容哈希、版本算法与原调试保持一致。不发布，不增加Agent或Trace层级。跨Registry与BadCase不是原子事务：先保存草稿、后提交事件；若第二步失败，可能留有孤立草稿，但问题保持处理中，页面保留编辑与错误，可重试。相同草稿登记幂等，不伪造成功或自动跳回。

既有手动状态接口不能直接切入两个新状态；新状态内追加备注仍允许。回放工具REPLAYABLE集合增加新状态，以便后续验证，而不是在本轮自动启动回放。旧前端不认识新枚举，需要刷新载入新代码；未宣称旧二进制可无感读新状态。

## 真实浏览器验收

创建明确标记为合成验收的记录 bc_a0023163906248489a22317123811a7c，关联既有真实Workflow，仅测试后台操作，不认定该Workflow实际有错。

1. 列表选择Prompt归因、Intent节点、说明和操作者；确认后服务端状态in_progress，sequence2。
2. 进入详情再次修改说明并确认，sequence3。
3. 点击立即修复，顶部显示对应BadCase标题与ID；编辑当前System添加明确的合成验收附注。
4. 底部确认，保存草稿 pt_8ced957b897dd6b4ce0d464eba53f31fd8a5ee7d2a621068d1eb8a330402f9fb；自动返回原详情，pending_verification，sequence4。
5. 刷新仍为待验证。四条追加事件依次为创建、列表归因、详情归因、修复提交；冻结证据哈希不变、evidence_intact=true。无LLM调用，无线上发布。

证据见real-case-created.json、real-roundtrip.json和四张截图。合成记录与草稿保留，不删除历史。实际关联Workflow的业务执行结果未修改。

## 测试

- 后端相关19例通过，覆盖新闭环、权限、序号冲突、归因更改、错误节点、原样内容、持久读取和既有回放。
- 前端相关28例通过，包含新增4例列表/详情/修复回流/冲突留页验证；TypeScript与构建通过。大于500KB构建块警告继续保留。
- 后端全量：1766通过、1个既有diagnosis隐私测试失败（与REQ0155修改前副本同样复现的test_success_has_no_failure_and_records_inputs_without_user_text）。
- Admin全量最后一轮：266通过、10个既有Trace/Comparison路由测试失败，与REQ0155保存的修改前基线一致，未顺带修改Trace。
- 中间一次完整UI测试发现新用例未等待归因加载完成，已修正为等待真实文本，最后相关28例通过；失败日志保留。另两次命令分别因错误工作目录和不存在的test_replay.py文件未实际执行，随后使用正确目录和test_bad_case_replay.py重跑，不将失败命令当成通过。

本轮未更改用户端功能，不冒称重跑Frontend全量。完整回归仍非全绿；新增功能通过专项、全量中相关项和真实浏览器闭环验证。

## 修改与限制

文件清单见changed-files.txt，前后快照before.zip/after.zip。没有自动验证成功、没有自动发布、没有在线修改固定User Python组装逻辑。本轮只打通Prompt修复流；其他归因仍须按真实诊断处理，不提供无效的自动修复按钮。后续可将真实回放结果绑定修复草稿，在明确验证后人工改为已修复；本轮待验证不会自动变已修复。
