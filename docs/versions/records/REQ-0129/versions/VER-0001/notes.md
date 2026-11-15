# 开始采集节点上仍未采集的调用指标（REQ-0129）

从这次改动之后的新运行开始记录模型调用里真实返回的用量和 HTTP 状态。已经落库的 Workflow 不回填，缺的字段继续显示未采集，不写成 0。

兼容模型接口在成功响应里读取 `usage`。`prompt_tokens` 记为 `input_tokens`，`completion_tokens` 记为 `output_tokens`，`prompt_tokens_details.cached_tokens` 或 `cache_read_input_tokens` 记为 `cached_tokens`。响应里有 `total_tokens`、`estimated_cost` 或 `cost` 时一并保存。响应没有这些字段时，节点上不写对应键。

同一次调用保存 HTTP 状态码，以及去掉用户信息和查询串后的 endpoint。地址哈希仍按原方式保存。超时或连不上时没有 HTTP 状态码。密钥和上游错误正文不写入节点，也不放进错误消息。

需求理解、分析规划、洞察生成在调用成功后把这些值写到当前 span。调用失败时，span 结束会带上异常对象上的状态和地址。失败 span 另存异常类型、错误代码和最后 12 帧的文件名、行号、函数名，最长 2000 字。不保存异常原文，避免把上游正文或密钥写进观测。

本服务发出的模型请求仍然只有 model、messages、response_format、stream，以及已配置时的 enable_thinking。没有 temperature、top_p、max_tokens，配置里也没有这些项，所以这三项继续是未采集。不新增默认值，也不改模型行为。没有价格表，成本只在供应商响应里自带数字时保存。

进程内节点（数据画像、校验、执行、图表、证据、报告组装）没有对外 HTTP 调用，endpoint 和 HTTP 状态保持未采集。没有检索链路，不采集知识切片。执行结果表、完整计划和完整报告仍不放进 Workflow 观测。

Prompt & Model 页增加 HTTP 状态码和 Endpoint URL。已有的 Token 指标会读 span 上的新字段。旧 Workflow `wf_d37a472ad4de4d28b5c2df9646c84914` 的需求理解在页面上仍是未采集。

`tests/test_llm_provider.py` 26 项通过。Admin `workflows` 与 `failure-diagnosis` 16 项通过，`tsc --noEmit` 无输出。
