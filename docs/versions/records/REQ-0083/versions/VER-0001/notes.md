Observability MVP Vertical Slice 01，REQ-0083。第一步入口审计完成，依据用户严格边界停止后续接入。
四目标已有准备埋点，Plan Validator两个真实校验位置且其中内部可嵌套；现有Root仅按Session创建/查询，无显式Business Workflow绑定和传播。
核对本地启动器cwd及backend/.env后只读查询正确项目var库：Business Workflows=0、routes=0、trace_workflow_links=0、Root manifest workflow_id=0；Session6（real_v1 5）、准备Root3、Report Run1。不能以Session唯一Root推断Business Workflow。
未编造Workflow、不新增Adapter/生产修改、不触发CSV/真实LLM、不写新Run/Span、不改Engine/Reporting/契约/状态机。新自动化测试未运行，不宣称验收通过。
保存readiness-corrected.json和原始错误cwd路径查询readiness.json（作为解析纠正证据保留），现有Trace只读导出明确非新运行，源码/冻结契约哈希前后一致。
解除阻断需单独授权最小单流程Workflow身份登记与显式传播；不自动回填历史、Switch或全面Writer重构。本轮按要求报告并停止。
