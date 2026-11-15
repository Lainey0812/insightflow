# Workflow Trace V0.1 交付记录

对应 REQ-0043 及其继续指令 REQ-0044。先保存 design.md 审计与契约，再按其实施最小后端埋点。

新增 Run/Span/Event/RunManifest、独立 SQLite 观测存储、安全记录器、四个只读 Admin API。复用 execution_id + report attempt 和既有数据/计划/批准版本；没有创建新的业务工作流状态或改写执行结果。增加 Report 四阶段及最终保存观测。

Manifest 冻结 Prompt/schema/model 配置和源码指纹；候选记录 index、引用、role、规则及汇总。默认不保存原始数据/自由文本，元信息不自动删除。写入失败降级，不影响业务；全丢失、容量增长与单进程恢复限制已披露。

自动化：backend 696、frontend 52、Admin 14 项通过；两前端构建与 Admin 类型检查通过。26 个新测试涵盖成功、partial、失败、无证据、并发、重试、重启、权限及写入故障。早期新增并发测试的固定执行请求 ID 冲突已修复，失败日志继续保留，没有放宽 Engine 幂等规则。

真实 qwen3.8-flash 两次调用均返回 3 条候选，均被现有 Fact Validator 拒绝，Run 如实 failed，Engine 结果与重启查询正常。不是整条 LLM 主流程评测：上游 Intent/Planner 使用有标签的测试传输，报告模型是真实调用。所有输出、失败、最终 API 回读均另存，未更换 Prompt 或优化校验业务。

代码变更限于 Trace 新文件及 core/config.py、main.py、workflow/reporting.py、services/analysis_report.py、reporting/fact_validation.py 的观测接入，另更新非密钥环境样例与文档。前后端页面和 Planner/HITL/Engine 未改。源码清单、完整性核对与 ZIP 快照见本目录；真实 .env、业务数据库、上传文件不进入快照。

当前 Admin 前端尚未接入查询；Intent/Planner/HITL/Engine、导入报告 API 和导出/Presentation 尚未新增内部 Trace。旧报告不会被伪造回填。
