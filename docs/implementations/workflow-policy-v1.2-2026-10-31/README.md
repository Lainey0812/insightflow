# C19 定向修订交付 — Lifecycle Contract V1.2

日期：2026-10-31（Asia/Shanghai）；REQ-0081，修订REQ-0080中D01。  
范围：契约V1.2、独立Policy和专项/兼容测试。未接入生产写入或生产Recover，没有Backfill、Switch或新Workflow入口。

## 1. 修订结果

1. **C19-A：Report Commit Authorization**：提交前核对当前Workflow/Execution/attempt/generating/revision/活动key、证据与覆盖。allow仅允许尝试业务事务，不要求也不产生accepted。
2. **Business Transaction**：规范未来Writer原子保存Report、ReportGeneration、归属及提交元数据；Policy不执行事务。
3. **C19-B：Report Completion Observation**：只根据可信的已提交持久事实确认accepted=True，只授权对应report_persistence Span完成，不改变Root/业务状态。
4. **回执丢失恢复**：没有收到返回值不判失败；一致读Report、Generation、归属、提交元数据，相互匹配则仍accepted。查询失败/未查询为unknown，部分记录错位为inconsistent。

V1.2共有33个检查点：31行原样继承+C19-A/B。覆盖见[command-coverage.md](command-coverage.md)与[原始决策JSON](command-coverage.json)。旧V1.1冻结内容和C19冲突拒绝行为保留。

## 2. 契约与差异

- [Lifecycle Contract V1.2](../../designs/lifecycle-contract-v1.2-2026-10-31/README.md)
- [V1.1至V1.2定向变更](../../designs/lifecycle-contract-v1.2-2026-10-31/changes-v1.1-to-v1.2.md)
- [设计检查结果](../../designs/lifecycle-contract-v1.2-2026-10-31/design-verification.json)

原D01已由新V1.2明确解决，不修改旧差异报告来抹去当时阻断。31个非C19命令及全部继承状态表未变。旧native_v1.1继续使用旧入口；native_v1.2显式使用新入口。

## 3. 实际代码文件

| 文件 | 修改性质与原因 |
|---|---|
| `backend/app/domain/workflow_policy/report_commit.py` | 新增纯领域提交授权/提交元数据/归属/Span投影与reconcile_report_commit；不查询数据库 |
| `backend/app/domain/workflow_policy/catalogue_v12.py` | 新增33检查点映射，只替换原C19，固定V1.2契约哈希 |
| `backend/app/domain/workflow_policy/validator_v12.py` | 新增WorkflowPolicyValidatorV12、PolicySnapshotV12、A前置与B后置校验 |
| `backend/app/domain/workflow_policy/models.py` | 扩展内部投影report_id、native_v1.2适用域与span预期转换/observe动作；不改公开API模型 |
| `backend/app/domain/workflow_policy/validator.py` | 将既有31条逻辑参数化复用，新增默认无效的报告扩展点；旧C19仍拒绝 |
| `backend/app/domain/workflow_policy/__init__.py` | 导出独立V1.2入口 |
| `backend/tests/workflow_policy_v12_fixtures.py` | 新增合成A/B提交事实 |
| `backend/tests/test_workflow_policy_v12.py` | 新增31继承兼容、A/B合法/拒绝、持久证据交叉核验、只读幂等等测试 |
| `backend/tests/test_report_commit_recovery.py` | 新增临时SQLite协议及真实子进程退出测试，含调用内存完全丢失后从audit重建授权 |

旧Session、ReportWorkflow、ReportRepository、Engine、HITL、TraceRepository、Prompt与API文件没有修改。原专项测试文件保持原样。

## 4. 调用方式与输出

```python
from app.domain.workflow_policy import WorkflowPolicyValidatorV12

# 来自未来可信的业务读适配层；不是HTTP或模型自报数据。
policy = WorkflowPolicyValidatorV12()
authorization = policy.validate(precommit_snapshot, c19_a_command)
# action=execute只表示允许尝试事务。原子提交由未来Writer负责。

observation = policy.validate(postcommit_snapshot, c19_b_command)
# action=observe仅授权该Span完成；不运行业务事务、不改变Root。
```

[C19实际合成示例](c19-examples.json)记录：A allow、持久证据accepted、B observe、未读库unknown及Span已interrupted时的业务成功/观测拒绝。

