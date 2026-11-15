# 兼容性验证报告与推断边界

## 变更边界

新增 domain DTO、只读 reader、聚合服务、测试；仅修改既有 `api/admin.py` 增加独立路由、`main.py` 注入路径。未改变原 `/admin/workflows/{id}` 的 4 个字段，也未把默认 `/admin/runs` 改为 Workflow 列表。Report Trace、Prompt Registry、Spans/Events/Comparison 旧端点保持原契约。

无数据库变更；无迁移；无新 Root、无 ReportGeneration 历史表。`domain/enums.py`、`domain/tracing.py`、`storage/trace_repository.py` 及业务服务全部保留原内容。使用 `source-before.json` 与 `source-verification.json` 验证，源码修改只限列出的两个接线文件；三个 LLM 节点及 Prompt、业务规则和模型配置未动。真实 .env 不复制、不修改。

## 测试与证据

最终以 `backend-regression-delivery.txt` 为准：原有 806 个测试 + 新增 31 个生命周期测试，共 837 个。Admin 和前台构建分别保存日志，均通过。唯一后端警告为已有 Starlette TestClient/httpx 弃用提示。

新增覆盖：

- 真实 Session + 上传画像 + 持久化计划的待审批状态；澄清暂停与补充后继续。
- Planner 超时失败与合法重试；Root 保持同一个关联。
- 真实批准、claim 时执行活动、恢复中断，不创建不存在的 Engine Span。
- 真实 Engine 部分任务失败，Report partial 仍保留成功结果。
- Engine success + Report LLM 失败的部分成功；基于现有失败记录重试，attempt 2 交付，原执行 ID 不变。
- 完成后删除辅助任务形成 plan v2，旧执行/报告不被新分支沿用；旧回调误改完成时 unknown。
- 当前批准、plan、dataset/version/hash、报告/audit、执行任务集合、Session accepted IDs 校验；缺记录 unknown。
- 多个当前执行候选返回 ambiguous；不按最新成功时间选择。
- queued/generating/failed/unavailable、空结果成功、报告缺失、未来 Trace attempt、报告相反终态。
- Trace 全缺或存储不可用但业务成功；Trace 绑定冲突则 unknown/inconsistent；不会伪造 Span。
- 业务查询期间另一连接更新 Session，被 revision/content 复查识别。
- 两个 API 前缀、404、403、no-store；旧 Runs/Root/Prompt API 保持可读。
- URI mode=ro + query_only 拒绝 UPDATE；重复 GET 前后业务与 Trace 的 SQL dump 相等；未调用 review_presentation/Engine approval check 等写侧服务。
- 新只读服务实例重开数据库后返回同一结果；缺失数据库不创建文件。

真实已有数据库验证：5 个 Session 的新 API 返回保存在 `existing-business-api-examples.json`，前后两库 SQL dump 哈希一致见 `readonly-database-proof.json`。验证器只承载新 Admin GET 的隔离 FastAPI Host，不执行生产 lifespan；没有触发 LLM、业务重跑或重启恢复。

历史失败日志保留：`backend-regression.txt` 记录强化 Trace/业务冲突规则后，两个旧测试 fixture 仍带矛盾报告 Trace 的失败；随后明确区分“报告未启动且无 Trace”与“报告记录缺失但 Trace 声称已完成”，修正 fixture 及断言。`backend-regression-r2.txt`、`backend-regression-final.txt` 和最终日志均保留，不覆盖失败。旧 `lifecycle-tests*.txt` 也保留。

## 尚不能可靠推断

| 范围 | 本阶段处理 |
|---|---|
| ReportGeneration 更早 attempt 的完整业务历史 | 只有 latest 行，不重建；report_attempt_history=not_guaranteed。存在的旧 Trace 不是业务历史表的替代品。 |
| 跨库同时刻原子快照 | 明示 non_atomic；复查 Session 能发现常规业务提交漂移，但不是分布式事务，也不能保证响应之后没有变化。 |
| 保存为 running 的进程是否仍存活 | activity 仅表示最后持久化活动；没有心跳/租约，不根据时间推断超时、成功或失败。已有 recovery 何时运行仍由原业务系统决定。 |
| 旧 Mock/manual/imported 会话的真实 Workflow 生命周期 | unknown + unsupported_workflow；不把历史 Mock 完成当真实成功。 |
| 缺审批快照/旧版本校验记录 | unknown，不重新 Validator、不补当前配置。 |
| 当前分支存在多个候选执行且无唯一当前执行指针 | unknown + execution_ambiguous，不选择最新时间。 |
| HITL、Engine、Chart 等过程没有完整埋点 | collection incomplete；真实 ExecutionResult 可证明结果状态，不能证明所有节点过程被采集。 |
| 完整请求、Prompt/LLM 调用内容 | 不由本接口返回；继续使用现有受控 Registry API。未修改历史 RunManifest。 |
| 原始上传文件是否仍在磁盘/是否已被外部替换 | 本接口核对保存的 FileInfo/画像版本/哈希，不打开原文件重算；真实数据加载仍由原 Engine 负责。 |
| 报告数值和业务洞察质量 | 不重新计算/事实校验，只核对已保存的生成/交付及分支关联，不能当作新的业务质量验收。 |
| 业务库不可用与 Trace 库不可用 | 前者业务 unknown；后者仅 collection unavailable，已有可信业务成功仍可显示。损坏/矛盾记录则按明确问题保守处理。 |

## 运行与后续边界

正常启动命令仍使用项目既有方式。测试可运行 `.venv/bin/pytest -q backend/tests/test_lifecycle.py` 或完整 `backend/tests`。本轮没有重启原后端进程；因此原运行进程需要正常重载才有新接口，不把测试 Host 冒充已部署接口。

等待本轮评审后才能讨论 Root 完整生命周期埋点、ReportGeneration 历史或 Progress UI，本次均未实施。
