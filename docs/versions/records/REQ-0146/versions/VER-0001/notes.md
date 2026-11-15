Phase 2-A 设计交付（只设计，未修改任何源码、测试、路由或历史数据）。

- 设计文档：docs/designs/evaluation-admin-v1-2026-11-13/DESIGN.md（复用矩阵、页面信息架构、6 个只读 API 契约与 JSON 示例、模块划分与数据流、前端复用、状态与指标规则、完整性与权限边界、Phase 2-B1/B2/C1/C2/D 拆分与验收、Phase 1 契约缺口 G1–G12、风险、产品决策 Q1–Q6）。
- 审查依据：实际读取 admin 路由与页面、admin.py、regression_runs.py、evaluation 模块；用 read_run 读取 3 个现有运行；Admin 前端测试实测 10 failed / 109 passed（REQ-0126 遗留，未改动）。
- 等待架构审核，不进入 Phase 2-B。
