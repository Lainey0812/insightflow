# Report Draft V2 实施说明

需求 REQ-0092。基于 REQ-0091 的失败归因，替换内部生成契约，不修改公开 AnalysisReport / Insight / ChartSpec，不修改 Planner、Validator、HITL、Engine、Workflow 状态权威或 Admin 页面。

## 职责边界

原 V1 Draft 要求模型写 implication/recommendation/limitations。关键词边界检测难以证明自由解释真实，也曾误拦截合法否定句。V2 不声称通过更复杂自然语言规则解决该问题；模型负责选择已验证证据和未来核查方向。它不能自行写事实、业务解释、建议正文或新统计数字。

内部 SelectedInsight 必填 primary_evidence_id、evidence_refs、finding_type、recommendation_id、limitation_refs，额外字段拒绝。生产服务显式使用 InsightSelection 和动态 ID enum Schema。旧版自由文本返回为 REPORT_LLM_INVALID_OUTPUT，不透明转换、不调用第二个模型，也不回退旧生成逻辑。

公开 Insight 仍保留 fact/finding/implication/recommendation/limitations。事实从实际 ExecutionResult 校验操作数后由既有 claims.compose / fact_details 生成；implication 是与发现类别对应的受控适用性说明，而非已验证的深层业务原因。未来建议由真实字段、类型和任务/结果/指标绑定的服务端目录渲染；none 是显式不推荐，不强行凑建议。数据字段真实和类型兼容不自动证明建议有业务价值。

## 校验与错误处理

保留同指标、同任务、同结果和同统计范围兼容校验。不同指标可以作为独立 Insight 并列，不开放未经验证的跨指标派生。每条引用必须唯一、存在且包含主证据；主类型必须兼容，重复发现拒绝。真实值、排名、比例、分子/分母、结果行引用继续验证。未覆盖 P0 任务继续失败；核心指标覆盖不足继续明确部分报告。部分合法候选可以保留，但公开状态为 partial，并保存拒绝详情。

实现期间发现全拒绝错误详情引用自身导致 JSON 循环；已以独立 details 副本修复，专项测试检查错误可持久化。没有吞掉非法内容或将失败包装成 complete。

建议支持 review_source_rows、compare_distribution、check_missingness。服务端从当前真实画像创建选项，不从模型自由文本提取字段。重新渲染前核验 task_id、data_ref、result_field、field_ids 和类型；不信任 description 缓存。已能解析的禁止字段从目录排除；无法解析的分析边界不授权新增无关字段方向。此有限约束语法不是通用语义授权器，未解决用户约束仍依赖原规划与审批规则。

## 历史与可观测性

旧 materialize、InsightDraft 和 request_schema_v1 留给历史测试/回放，新生成路径不使用。Presentation 明确兼容 evidence-composition-v1.2.3，继续展示历史保存的洞察，不按当前配置改写旧报告。V2 页面与 HTML 使用同一保存来源。

Prompt Registry 将 V2 Schema、建议目录组合与新模块来源纳入模板登记。真实调用仍记录实际消息、动态 Schema、配置和模型返回。Trace 的只读脱敏投影能区分旧 Draft 与 V2 选择输出；这只影响观察，不构成旧格式的业务接受。无新增节点、重试循环、Trace 层级或 Attempt 实体。

## 安全和能力限制

V2 保证的是受控数据表达和来源绑定，不是自然语言深层业务推理能力。字段名和类别是源数据，不应被视为指令；HTML 继续沿用现有转义。用户/Planner 的目标文字及源字段可能仍不友好，现有公开 Schema 的 interpretations_unverified 标记保留。没有声称正则完成语义事实验证，也没有宣称达到专业分析师水平。
