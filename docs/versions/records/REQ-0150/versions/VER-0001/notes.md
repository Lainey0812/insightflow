Phase 2-B1 实现两个只读列表接口，未做 Run Detail、Case Detail、Evidence、前端、Trace 路由或评分规则。

实现：
- backend/app/evaluation/run_index.py（扫描前已存在；本轮补了 cache salt、非法名符号链接、scanned_root_ids）
- backend/app/evaluation/datasets.py
- backend/app/evaluation/admin_views.py
- backend/app/services/evaluation_admin.py
- backend/app/api/admin.py、backend/app/main.py、backend/app/core/config.py
- backend/tests/test_evaluation_discovery.py

证据：docs/evaluations/evaluation-admin-b1-2026-11-13/（真实 HTTP 响应、历史目录快照对比、与设计稿的差异）。
改动前副本：docs/implementations/evaluation-admin-b1-2026-11-13/before/。

测试：相关后端 70 passed。既有红测试 test_failure_diagnosis.py:81 仍失败，未改断言。
历史 Golden 48 个文件、TC 8 个文件，扫描前后 mtime 与 SHA-256 相同，没有新增 WAL/SHM。
等待审核，不进入 Phase 2-B2。
