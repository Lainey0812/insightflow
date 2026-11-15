# HITL V2 实施设计（编码前冻结）

现有 Validator 校验类型/能力/顺序，不证明自然语言约束；approve_v1 对所有非空约束统一拒绝。Engine 已有 constraints_confirmed 闸门，并核验不可变审批记录，无需改动执行契约。

新增独立 review/constraint_audit.py 确定性、保守的有限语法映射。逐条保留 Intent 约束路径与原文，解析后绑定真实字段、具体 task/step/参数；验证执行任务的范围条件均在聚合前，指标来自真实聚合，排序与截取发生在聚合后。所有实际执行任务继承全局筛选；未声明的附加筛选/截取、字段歧义、未知表达、未支持转换、defer 等保留阻断。绝不修改 Intent 原文或 validation_status，不猜测任意中文语义。

审批事务仍重新校验原 PlanVersion；以同一审计器替换“非空即拒绝”谓词，仅全部证明通过才设置原有 constraints_confirmed。不可变审计证明以 approval_id 为键旁存，绑定 session/dataset/plan/validation/registry/内容摘要。原审批输入、版本、幂等、告警确认、快照结构与 Engine 不变。GET review 计算展示/资格，不写批准。客户端不可提交审计结果或布尔值授权。

新增 domain/review_presentation.py 与 review/presentation.py，将真实业务字段、步骤、验证结果映射为 ViewModel。新增 GET /sessions/{id}/review；返回服务端资格、风险与条件审计。默认目标→范围口径→分析方向→待确认→操作；技术原文、枚举、字段 ID/摘要/步骤放 details。无额外 LLM、无未经计算的结论、无报告承诺。未实现的修订提供重新提出需求入口。

前端 PlanReviewCard 真实分支改为新组件，按会话/版本/revision 获取 ViewModel；加载失败、过期或版本不匹配时拒绝批准，历史只读。批准仍调用原接口，任务删除仍生成不可变版本并重验。保留旧 Mock 卡片，仅历史隔离使用。

测试：四领域元数据与真实上传/内核集成；时间/值/指标/维度/排序/Top N/排除/禁止；同名字段、错误值/字段/方向/口径、附加筛选、步骤提前截断、辅助任务漏筛选、未识别语言、F0/F1/defer、删任务及版本变化、刷新、权限、伪造与幂等；原回归。浏览器使用四领域合成 CSV 和真实现有模型，保存计划/审计/批准/结果与截图。有限语法未覆盖的自然表达作为 Bad Case，不临时放宽评分。
