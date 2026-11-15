# Admin 全链路监测与问题定位审计

日期：2026-11-09（Asia/Shanghai）。需求：REQ-0107。

本轮为只读审计、现有页面验证和测试，不修改业务代码、Prompt、模型参数、数据库Schema或历史业务记录。用户“好”确认的是先用当前真实报告检查已有覆盖并列出缺口。未自动进入在线Prompt编辑开发。

## 1. 真实样本与结论

- report_id：report_6e2438b23e874520b39f24a0e4660896
- workflow_id：wf_c3781c6be06a4fbfa1428e36813a35e8
- session_id：93c7625ad37748b6bbc6a820bbf63228
- root_run_id：run_522e438781b54fc4ab53bd7fe32b3d78
- plan_version：2；plan_version_id：wpv_15bbe473c4adb215839c390c2dbac4490b7227f75cef23e3c96cb8acccc0e971
- approval_id：approval_512e3bbd8821448c828e1d8f6b1cebdb
- execution_id：exec_4eaf5344f4934ee1aa36fa0310fc5484
- ReportGeneration attempt：1，completed；已提交Report：complete / goal_coverage complete。
- 业务聚合API：succeeded、execution success、report delivered、consistency consistent，未发现已知collection gap。
- 16个真实Span、44条Root事件、3条真实模型调用；所有新Span直接挂Root（parent_span_id=null），未生成占位节点。
- 总耗时1657.98秒，明确包含人工等待；Span耗时简单相加25.14秒，部分Span重叠，不能解释为独占机器耗时。最长计算节点为Planner17.16秒。不能把27分钟墙钟时间说成模型超时。

证据：workflow-api.json（脱敏元数据API原响应）、prompt-links.json（实际调用模板关联）；未归档完整原始数据、API Key或完整请求。

## 2. 节点覆盖表

| 节点 | node_attempt | 实际状态 | 耗时ms | LLM调用数 |
|---|---:|---|---:|---:|
| data_profiler | 1 | complete | 19.82 | 0 |
| intent_parser | 1 | complete | 2701.70 | 1 |
| analysis_planner | 1 | complete | 17160.87 | 1 |
| plan_validator | 1 | complete | 4.20 | 0 |
| plan_validator | 2 | complete | 3.51 | 0 |
| hitl | 1 | complete | 25.46 | 0 |
| plan_validator | 3 | complete | 2.59 | 0 |
| hitl | 2 | complete | 21.53 | 0 |
| plan_validator | 4 | complete | 3.62 | 0 |
| analysis_engine | 1 | complete | 18.09 | 0 |
| evidence_builder | 1 | complete | 3.91 | 0 |
| chart_builder | 1 | complete | 1.62 | 0 |
| insight_generator | 1 | complete | 5154.64 | 1 |
| fact_validator | 1 | complete | 7.00 | 0 |
| report_assembler | 1 | complete | 2.13 | 0 |
| report_persistence | 1 | complete | 9.68 | 0 |

四次Plan Validator对应planner_output、initial_plan_save、hitl_revise、hitl_approve，属于不同真实校验位置，不能当作四次失败重试。HITL两次分别是范围修订和审批。三个LLM调用retry_index均为0，本样本没有真实LLM重试。

洞察节点传入29条证据，输入34026字节；产生3候选，事实校验接受3、拒绝0。候选证据引用存在于实际事件中。本样本无拒绝案例，不能据此宣称已经真实验证所有拒绝或超时场景。

## 3. 数据来源与页面核验

- 只读聚合API：GET /admin/workflow-observability/{workflow_id}；列表同前缀。`backend/app/api/admin.py:101`；业务聚合`backend/app/services/workflow_observability.py:14`。
- 业务关联读取：`backend/app/services/workflow_trace.py:12`起，按登记Workflow、审批、Execution和已提交报告校验，不按最新成功时间选报告。
- 页面：`admin/src/pages/WorkflowDetailPage.tsx:13`起，节点事件、重入和调用关联；`:42`时间线，`:43`报告尝试记录。
- 浏览器实际打开详情，核对16节点、3调用、审批/执行/报告ID与数据库一致。展开Planner查看17.16秒、2条真实事件，再点击调用记录，看到qwen3.8-flash和17.09秒Provider耗时。
- 点击“查看关联Prompt版本”，读取的是planner-v1.2+composition-v0.12-report-reference-format-v1历史快照，**不是当前composition-v0.13**。来源Commit正确显示unknown。模板登记包含System、固定组合、重试、能力、Schema和源码来源。
- 当前Admin此前未启动，首次浏览器连接失败；启动现有Vite开发服务后页面正常。另一次绑定错误页面被URL策略拒绝后重新打开正常localhost页面，没有绕过安全页。该启动问题与Trace采集或模型调用无关。

