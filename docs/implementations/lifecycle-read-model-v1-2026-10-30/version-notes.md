# Lifecycle Read Model V1

需求：用户所称 REQ-0064 下一阶段；新原文档案 REQ-0065，继续指令 REQ-0066；不覆盖原 REQ-0064 只读评审。

新增只读 Lifecycle DTO、SQLite mode=ro reader、纯聚合函数及受既有 Admin 权限保护的 `/admin/workflows/{session_id}/lifecycle`（亦有 `/api/v1` 前缀）。保留 Session 唯一 Root，不迁移数据库，不新增 ReportGeneration 历史，不修改业务状态、Trace 转换、模型配置、Prompt 或分析算法；不开发 Progress UI。

现有源码只修改 api/admin.py、main.py 两个接线文件；增加 3 个模块和 1 个测试文件。前后源码 ZIP、哈希验证、完整数据契约、兼容性报告、真实已有 Session API 返回、查询前后数据库哈希及失败测试日志均保留。

最终后端 837 passed（既有 806 + 新增 31），Admin/前台构建通过。真实业务库 5 个 Session 只读查询前后 dump 哈希不变；未调用生产 LLM、未触发用户业务重跑、未重启原服务。新接口在后端正常重载后生效，本次查询验证使用隔离只读 API Host。

已知限制：非跨库原子快照；ReportGeneration 只有 latest attempt；running 不能证明活性；旧 Mock/manual 数据不推断真实成功；未采集的过程不补 Span；不打开原上传文件重算校验。详情见 compatibility-and-limits.md。

完成本阶段后停止，等待评审，不进入下一阶段。
