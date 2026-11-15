# REQ-0071 Planner 超时诊断与配置修复

## 现有证据

修复前 Prompt Registry 有 8 次 Planner 调用：2 次成功，耗时 12.45 秒与 51.98 秒；6 次取消，其中 5 次约 30 秒、1 次约 60 秒，符合服务层总期限取消。成功样本数量太少，且失败样本被截止时间截断，不以成功中位数估计整体典型延迟。8 次 Intent 调用均成功，约 1.99–3.98 秒，中位数 3.31 秒。

真实入口为 app/main.py 中 AnalysisPlannerService 构造，复用 Settings.llm_timeout_seconds；app/services/analysis_planner.py 的 plan() 使用 asyncio.timeout 包裹全部尝试。CompatibleLLMProvider 的 HTTP 超时同样为该值。最近失败发生在约 59.95 秒，尚未收到模型返回，不是前端提前停止等待。服务层取消在调用台账中记录 LLM_CALL_CANCELLED；业务层显示 LLM_TIMEOUT。没有擅自改变历史错误代码。

Intent 显式发送 enable_thinking=false，Planner 旧请求未发送此参数。未发送不等于已经证实模型开启思考；服务端默认行为未直接观测。较慢生成与配置差异有关的假设，使用同一失败请求对照验证。

## 同请求实测

源请求 request_09602ba75f6943a8ae0d5f1d6f1c277f。原请求 60 秒内未返回。两次对照只增加 enable_thinking=false，保留原消息、Schema、模型和 60 秒限制，分别耗时 16.49 秒和 13.41 秒。均返回合法 JSON，真实 Validator 覆盖状态 complete，4 个任务可执行。未进行审批、执行或写入 Session 计划。技术校验通过不等于业务语义逐项验收。

调用 ID：call_ae3b9b52ff8b4c8792f767f9f05c613e、call_8ccab3830ab440398e8ec82677c54797。请求、模板和参数保存在原 Prompt Registry，不建立第二套运行记录；诊断不伪造 Run/Span 关联。原始返回、结果及校验见 attempt02/attempt03 目录。

attempt01 网络沙箱导致 LLM_UNAVAILABLE，已保留。attempt02 模型成功、Schema 通过，但诊断脚本遇到历史 Mock profile 缺少 dataset_id，后续读取校验失败。该错误不属于模型失败，原 result.json 保留；使用 get 排除旧画像后，独立本地后验校验保存为 validated-plan-followup.json，无额外模型调用。attempt03 修正诊断读取并完整通过。

## 最小修复

仅在 backend/.env 增加 INSIGHTFLOW_PLANNER_ENABLE_THINKING=false。保留 INSIGHTFLOW_LLM_TIMEOUT_SECONDS=60，沿用 qwen3.8-flash；不修改 Prompt、输出 Schema、重试次数、审批、Validator 或统计代码。真实 .env 未复制到归档。

确认无运行中 Session 后重启同一本地后端，新进程 16365。安全配置摘要和真实请求参数见 verified-configuration.json。原失败 Session 不自动重试，用户可在前台主动选择“重试准备”。

## 验证与限制

Planner、服务契约、Provider 相关自动化测试 66 项通过，1 个 warning；见 attempt02/regression.txt。真实两次请求均通过既有 Validator。配置修复降低了本次同请求观测延迟，仍不能排除模型服务负载、网络及任务复杂度影响，也不能保证未来所有请求均在 60 秒完成。没有调整总期限或增加自动超时重试，避免重复收费和长时间阻塞。没有为配置变更修改服务默认值，以保持显式配置和其他部署兼容。
