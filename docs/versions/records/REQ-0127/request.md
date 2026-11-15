详情页节点详情的展示，需要按照节点的类型分类，来展示对应的内容。
1. 规则 / 逻辑节点 (Rule / Condition / Code Node)
业务场景：如 If-Else 条件判断、Python 脚本执行、状态变量赋值。

核心诉求：看数据怎么进来的，最后走的是哪条分支。

专属详情展示：

Input Data：输入的全局状态变量（JSON 格式）。

Evaluation Result：判断结果（例如：condition_matched: true，命中了哪一个分支）。

Output Data：更新后的变量或输出。

2. 大模型节点 (LLM Node)
业务场景：常规文本生成、意图识别、结构化数据抽取。

核心诉求：排查幻觉、看 Prompt 拼得对不对、算 Token 和成本。

专属详情展示：

Prompt & Meta：

Prompt Version ID（版本号，如 v1.2.0）

Model Name（模型型号，如 gpt-4o）

Generation Parameters（Temperature、Max Tokens 等）

Input Payload：完整拼装完成的 System Prompt + History + User Message。

Raw Output：大模型吐出的原始字符串。

Metrics：Input Token / Output Token / Cached Token / 预估成本（$）。

3. API / 工具调用节点 (Tool / API Node)
业务场景：调用外部三方接口、内部微服务、计算器、网页搜索等。

核心诉求：看模型生成的入参对不对、外部服务是不是崩了。

专属详情展示：

Tool Identity：

Tool / API Name（工具名称，如 get_highway_status）

Endpoint URL（请求地址）

Request (入参)：大模型生成的结构化 JSON 参数（排查是不是少传了必填字段）。

Response (出参/三方返回)：外部 API 返回的原始报文。

Network Status：HTTP 状态码（如 200 OK, 502 Bad Gateway）及接口耗时。

4. RAG / 知识库检索节点 (RAG / Retrieval Node)
业务场景：向量检索、BM25 关键词匹配、Rerank 重排。

核心诉求：看知识库有没有搜出有用的东西，有没有混入噪音。

专属详情展示：

Retrieval Config：检索策略（如 Top-K 设置、Embedding 模型名称）。

Query String：拿什么去搜的（原始提问或优化后的检索词）。

Retrieved Chunks (召回切片明细)：

每一个切片的文本内容（Text Chunk）。

来源文档名称（Source File Name）。

相似度得分 / Rerank 分数（Score）。

当用户在左侧的“链路树”中点击任意一个节点时，右侧的详情面板可以这样实现：头部公用区：展示节点名称、Node Type 标签（带不同颜色区分）、运行状态（🟢/🔴）、单节点耗时。主体动态 Tab 区：通用 Tab：Input（输入）、Output（输出）。动态扩展 Tab（根据 node_type 实时切换）：如果是 LLM 节点 $\rightarrow$ 多出一个 Prompt & Model Tab。如果是 Tool 节点 $\rightarrow$ 多出一个 API Request/Response Tab。如果是 RAG 节点 $\rightarrow$ 多出一个 Knowledge Chunks Tab。异常 Tab：如果节点报错，额外高亮一个 Error Stack Tab 展示报错堆栈。
