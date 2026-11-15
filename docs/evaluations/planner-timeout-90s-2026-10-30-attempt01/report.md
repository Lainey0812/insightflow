# Planner 超时对照：真实结果与限制

REQ-0060，2026-10-30。一次独立诊断重放，非前台任务恢复。运行前规则在 design.md 冻结。

## 超时结论

同一个已保存的请求，保持 qwen3.8-flash、Prompt、消息、输出 Schema、非流式及其他模型参数完全相同，仅将本次 Provider/测试总时限延长到 90 秒，成功获得响应。实际 Provider 耗时 **51.976 秒**，测试观测为 **51.980 秒**。原同需求两次调用在约 29.946 / 29.943 秒被应用的 30 秒总时限取消。

本次证明模型连接和请求可用，30 秒上限不足以容纳本次慢响应。不能证明此前被取消的两个请求必定也会在 52 秒完成，也不能据此区分模型生成、排队、网络或思考耗时：当前非流式请求没有首 token 与服务端耗时分解。Planner enable_thinking 仍未显式传入，没有猜测服务端默认值。

仅这一次真实调用，没有模型参数试探、Prompt 改写或自动修复循环。没有修改应用代码、backend/.env 或当前运行服务；日常前台仍是原 30 秒时限，旧 Session 状态未改，因此前台不会因本次诊断自动恢复。

## 返回质量：技术通过，但有真实业务错误

返回一项 P0 任务，操作链 filter → group_aggregate(sum) → sort(desc) → top_n(3)。原 validate_draft 通过，原 PlanValidator 判为 F2、技术 coverage=complete。这里不等于业务正确或已批准。

只读核对真实 CSV（其 SHA256 与保存的 DatasetProfile 一致）发现：

| 字段 | 模型使用的等值筛选 | 文件实际值 | 风险 |
|---|---|---|---|
| 地区 | 华东地区 | 华东 | 等值筛选不命中 |
| 订单状态 | 已完成订单 | 已完成 | 等值筛选不命中 |

两条筛选各自命中数均为 0。若不修正就执行，会得到空数据；本次没有执行。错误不能通过延长超时解决。保留原模型输出，没有静默替换筛选值。现有技术 Validator 的 F2 未检查这类字面值与数据分布的匹配，不用它宣称语义质量验收通过。

初次只读元数据核对误用了 columns 键，产生 KeyError；实际画像用 fields。已按真实 Schema 重新核对，不改画像数据、不追加模型调用。该检查错误与模型结果无关。

## 追溯

- 原请求：request_4b0b7ef6fd574f9aa614df5e82d9c29c。
- 新 operation：diagnostic_timeout90_a5436200638f48eb8ffca762f130a3c4。
- 新 Call：call_c746e2d3f2264a5eaa00880cbfcd58ca。
- 新请求快照：request_5d6c6a80d9bf46e3990b177328474bca。
- 原模板：pt_00d2887d1cbeb11e82cba23892064ef53a8603d6c4286cdc8eca73701bb9a272。
- Payload 哈希：15e0a4f4de92c44c2fa6487939b5dfd9dab389a12708566a2b2f99accdce4d06，与原请求相同。

新请求和 CallRecord 通过既有 Registry 保存。run_id/span_id=null，明确表示独立诊断，不挂到旧终态 Span、不伪造工作流执行。原失败 Call/Span/需求记录不变。完整请求仍由 Registry 受控保存，未复制到公开文档；原始模型输出、技术校验结果、等值核对分别保存为 raw-model-output.txt、validated-plan.json、filter-value-check.json。

## 建议

后续可考虑为 Planner 单独设置更合理的等待预算，同时保留失败可见性；修改前需独立实施和验证，不能只扩大所有节点超时。另需单独处理已暴露的筛选值映射/验证问题，避免把自然语言“华东地区”“已完成订单”直接作为真实字段值。当前未改任何业务规则，也未声称这两个问题已修复。
