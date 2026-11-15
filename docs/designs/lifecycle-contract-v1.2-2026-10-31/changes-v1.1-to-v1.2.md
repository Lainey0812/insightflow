# Lifecycle Contract V1.1 → V1.2 定向变更

REQ-0081；V1.1冻结目录保持不变。

| 标记 | 项目 | V1.1 | V1.2 |
|---|---|---|---|
| 目标 | 提交前检查 | C19同时要求generating与accepted=True，前置/后置时序冲突 | C19-A仅检查业务资格与fencing，不要求尚未产生的accepted |
| 目标 | 业务提交 | 原子持久化要求已存在，但accepted证据角色不够独立 | Business Transaction原子Report、Generation、归属与提交元数据；提交才形成可信accepted |
| 目标 | 完成观测 | 原C19隐含在同一行 | C19-B核验持久提交证据，仅允许对应report_persistence Span完成 |
| 目标 | 回执丢失 | 缺少明确“提交后返回前崩溃”分支 | 必须一致读持久事实；正确提交仍accepted；无查询/不可读/错位为unknown或inconsistent，不能直接判失败 |
| 目标 | 原token与revision | 单一提交时守卫 | A使用当前fence；B核对提交时fence与元数据，允许提交后key清空，不将合法revision+1误判为过期 |
| 目标 | 精确Span | 两层结构已要求 | 增加提交元数据中可选persistence_span_id；无Trace不阻断业务，有Trace时精确绑定，不仅匹配名称 |
| 目标 | 不可变历史Span | 终态不重开 | 保持；真实业务已交付但Span恢复为interrupted时保留缺口，不篡改成complete |
| 目标 | 检查点数量 | 32行 | 31行原样继承，C19替换为A/B，共33行；不增加Agent或Trace层级 |
| 现有 | 生产执行路径 | Session与旧ReportWorkflow/Repository | 保持不变；新Policy和证据重建仅独立使用/测试 |

**[目标]** 旧native_v1.1的C19拒绝继续兼容；native_v1.2显式使用新检查点。V1.2没有修改Business Lifecycle/Activity/Execution Outcome、控制状态矩阵、Root重开规则、unavailable Retry、Engine Resume或Legacy路径。

**[目标]** C20 unavailable不改作C19-A可交付报告；这次修订只解决原C19的可交付报告提交与完成观测。未来Writer/观察服务接入须单独审查，不能把纯Policy通过当作生产恢复已上线。