截图：workflow-overview.png、workflow.png、planner-call.png。页面已保持打开。

## 4. 真实缺口与优先级

| 优先级 | 发现与源码依据 | 影响 | 建议最小改造 |
|---|---|---|---|
| P0 | LLM返回只保存response_hash，`backend/app/llm/capture.py:55`；Trace快照只做脱敏投影，`backend/app/observability/snapshots.py:15` | 请求可追，但不能还原原始JSON或被拒候选文字；难判断模型错误还是后处理损失 | 为今后的真实HTTP返回增加受控响应快照，关联既有call_id；权限、保留期、摘要、哈希与明确写入失败语义；不重跑推测旧返回 |
| P0 | Workflow页节点展开以原始属性/事件JSON为主，`admin/src/pages/WorkflowDetailPage.tsx:13`；专门Inspector仅部分报表字段有解释，`admin/src/features/traces/NodeInspector.tsx:12` | 有证据但仍需开发人员阅读，无法快速区分数据、规划、审批、计算、事实拒绝、组装或持久化问题 | 用现有reason_code和事件构建通用节点诊断面板，展示真实输入输出引用、错误类别及规则，不自动判定错误归咎Prompt |
| P1 | Workflow页只有手动刷新，`admin/src/pages/WorkflowDetailPage.tsx:32`附近effect只依赖ID与refresh | 当前可历史追溯，尚不是自动更新的运行监控 | 对非终态只读轮询，取消过期请求，展示采集时间与读取失败；不推测未执行节点 |
| P1 | Root持久状态仍waiting_approval；`backend/app/services/workflow_trace.py:114`声明preparation_checkpoint；业务聚合已独立 | 原始Run Explorer易与全链路业务状态混淆 | 继续以Workflow业务卡片为主；突出Root观测范围，不能直接改Root终态或由Span反推业务成功 |
| P1 | PromptRegistry是只读快照查询；`backend/app/api/admin.py:202`后只有GET；`backend/app/llm/templates.py:110`运行时固定源码绑定 | 页面不能编辑、测试或发布新Prompt；改数据库模板也不会安全改变运行行为 | 另行设计草稿与显式启用契约，先复用不可变快照，再接固定测试和前后对比；不修改历史模板，不把保存草稿等同发布 |
| P2 | 问题归档/评测中心仍为禁用占位，`admin/src/app/navigation.ts:55`后 | 无法从Trace形成持续Bad Case复测闭环 | 先新增问题记录关联Workflow/Span/Call/规则/Prompt，后续再做小型评测管理；不开发统计Dashboard |

“collection observed”只说明当前检查器未发现已知采集缺口，不表示保存了全部原文或具备全部诊断能力。跨库查询仍是非原子快照，API明确标注；当前仍是Session单流程兼容权威，不宣称多Workflow切换完成。

## 5. 当前能力与未实现能力

已验证：真实Workflow查询、业务结果与Trace分离、实际节点耗时、节点展开事件、调用关联、实际历史Prompt及Diff入口。Trace写入fail-open与Registry请求捕获fail-closed是两个不同机制，不能混用故障语义（`backend/app/observability/recorder.py:178`、`backend/app/llm/capture.py:50`）。

未实现：自动运行中刷新、受控完整模型响应追溯、业务人员可理解的统一诊断、问题归档、Prompt在线草稿/测试/启用。GitCommit缺失仍unknown，不能回填为当前状态。本轮未读取额外受控原始请求、未发送新数据给模型。

## 6. 测试与局限

本轮执行相关后端测试62 passed（1个既有依赖弃用警告），Admin全量88 passed。日志附后。测试使用隔离临时数据，涵盖缺Trace、权限与Registry查询等；不冒充本样本真实发生过失败/重试。无生产代码变更，不重复宣称全量后端或Frontend本轮回归通过。

本轮只有一个真实成功样本，不能据此验收全部失败诊断或运行中轮询。下一阶段建议优先实现“调用响应受控追溯+统一节点诊断”，再补非终态刷新，最后开启Prompt草稿与评测；保持Root+Node Span两层，无独立Attempt实体，不改变分析成功标准。后续需要用真实失败、超时、部分成功和Trace故障样本分别验收。
