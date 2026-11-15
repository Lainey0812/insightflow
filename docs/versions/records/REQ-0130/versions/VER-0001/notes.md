# 从 InsightFlow 已有记录补齐未采集项（REQ-0130）

节点详情改为读取 InsightFlow 里已经保存的调用记录和节点属性，不回写历史 SQLite，也不补造缺失数字。

模型调用摘要在返回时核对 `client_config.endpoint_sha256` 与当前模型地址。哈希一致时，Prompt & Model 显示去掉用户信息和查询串的 endpoint。哈希不一致或没有当前地址时仍是未采集。已核对当前服务上的历史调用哈希一致。

进程内节点（数据画像、证据、图表、报告组装、报告保存）没有对外 HTTP。API 页写明进程内执行，并展示节点上已经保存的入参和计数。不写 200，也不把内部调用伪装成 URL。

Input 展示该节点已保存的属性。temperature、max_tokens、top_p 不在已保存的请求参数里，配置也没有这三项。历史响应只保存了模型正文，没有 `usage`，所以 Input Token、Output Token、Cached Token、预估成本和 HTTP 状态码仍然是未采集。新的模型调用会按 REQ-0129 把供应商实际返回的用量和状态写到 span。

浏览器打开已有 Workflow 的需求理解：Endpoint URL 已显示，Token、成本和 HTTP 状态码仍是未采集。数据画像的 API 页显示进程内执行和已保存的解析参数。

`tests/test_llm_provider.py` 27 项通过。Admin `workflows` 与 `failure-diagnosis` 16 项通过，`tsc --noEmit` 无输出。
