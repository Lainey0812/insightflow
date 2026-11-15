Phase 2-C1：Admin 评测管理页面（只读）。接入真实 B1/B2 接口，前缀 /api/v1/admin/evaluations。未改后端、Agent、Planner、Engine、HITL、Evaluator、Golden Set、历史运行或 /traces 路由。

新增：
- admin/src/types/evaluations.ts（与 Pydantic 模型对齐的类型和唯一一处枚举）
- admin/src/api/evaluations.ts（4 个方法及运行时结构校验）
- admin/src/features/evaluations/EvaluationShared.tsx（状态文案与徽标、指标卡、错误面板、分页、路径隐藏）
- admin/src/pages/EvaluationDatasetsPage.tsx、EvaluationDatasetDetailPage.tsx、EvaluationRunsPage.tsx、EvaluationRunDetailPage.tsx、EvaluationCasePlaceholderPage.tsx
- admin/src/tests/evaluations.test.tsx（28 个测试）
- admin/src/tests/fixtures/evaluations/*.json（取自 B2 真实响应）

修改：
- app/routes.tsx：新增 3 个详情路由
- app/navigation.ts：启用 Evaluation Runs；详情路径导航高亮
- api/client.ts：ApiError 增加 serverCode 和 details
- pages/GoldenSetPage.tsx：改为导出 GoldenSetContent 和打包副本哈希
- tests/golden-set.test.tsx：改为走数据集详情
- styles.css：追加 ev-* 样式

改动前副本：docs/implementations/evaluation-admin-c1-2026-11-13/before/
证据：docs/evaluations/evaluation-admin-c1-2026-11-13/

结果：
- Admin vitest：10 failed / 138 passed。失败的 10 个都是 REQ-0126 遗留，与改动前相同。
- typecheck：0
- build：0
- 实时联调：字段集与 TS 类型一致；RF-01～05 符合预期；错误码 404/422 符合预期
- 历史文件：58 个，未变化

已知限制：
- 运行详情接口不提供逐 Case Evaluator 结果
- 列表接口不提供 E2E 指标
- 运行中的 8000 进程的 TC 根目录不存在
- 顶部全局横幅文案未更新

等待审核，不进入 Phase 2-C2。
