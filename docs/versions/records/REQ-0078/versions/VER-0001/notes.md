Lifecycle Contract V1.0（设计稿），对应 REQ-0078。
基于当前真实源码及 Phase 02-A 设计补充，新增完整身份/归属契约、权威来源、12 状态 ALLOWED 全矩阵、业务命令提交矩阵、ReportGeneration 状态矩阵、Lifecycle 判定矩阵、12 类 Runtime 节点、当前 Root/Report Run 与目标 Root 转换矩阵、31 类异常恢复、CAS/幂等/fencing/Switch 门槛、验收测试设计和源码符号索引。
明确区分现有实现、Expand 已具备空结构与目标设计；说明 Root 仍只追踪准备、历史独立 Report Run 保留、现有嵌套 Span 与两层目标的差距、Registry 强制捕获与 Trace fail-open 的差异。
验证：269 个业务源码/测试/前端文件哈希未改变；12 个 ALLOWED 源状态与文档矩阵一致；269 条 AST 源码符号位置可追溯。不修改业务代码或数据库，不运行 LLM，不宣称目标功能已实现；目标测试矩阵是设计，不是本轮执行结果。
完成后停止，等待评审；不开始 Backfill 或 Workflow Switch。
