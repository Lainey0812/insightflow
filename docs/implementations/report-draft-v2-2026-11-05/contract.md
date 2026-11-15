# Report Draft V2：实施前冻结契约

需求 REQ-0092，2026-11-05。采用上轮已提出的职责隔离方案，不改变公开 AnalysisReport、Insight、ChartSpec、审批或 Engine 契约。

内部模型输出仅包含 insights；每项必填：primary_evidence_id、evidence_refs、finding_type、recommendation_id、limitation_refs。没有自由 implication、recommendation 或 limitations 字符串，额外字段拒绝。

证据 ID 必须来自实际选用池，主证据必须在引用中，同任务/结果/指标/范围兼容；数值、排名、比例和操作数仍逐项核对真实 ExecutionResult。受控 finding_type 必须与主证据类型兼容，重复发现拒绝，P0 覆盖要求保持。

建议选项由服务端从真实画像与当前指标组生成，包含受控类型、task_id、data_ref、result_field、field_ids。模型只能选择 option_id；服务端再次核验来源与字段类型。支持查看来源记录、比较真实字段分布、核查已有缺失；none 表示没有额外建议，不强行凑建议。字段合法不等于业务价值已通过，需保留人工/执行者评测。

局限以 Lxxx 引用服务端已验证语句。引用缺失或错误拒绝；不让模型复算缺失数或增加市场/因果判断。输出文字由通过校验的结构生成，不在展示层另造发现，不用规则替换非法模型选择，也不以模板伪造模型调用成功。

公开 Insight 的 fact/finding 使用既有确定性组合；implication 表达该发现的适用范围和未验证原因边界；recommendation 使用实际字段名称表达受控后续方向，明确尚未执行、需另行规划和确认。Report 不创建 AnalysisTask、不执行建议、不增加新 LLM 节点。

LLM 失败、旧格式返回、非法引用、核心覆盖不足继续返回明确失败/部分状态，不自动降为旧生成契约。旧 materialize 函数仅供旧版记录/测试回放；生产新调用显式走 V2。

保留此前冻结 CSV、Gold、评分规则与失败记录。先完成安全单测与全量兼容验证，再在同24例上真实回归，并新增四类数据的独立表达组。分别统计系统交付、数值事实、业务相关性、建议相关性和可读性；不以 Schema 合法率单独宣称产品通过。真实目标用户复核仍单列待开展。