可信accepted不是公开请求参数：PolicyCommand接受accepted=True额外字段会被拒绝。B内部调用reconcile_report_commit，要求可信读适配层提供事务一致的记录。纯领域代码不能认证调用者或自己查库，不能把客户端自称transactional的字典当作可信证据。

## 5. 原子提交与恢复边界

提交元数据精确绑定业务引用、report_id/digest、原请求/hash、授权revision/key、committed_revision及可选persistence_span_id。建议保存在既有报告audit；本轮未创建表或新Attempt实体。

B核对提交时key与Span，允许当前活动key在提交后清空，允许当前revision包含已提交revision。若Workflow已换新执行/attempt，拒绝污染当前观察。已complete的同Span只读replay；failed/interrupted等历史终态不重开。

Trace未采集时业务依然可以提交；没有目标Span只产生采集缺口。Report.partial的持久化Span可以complete，业务仍部分成功；没有把Span状态当作报告质量或目标覆盖。

测试中的SQLite协议有专用protocol_*表，只存在tmp_path，显式开启外键与WAL。它验证提交/回滚/持久查询时序，**不是生产Schema迁移或原生Workflow Writer实现**。测试还从实际存储的payload计算hash，避免信任投影中自称的摘要。

## 6. 实际专项与兼容验证

最终结果以[tests-summary.json](tests-summary.json)与相应日志为准。

| 验证 | 结果 |
|---|---|
| 旧Policy专项+C19新专项+恢复协议 | 544通过；旧446全部保持，新98 |
| 33个检查点允许样例 | 全部通过；A=execute，B=observe |
| 提交前/后崩溃 | after_report、after_generation退出整笔回滚；after_commit退出仍可核验accepted |
| 调用内存完全丢失 | 从execution_id查询持久generation/report.audit，重建授权和B请求，允许精确Span完成 |
| 原子提交已成功但Span interrupted | 业务accepted=True，Span不重开、不重算业务 |
| A合法但尚未提交 | B拒绝，不把A allow当作业务成功 |
| 伪造accepted/错Workflow/旧execution或attempt/key/revision | 拒绝 |
| 元数据/报告hash/归属/Generation冲突或缺失 | unknown/inconsistent，不误判成功 |
| 重复A/B | 原结果只读重放，无第二次事务/状态转换 |

日志保留：policy-tests-first.txt为521通过；policy-tests-r2.txt为539通过；policy-tests-final.txt保留1个用例期望错误（B仍带A的候选facts，先被额外写入输入守卫拒绝）；改为真正的纯观测请求后policy-tests-verified.txt为543通过；增加完全丢失内存恢复验证后policy-tests-release.txt为544通过。没有删除失败或放松校验。

本轮没有外部真实LLM请求，没有使用Mock冒充真实分析运行。全部为领域/协议与原工程自动化回归。

## 7. 交付判断与仍未上线内容

本次C19-A/B契约时序和独立Policy阻断已解决，可提交进入下一阶段的评审；不自动启动下一阶段。

仍未实施：原生Workflow Writer、生产原子归属写入、受控提交元数据持久适配、生产Recover读取协议、真实Span完成适配、Lifecycle Read Model V2、状态权威Switch与多Worker接管。

因此“专项通过/33检查点允许”不等于生产已经采用V1.2或全部恢复风险已消除。后续接入时必须再次验证事务锁内CAS/幂等、提交元数据真实性、持久读一致性及旧Worker隔离；不得直接接收客户端构造的内部投影。

## 8. 最终回归与保留核对

- 最终专项544通过，完整后端1423通过，Frontend67、Admin78通过；原有1条Starlette/httpx弃用警告。
- 测试日志：policy-tests-release.txt、backend-full-release.txt、frontend-tests.txt、admin-tests.txt；中间日志及失败用例记录全部保留。
- 冻结文件：V1.1及其旧交付完全保留；V1.2新目录freeze-manifest.json登记本版冻结内容。
- [隔离验证](isolation-verification.json)、[源码差异](source-diff.json)、[测试摘要](tests-summary.json)、[前源码快照](source-before.zip)、[后源码快照](source-after.zip)。
- 旧业务代码与原测试未变，修改仅限原独立Policy包3文件，新增V1.2纯模块和测试。不修改实际Report/Generation表，不创建生产提交元数据。
