# 未见输入的调用前纠错

`new-unseen-inputs.json` 尚未进行任何模型调用时，检查发现 U06 使用测试 helper 的 null_metrics 开关覆盖了非空输入的计算输出。这不适合作为本轮真实证据质量评测输入。

保留原文件而不覆盖，不将其用于真实评测。`new-unseen-inputs-v2.json` 改用真实全缺失时长列，现有 Validator 判为不可执行、没有成功计算证据；report 不调用 LLM、返回 unavailable。其余案例的输入及统计操作不变。此修正发生在新集首次调用前，不依据新集模型输出调整标签或评分。

所有新集案例都明确标注 `source=imported` 的确定性 kernel fixture，不冒充生产上传/审批/Engine 端到端执行。冻结回归 S01 保留原有真实 Engine 与审批快照。
