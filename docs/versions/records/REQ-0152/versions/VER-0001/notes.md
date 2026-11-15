Phase 2-B2：评测详情与证据读取，四个只读 GET 接口，前缀 /api/v1/admin/evaluations（/admin 同时挂载）。未改 Agent、Planner、Engine、HITL、Oracle、MustForbid、Golden Set、历史运行、前端或 /traces。

新增：
- backend/app/evaluation/evidence.py（证据种类白名单、contained_path、只读 JSON、脱敏、大小/数量/深度限制）
- backend/tests/test_evaluation_detail.py（11 个测试）

修改：
- backend/app/evaluation/admin_views.py（详情与证据响应模型）
- backend/app/evaluation/datasets.py（load_all，供冲突检测）
- backend/app/services/evaluation_admin.py（get_run / get_case / get_evidence / get_dataset；数据集关联三分类）
- backend/app/api/admin.py（四个路由）
- backend/tests/test_evaluation_discovery.py（弱关联修正后的两处预期）

改动前副本：docs/implementations/evaluation-admin-b2-2026-11-13/before/
证据：docs/evaluations/evaluation-admin-b2-2026-11-13/（真实响应、历史目录对比、差异说明、测试日志、采集脚本）

测试：评测与 B1 相关 81 passed；全量后端 1755 passed，1 failed（test_failure_diagnosis，REQ-0133 既有），test_git_unknown 排除。
历史目录：Golden 48 个文件、TC 8 个文件，路径、mtime、大小、SHA-256 前后一致，没有新增 WAL/SHM。
等待架构审核，不进入 Phase 2-C。
