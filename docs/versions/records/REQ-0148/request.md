# InsightFlow Evaluation Platform — Phase 2-B1

## 任务：Run Index & Dataset Discovery

### 一、目标

基于已完成的 Phase 1 评测内核和 Phase 2-A 架构设计，实现两个后端只读能力：

1. Run Discovery：统一发现 Golden 与 TC Regression 运行。
2. Dataset Discovery：统一发现现有测试集及其来源。

交付两个 API：

- `GET /api/v1/admin/evaluations/runs`
- `GET /api/v1/admin/evaluations/datasets`

本轮只实现 B1，完成后停止。

### 二、实施前检查

先读取：

- `docs/designs/evaluation-admin-v1-2026-11-13/DESIGN.md`
- REQ-0146 和 REQ-0147 的决策记录。
- `backend/app/evaluation/` 下的统一契约、`read_run()`、Manifest 和完整性校验。
- 现有 FastAPI Admin 路由与测试。
- Golden / TC 的真实运行目录结构。

如果设计与真实代码不一致，先记录差异，不得擅自扩大范围。

### 三、Run Discovery Service

实现只读运行发现服务。

要求：

1. 只扫描显式配置的允许根目录。
2. 仅识别符合现有格式的 `gf_` 和 `rg_` 运行。
3. 通过 Phase 1 的 `read_run()` 获取运行内容，不重新实现评分逻辑。
4. 索引仅保存定位与发现信息，不作为第二套业务事实来源。
5. 支持 FINISHED、INCOMPLETE 和历史运行。
6. 不从目录名推断 Agent Version、Dataset Version 或 Evaluator Version。
7. 不打开任何历史 SQLite。
8. 不修改历史文件。

必须处理：

- 重复 Run ID。
- 缺少 Manifest。
- 缺少必要 JSON。
- JSON 损坏。
- 不完整运行。
- 符号链接越界。
- 非法目录名。
- 单个目录读取异常。

单个运行损坏不得导致整个列表失败。

重复 ID 不得随机选择其中一个运行。需要确定性冲突处理，并记录冲突信息。

### 四、Dataset Discovery Service

建立只读 Dataset Registry。

来源仅限仓库中可验证的 Golden / TC 数据集。

展示字段：

- dataset_id
- dataset_version
- dataset_hash
- dataset_type
- case_count
- source
- freeze_status
- related_run_count

约束：

- 未记录版本时返回 null。
- 未提供正式冻结声明时，freeze_status 为 UNDECLARED。
- 文件 Hash 不等于正式 Dataset Version。
- 不自动创建 Golden Set。
- 不修改测试集。
- 不开发数据集编辑功能。
- 不从历史运行中推断不存在的版本信息。

关联运行时，应明确区分已验证的 Dataset Hash 匹配与仅能根据历史路径建立的弱关联。

### 五、API 契约

沿用现有 FastAPI Admin 路由规范。

#### GET /api/v1/admin/evaluations/runs

支持：

- page
- page_size
- run_type
- status
- integrity_status
- sort

响应至少包含：

- items
- total
- page
- page_size
- discovery_warnings

每条 Run 包含：

- run_id
- run_type
- created_at
- lifecycle_status
- integrity_status
- agent_id
- agent_version
- dataset_id
- dataset_version
- dataset_hash
- case_count
- evaluated_case_count

缺失字段返回 null，不得伪造。

#### GET /api/v1/admin/evaluations/datasets

支持：

- page
- page_size
- dataset_type
- sort

响应至少包含：

- items
- total
- page
- page_size
- discovery_warnings

使用明确的 Pydantic Response Model。

分页参数需要限制合法范围。

排序必须稳定；时间相同时以唯一定位标识作为次级排序键。

不得向前端返回本地绝对路径。

### 六、数据安全

- 根目录白名单。
- 路径规范化。
- 拒绝目录越界。
- 不跟随越界符号链接。
- 不开放任意文件读取。
- 不返回密钥或完整模型连接凭据。
- 不打开 SQLite。
- 不写入运行目录。
- 不修改原有历史日志。

### 七、测试与验收

使用临时目录和 Fixtures 测试，禁止调用真实 LLM。

至少覆盖：

1. 发现历史 Golden Run。
2. 发现历史 TC Run。
3. 发现新格式 Golden Run。
4. 发现 INCOMPLETE Run。
5. 空目录。
6. 损坏 JSON。
7. 缺失 Manifest。
8. 重复 Run ID。
9. 符号链接越界。
10. 非法运行目录。
11. 分页。
12. 稳定排序。
13. 类型与状态筛选。
14. Dataset Hash 与版本缺失。
15. 冻结状态 UNDECLARED。
16. Dataset 与 Run 关联。
17. 单个损坏目录不影响其他结果。
18. 两个 API 的实际响应符合 Pydantic Schema。
19. `/admin` 与 `/api/v1/admin` 的现有路由兼容。
20. 历史文件 SHA-256 不变。

额外验证：扫描历史运行目录前后，文件清单、修改时间和哈希保持不变，不产生 SQLite WAL/SHM 文件。

运行相关后端测试，并记录既有红测试，不得修改无关断言。

### 八、禁止事项

- 不开发 Run Detail。
- 不开发 Case Detail。
- 不开发 Evidence API。
- 不开发 Admin 前端。
- 不修改 Trace 路由。
- 不开发 Bad Case 回流。
- 不引入数据库迁移。
- 不实现任务调度或从 Admin 启动评测。
- 不修改 Phase 1 评分规则。
- 不修改 Golden Set。
- 不改写历史运行。
- 不进入 Phase 2-B2。

### 九、交付报告

完成后提供：

1. 实际新增与修改文件。
2. Run Discovery 设计及异常处理策略。
3. Dataset Discovery 的数据来源与关联规则。
4. 两个 API 的真实响应示例。
5. 自动化测试命令与结果。
6. 历史目录完整性验证。
7. 已知限制及需要产品决策的问题。
8. 是否满足进入 Phase 2-B2 的条件。

所有验证证据保存到独立的新目录，不覆盖此前 Phase 1 的证据。

**完成 B1 后立即停止，等待审核。**
