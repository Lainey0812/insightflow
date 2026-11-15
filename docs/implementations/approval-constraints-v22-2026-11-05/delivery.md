# REQ-0093 审批映射修复交付

2026-11-05。已完成本次四类误阻断修复，停止本阶段工作；未启动报告可读性或Admin改版。

## 文件变更

- `backend/app/review/constraint_audit.py`：完整动词/前缀映射、唯一聚合排序、报告边界proof、审计版本2.2。
- `backend/app/review/bindings.py`：已明确实体上下文的上传记录计数和计算维度识别，仍拒绝真实数量列冲突。
- `backend/app/review/output_boundaries.py`（新增）：有限禁止性表达、受控报告能力及利润引用缺席校验。审批与报告运行时共用规则，未知表达不放行。
- `backend/app/review/presentation.py`：区分步骤proof和报告边界proof；明确逐行计数口径。
- `backend/app/domain/review_presentation.py`：兼容读取审计2.0/2.1/2.2，无数据库Schema变化。
- `backend/app/services/analysis_report.py`：兑现已批准报告表达边界，独立导入入口也核验利润引用；受控标题与建议范围，不改计算成功标准。
- `backend/app/llm/templates.py`：新组合版本composition-v0.4-approval-audit-v2.2，保留实际来源变更；三个Prompt正文和模型参数未修改。
- `backend/tests/test_approval_constraints_v22.py`（新增）：27项保存案例重放、反例、能力版本和独立报告入口测试。
- `backend/tests/test_reliability_constraint_bindings.py`：当前审计版本与已支持边界预期更新，保留历史保存输入。
- `backend/tests/test_prompt_registry.py`：严格限定新增行数口径提示的请求上下文差异；其余历史实际请求继续逐项核对，冻结原件不变。

未修改Frontend/Admin源文件、PlanReview审批事务/版本/幂等、Engine、Planner、状态机、数据库或Workflow归属机制。

## 验证

- 最终完整后端：1568 passed；Frontend：67 passed；Admin：88 passed；两端构建通过。
- 原4个真实保存计划只读重放4/4通过，原Intent未改写。
- 首次真实32例：93/93 HTTP正常；30个非预期阻断请求中29个可审批。P02错误字面值仍正确拒绝。
- 首次32例：29次Engine执行、34项任务与独立Pandas一致；22完整报告、6部分报告、1报告容量失败、2预期能力阻断、1审批正确拒绝。
- 新表达X组4/4完整交付；使用已见CSV，只称新表达验证。
- 最终代码专项：原T04/U02/W03/W04另行真实确认，12/12 HTTP正常，4/4审批、执行、报告complete。保留首次32例不覆盖、不挑优合并。
- 错误字段/范围/方向、非空/去重计数冒充行数、多个排序指标、未知边界、利润别名或能力、旧报告生成器均保持拒绝。旧版本/Root CAS/Report stale callback回归保持。

## 资料与可用方式

评测、逐例结果、完整Bad Case与最终业务关联见 `docs/evaluations/approval-constraints-v22-2026-11-05/README.md`。需求原文REQ-0093保留。before.zip与after.zip、来源diff、首次32例源码v0.3及全部测试日志另存；没有覆盖旧版需求、Prompt、Gold或失败记录。

后端需完整重启加载新组合代码。待审批会话刷新后会重新核验；历史报告不自动改写。未知约束仍需明确表达，不能勾选解除。不可把代码回滚到不执行新报告边界的自由文本版本；历史审计旧版本只读兼容，不代表旧写入逻辑可安全接管新审批。

本次交付只说明针对性审批修复完成，不宣称任意自然语言可执行或整体验收通过。报告候选重复/类型、探索容量、长小数、排序叙述和真实目标用户试用仍待后续工作。
