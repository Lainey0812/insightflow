# 埋点采集生成参数、Token、HTTP 状态和成本（REQ-0131）

在模型调用上增加记录，不再只检查历史库里有没有这些字段。已经落库的调用不回填。

InsightFlow 之后发出的模型请求带上 temperature、top_p、max_tokens。默认是 0.7、0.8、8192，可用 `INSIGHTFLOW_LLM_TEMPERATURE`、`INSIGHTFLOW_LLM_TOP_P`、`INSIGHTFLOW_LLM_MAX_TOKENS` 覆盖。这三个值写入请求快照的 model_parameters，并写到节点属性。应用入口和回归、回放脚本都走同一套配置。

调用结束时，把 HTTP 状态码、去掉用户信息和查询串的 endpoint，以及 usage 写进调用记录。`prompt_tokens` 记为 input_tokens，`completion_tokens` 记为 output_tokens，`prompt_tokens_details.cached_tokens` 记为 cached_tokens。详情页的调用摘要会读这些字段。失败响应同样记下 HTTP 状态码。

预估成本在供应商 usage 自带 cost 时直接保存。没有该字段时，若配置了 `INSIGHTFLOW_LLM_INPUT_USD_PER_MILLION` 和 `INSIGHTFLOW_LLM_OUTPUT_USD_PER_MILLION`，按 input、output token 计算。当前模型接口的 usage 有 token 和 cached_tokens，没有金额字段，也没有配置单价，所以成本仍要等单价或供应商金额。

对当前模型接口做了一次最小请求：HTTP 200，usage 含 prompt_tokens、completion_tokens、total_tokens 和 cached_tokens。没有 cost。

`tests/test_llm_provider.py` 与 `tests/test_prompt_registry.py` 共 60 项通过，其中包含历史请求体仍与冻结捕获一致的检查。
