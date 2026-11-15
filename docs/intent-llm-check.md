# LLM 连接与 Intent Parser 复测

后续已完成 [Intent V1.3真实模型回归与独立评测](evaluations/intent-v1.3.3/report.md)，模型仍为qwen3.8-flash，当前Prompt为intent-v1.3.3。有效调用、结构正确与语义质量分别记录；以下保留连接恢复时的v1.1记录。

2026-10-27：真实模型已可用，之前的 403 权限阻塞在本轮未再出现。本次直接加载 backend/.env，未输出或保存 API Key，未修改 Key。

## 本轮结果

- 真实 qwen3.8-flash 简短请求 HTTP 200，约 0.6 秒返回 OK。
- 项目实际 IntentParserService 成功返回，is_mock=false，严格 JSON Schema 和流程规则均通过。
- 固定 40 条真实模型评测全部返回有效结构，模式 40/40，阻断识别 10/10，无编造决策目标（36 个预期为空的样本）。
- 约束召回 37/47（78.7%），整例通过 30/40；低于 95% 约束召回目标。连接成功不等于语义验收通过。
- 后端自动化回归：447 passed；本轮未修改前端。

完整评分、失败样本和局限性见 [评测与 Bad Case](intent-evaluation.md) 与 [逐条模型输出](intent-live-evaluation.json)。参考标签尚未完成人工复核，本轮每个样本仅运行一次。

## 本轮必要兼容修复

1. 默认思考模式的严格输出诊断约 50 秒，超过现有 30 秒总超时。增加可选配置 INSIGHTFLOW_INTENT_ENABLE_THINKING，当前本地设置 false，仅影响 Intent；其他模型接口留空时省略扩展参数。未放宽严格 JSON Schema。参数依据 [阿里云官方说明](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)。
2. 原非空文本正则在该端点表现为只生成单字。改用语义等价、兼容完整匹配的正则后，分析目标与约束恢复完整文本；增加多字符、多行和空白回归测试。

诊断对照：[响应耗时](intent-latency-probe.json)、[旧规则单字输出](intent-non-thinking-check.json)、[新规则完整输出](intent-pattern-compatibility-check.json)、[实际服务成功输出](intent-connection-check.json)。不能将旧规则下 Schema 合法的单字结果视为语义成功。

## 调用示例结果

输入：“比较不同地区的销售额，并找出销售额最高的三个地区。”

实际输出：goal_driven / proceed；分析目标为比较地区销售额并找出前三名，decision_goal=null；metric_requirements 保留“销售额”，analysis_limits 保留“最高的三个地区”，均为 unverified；没有创建任务、执行统计或生成报告。

## 配置生效范围

本轮在独立测试进程显式加载 backend/.env。应用与评测脚本仍不会自动读取该文件；运行中的后端需要重新加载这些环境变量并重启，才会使用本轮配置。未改动聊天、HITL、Planner 或 Report 的业务接线。

## 历史诊断

此前曾发现 BASE_URL 重复地域域名导致 TLS 主机名错误，修正后端点可达，但模型调用返回 403 AccessDenied.Unpurchased；2026-10-27 11:14 的复测仍为 403。本轮随后已取得成功响应。历史记录保留在 [连接诊断](intent-connection-diagnostics.json)，历史权限错误不代表当前状态。
