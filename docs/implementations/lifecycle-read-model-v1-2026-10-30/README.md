# Lifecycle Read Model V1 — 第一阶段交付

日期：2026-10-30。用户任务标识 REQ-0064；需求档案流水号 REQ-0065（实施）、REQ-0066（“重新”继续），关联原 REQ-0064 只读评审。旧文档、旧档案与失败记录保留。

本阶段仅提供查询投影。没有新增业务表、Root 表或 ReportGeneration 历史表；没有修改 Session/TraceRun 状态枚举、状态迁移、LLM Prompt、模型参数、审批、统计操作或报告生成逻辑；没有新增 Admin Progress UI。

- [数据契约与判定规则](data-contract.md)
- [兼容性验证与已知限制](compatibility-and-limits.md)
- [现有本地业务记录的 API 返回](existing-business-api-examples.json)
- [查询前后数据库一致性证明](readonly-database-proof.json)
- [最终后端回归](backend-regression-delivery.txt)
- [Admin 构建](admin-build.txt)、[前台构建](frontend-build.txt)
- [源码差异与保护范围](source-verification.json)

## 实现位置

| 文件 | 用途 |
|---|---|
| `backend/app/domain/lifecycle.py` | 受控查询 DTO 与只读语义枚举 |
| `backend/app/storage/lifecycle_reader.py` | 两库只读事务读取、业务版本复查；不初始化数据库 |
| `backend/app/services/lifecycle.py` | 纯函数 `aggregate(snapshot, session_id)` 与薄查询服务 |
| `backend/app/api/admin.py` | 新增受现有 Admin 权限保护的 GET；旧接口不变 |
| `backend/app/main.py` | 注入既有业务库/Trace 库路径 |
| `backend/tests/test_lifecycle.py` | 只读性、关联、安全边界和真实仓储链路测试 |

## 查询接口

`GET /admin/workflows/{session_id}/lifecycle`

兼容前缀：`GET /api/v1/admin/workflows/{session_id}/lifecycle`。沿用当前 Admin 本地测试权限或只读 Token/Cookie，不另建身份机制；响应 `Cache-Control: no-store`。

例如在本地测试访问模式已经启用的现有环境中，后端载入新代码后可调用：

```sh
curl http://127.0.0.1:8000/admin/workflows/04627ec38ec245bf8794111a84803d84/lifecycle
```

非本地测试部署使用既有 Admin 凭证。不存在会话返回标准 `SESSION_NOT_FOUND` / 404；缺权限沿用 403 / 未配置 503。数据无法可靠绑定时 GET 返回 200 + `unknown` 及原因，而不是伪造业务失败/成功。服务未注入时 `LIFECYCLE_UNAVAILABLE` / 503。

现有后台进程没有在本次交付中重启，避免启动恢复钩子改变已有任务。新路由在后端正常重新加载后生效；本次 API 验证使用隔离的只读 API Host 读取真实本地数据库，没有调用生产启动恢复。

## 验证性质

`test_lifecycle.py` 的链路测试通过现有真实上传、审批、执行、报告仓储及 API 建立记录，模型传输使用明确的测试 Provider；这不是新增真实模型质量评测。另有 5 个真实已有本地 Session 通过只读 API 查询，返回待审批 1 个、准备失败 3 个、旧 Mock 流程 unknown 1 个。没有为验证而新增真实用户运行或发送数据到模型。

现有生产业务库没有可用于新增成功报告链路验收的已批准执行记录；成功、partial、报告失败与重试由临时数据库中的真实业务服务/持久化链路验证，不冒充生产历史。

本阶段完成后停止，等待评审；不自动推进埋点或 UI。
