# Prompt Registry V1 — phase1 audit and proposed contract

需求 REQ-0048；本记录为审计交付，不是 Registry 已实现或用户已确认的声明。

完成三个真实 LLM 节点的 Prompt 加载、User JSON 组装、动态 Schema、配置与 Trace 审计。对实际目录和源码 ZIP 静态解析，确认 13 个具名 System 全文版本与一个无版本标识的 Planner baseline；报告 v1.1.7 与 v1.1.9 System 文本相同，Planner v1.1/v1.2 有真实差异。

拟定 PromptVersion 契约和受控来源、内容不可变规则、版本关联可信度/实际调用状态、API/UI 路由和测试计划。推荐 user_template 可 null、User 组装源码单独引用，缺失的历史 Schema/Git 不补当前值。created_at 定义为登记时间，避免伪造原始版本创建时间。

审计源码 ZIP/SHA、内容库存、只读 Trace 观察、公开配置白名单、两个真实静态 Diff 与 audit-checks.json 全部保留。本次未修改应用源码、数据库、LLM 配置或 Prompt；没有调用真实模型，没有声称 API/UI 测试已通过。

按用户要求停在第一阶段，等待确认后再进入实现。详见 audit-and-contract.md 与 PromptVersion.proposal.schema.json。
