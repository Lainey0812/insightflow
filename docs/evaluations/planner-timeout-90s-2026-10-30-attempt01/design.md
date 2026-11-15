# Planner 90 秒对照测试（运行前冻结）

依据 REQ-0060 用户对延长超时对照测试的确认，关联 REQ-0059 已记录的自然超时。

仅一次真实调用。重放 request_4b0b7ef6fd574f9aa614df5e82d9c29c 的实际已保存模型 payload，不重新拼接 Prompt，不修改字段、Schema、模型、thinking 或其他 API 参数。原失败 Session=8d7d0076ff4647eb99b8561ea36e91ef。Provider 等待和测试总时限改为 90 秒，运行服务器及 .env 仍为原配置。

复用现有 CompatibleLLMProvider、CallRecorder、PromptRegistryRepository，将新调用保存为独立 operation_id。它是离线诊断重放，不是前台工作流恢复，因此不挂到已结束的旧 Span，不伪造 Root/Span。原请求、CallRecord 和失败 Attempt 不变。原始请求继续只在原 Registry 的受控存储中；文档只保存引用/哈希及模型返回的计划。

结果分层：模型调用是否返回；原有 validate_draft 是否通过；原有 PlanValidator 的结果。不得把技术可执行性等同约束忠实或已批准；不调用 Engine，不写入/批准 Session 计划。

判读预先确定：30–90 秒成功仅证明原时限对本次响应不足；90 秒仍超时不能区分模型生成、排队和网络；30 秒内成功只能证明本次成功和时延波动，不能宣布问题修复。无首 token/服务端分解时，不把耗时归因为 thinking 或某个 Prompt 片段。

不在本轮增加更多模型参数对照或修改应用源码。生成实际结果后追加报告，不覆盖本设计或旧评测。
