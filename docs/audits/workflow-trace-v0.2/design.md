# Trace V0.2 实施前审计

需求 REQ-0045。复用 V0.1，不新增 Run 表、Trace 数据库或业务状态。

## 已有能力

- Run：queued/running/complete/partial/unavailable/failed/interrupted；已有 session/execution、attempt/retry_of、实际时间、耗时、error_code、integrity 和 manifest。
- Span：parent_span_id 同 Run 约束；running/complete/partial/failed/skipped/interrupted，时间、耗时、受控 attributes。
- Event：Run 内 sequence，阶段事件、LLM 开始/返回、候选 index、evidence_refs、role、rule_ids、接受/拒绝汇总。V0.1 每 Run 上限 256 条，单条 payload 8KiB。
- RunManifest：数据/计划/审批引用、Prompt/Schema/生成版本、模型配置、源码 SHA；公开模型保持不变。
- API：Run 列表/详情、Span 列表、Event 分页，/admin 与 /api/v1/admin 为同一实现。
- 权限：服务端 INSIGHTFLOW_ADMIN_READ_TOKEN 与 X-Admin-Token；未配置 503、无权限 403，不是账户系统。
- Admin：React/TS/Vite/React Router，已有 Layout、API Client、错误边界，/traces 尚为空状态，无凭证传递能力。

## 不能提供的原文

没有完整输入、输出或候选自由文本快照；只有受控摘要、字节数、计数、证据 ID 与规则。没有 token usage、temperature/top_p 实际值或模型服务请求 ID；未知保持不可用。规则翻译仅解释已存规则含义，不能声称人工认定候选确实错误。不读取原始业务表来填充缺失快照，不发布验证库或历史评测文件。

## 最小调整

1. TraceRepository.runs 增加可选 queued_at 起止时间、Span name（EXISTS）、Prompt/生成/报告 Schema 版本匹配；原 status/分页接口保持兼容。筛选在数据库执行，禁止只筛当前页。
2. 复用同一管理员凭证，新增 /access 凭证交换与退出接口。Cookie 为现有凭证派生的短期签名，不包含原密钥；HttpOnly、SameSite=Strict、HTTPS 时 Secure；刷新后继续请求。原 X-Admin-Token API 保持兼容，不新增账户、角色、运行记录或写业务数据。
3. Admin 新增 trace types/service、只读访问表单、列表、详情、树形 Span、Inspector 与对应测试。过滤器和页码放 URL；节点选择放 URL，刷新可恢复。切换与刷新取消旧请求，错误与空列表分开。
4. Inspector 仅展示允许字段；技术 JSON 也不原样输出未知 metadata 字段，避免未来字段夹带敏感内容。模型信息来自实际 Span 或当前 LLM span 的 Manifest，不把 Run 全局模型冒充每个确定性节点调用了模型。
5. 修改布局的 V0.1 提示和详情导航；Dashboard、Versions、Settings 仍为占位，不提前加入编辑或评测功能。

## 拟变更文件

backend/app/api/admin.py、storage/trace_repository.py；新增 backend Trace V0.2 筛选/访问测试。

admin/src/api/client.ts、app/routes.tsx、layouts/AdminLayout.tsx、pages/TracesPage.tsx、styles.css；新增 types/traces.ts、api/traces.ts、features/traces/*、pages/TraceDetailPage.tsx 及测试；更新受影响的路由测试。

文档与版本档案追加。原 Trace Schema、观测写入、Planner、HITL、Engine、Report 业务不修改。

## 验证方案

检查筛选/分页组合、父子关系、历史缺失、partial 标识、失败定位、事件翻页、权限、Cookie 到期/篡改/退出、请求失败与刷新恢复；全量 backend、Admin 类型/测试/构建、原前端构建。浏览器使用真正由 ReportWorkflow 产生并持久化的记录，与 SQLite 核对；受控传输测试与真实 LLM 运行分别标注，不编造成功记录。
