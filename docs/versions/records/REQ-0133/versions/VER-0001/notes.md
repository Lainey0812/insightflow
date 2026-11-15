# intent-node-detail-v1

REQ-0133。只调整 Intent Parser 的右侧详情。左侧 Workflow 与左右栏布局保持不变。

字段核对：

- 已存在且已展示：节点名称、状态、耗时；span 上的数据集标识、需求字数、澄清答复数、字段数、next_action；LLM Call 的编号、状态、延迟、模板快照、重试关系；已保留的请求消息和原始响应。
- 已存在但原先未按业务结构展示：请求快照里的 user_query、clarification_answers、dataset_context；响应里的 analysis_mode、analysis_goal、constraints、uncertainties、clarification_questions。Session 中与 operation_id 匹配的 IntentArtifact 现在附在对应节点上，供快照缺失时读取。
- 运行时存在但历史调用未写入：temperature、top_p、max_tokens、token 用量和 HTTP 状态。新调用沿用已有采集，旧调用继续显示未采集。
- 完全缺失，本次不补：约束的操作符、取值和来源标记。Schema 只有 raw_text 与 validation_status。没有独立维度字段。传入模型的画像摘要没有质量信号，也没有样例行。
- 不适用：独立 Diagnostics Tab、自动约束遗漏检测、重新调用模型补历史。

没有修改 IntentArtifact 或 ParsedIntent。Analysis Planner 的输入契约未改。Bad Case 证据仍只复制节点元数据，不带需求原文。

真实节点 wf_d37a472ad4de4d28b5c2df9646c84914 的需求理解为成功，耗时 2.40 s。默认打开 Output。分析模式为探索，下一步为继续规划，四类约束均为空，没有澄清问题。Input 显示 9 字需求原文、没有补充说明、10 个字段的名称和类型，并标明未传入质量信号。LLM 只有 1 次成功调用，模板版本 intent-v1.3.3，请求约 9071 字符，响应 371 字符且 analysis_mode 为 exploratory。该历史调用的 token 与采样参数为未采集。切换 Tab 不重新执行节点。分析规划节点仍使用 Prompt & Model。左右栏约 755px 和 503px。

验证：Admin 类型检查通过；workflows、failure-diagnosis、quality-signals 共 20 项通过。后端 workflow observability 详情测试通过，匹配节点带有已保存意图，其他节点没有。读取时根状态仍按既有规则把 waiting_approval 显示为 suspended，测试期望已改为这个返回值。
