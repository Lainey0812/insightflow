# Workflow 节点详情按类型展示（REQ-0127）

右侧详情按节点种类切换，不再把所有字段堆在同一栏。头部固定：节点名称、类型标签、状态、耗时。类型颜色分开：规则 / 逻辑、大模型、API / 工具、知识库检索。没有归类的节点标为未归类，只保留 Input 和 Output。

归类使用现有节点名，不把现有节点改写成 RAG 或 Router。规则 / 逻辑：计划校验、事实校验、人工审核、分析执行。大模型：需求理解、分析规划、洞察生成。API / 工具：数据画像、证据构建、图表构建、报告组装、报告保存。属性里的 `node_type` 或 `kind` 为 rag、llm、tool、rule 时，未在上表中的节点才按该值归类。

页签：Input、Output 始终存在。大模型多 Prompt & Model，工具多 API Request/Response，检索多 Knowledge Chunks。节点状态为错误或已有错误代码时，再高亮 Error Stack。

规则节点的 Output 展示已保存的判断字段，例如 `validation_role`、`coverage_status`、可执行数。没有 `condition_matched` 或分支字段时写明未采集，不补造命中结果。

大模型页签读取调用摘要：Prompt 快照编号、登记版本号、模型名、temperature、max tokens、超时。完整请求和模型原文仍要快照凭证，默认不展示。Input Token、Output Token、Cached Token、预估成本没有采集时显示未采集，不写成 0。

工具页签展示工具名、请求 JSON、已保存的结果 JSON 和节点耗时。没有 HTTP 地址或状态码时显示未采集，不把哈希当成 URL，也不默认 200。

当前真实 Workflow 没有检索节点。检索页签只在节点被标成检索时出现，展示策略、查询词和切片的文本、来源、分数；缺哪一项就标未采集。

浏览器核对 `wf_d37a472ad4de4d28b5c2df9646c84914`：数据画像为 API / 工具，地址和 HTTP 状态未采集，耗时 24.6 ms。需求理解为大模型，模型名 qwen3.8-flash，版本号已读到登记版本，Token 与成本未采集，原文未自动展开。计划校验为规则 / 逻辑，Output 有 validation_role 与 coverage_status。`wf_7a3ebf3b8f92403b80617151eb295e9b` 的需求理解为错误，Error Stack 高亮，错误代码 LLM_UNAVAILABLE，没有异常栈原文。

Admin 相关测试 17 项通过，`tsc --noEmit` 无输出。
