# Planner V1：实现审查与调用前冻结设计

2026-10-27，Asia/Shanghai。仅独立Planner，不接线主Workflow，不调用Engine。

## 已有能力及接口

已有AnalysisPlannerService.plan(intent, profile)、POST /api/v1/plans/generate、CapabilityRegistry、严格输出Schema与PlanValidator。当前画像使用fields[].field_id / display_name / logical_type / physical_type；没有semantic_tags，不编造。Provider与Intent Parser共用，模型沿用qwen3.8-flash。

已有AnalysisTask比示例多requirement_ids、missing_inputs，AnalysisPlan多core_requirements，ValidatedAnalysisPlan含intent_snapshot。直接复用，无下游契约变更。返回是ValidatedAnalysisPlan包裹AnalysisPlan，批准和执行仍独立。

## 修改文件与顺序

1. app/planning/prompt.py：版本planner-v1.1、删除测试、四种语义状态、显式约束步骤映射、真实六类能力边界、核心任务保留。
2. app/planning/context.py：有界元数据与现有核心需求列表，按四类登记已知约束；不传样本行，不改变数据。
3. app/planning/output.py：严格JSON/Schema，模型传输层等价非空正则兼容；唯一ID/参数/无P0的错误分类。
4. services/analysis_planner.py：一次总超时、有限格式重试、脱敏错误、单次Validator，F0不修复不删除；保留intent_snapshot。
5. config.py/main.py/.env.example：仅为Planner增加独立思考参数与尝试次数配置，不改变Workflow接线。
6. app/planning/evaluation.py、scripts/evaluate_planner.py、evaluation/planner_cases_v1.json：真实调用与独立评测。
7. tests/test_planner_v1_live_contract.py及已有Planner测试的错误码适配，文档。

## 契约与风险

领域Schema、Registry参数Schema、Validator、Engine、HITL、Report、Intent代码均不改。模型传输Schema将非空正则从search式的\\S改为完整匹配兼容的等价式，不改变合法业务对象范围。

core_requirements中的C01为业务目标，后续为明确决策及四类约束；P0任务需关联相应需求，未满足部分用missing_inputs。max10限制仍保持，不建立新字段。所有defer/annotate原样保存在intent_snapshot，未宣布已解决。

Validator.complete是技术引用覆盖，无法证明LLM在语义上覆盖目标或正确保留每个约束；不得用它作为业务验收。未经核实的constraints仍unverified，当前真实HITL按原规则不能直接批准这些条件，不在本轮绕过该限制。

## 冻结评测

25个案例，其中24个应生成计划，1个clarify应服务端拒绝且零模型调用。四主题各6条；明确、探索、多指标、多重过滤、绝对时间、相对时间未确认、排除、禁止、非必选、未定统计口径、缺字段、薪资文本、技能派生、P0/F0、受控时间派生均覆盖。

基于人工可读的代理参考标签构造IntentResult，**不是实际Intent Parser调用**，不把上游正确性算入Planner成绩。使用真实Data Profiler解析明确标记的合成CSV，LLM只接收字段元数据及质量摘要，不传记录。

评分planner-reference-v1在真实调用前冻结。检测必需指标/函数、分组、每个核心任务的筛选、绝对年份、聚合后Top N、禁止字段/口径、未请求指标、任务数量、重复、技术覆盖及F0保留。只接受预先列出的明确等价，如eq与单值in、ne与单值not_in、年份派生后筛选与ISO日期半开区间。相对日期无基准需保留未确认阻断项。

该评分不证明全部解释性语义；业务价值与P0删除测试需逐例人工审阅。用sum比较未指定口径可能是合理待审批方案，参考未匹配与真实语义错误分别复核，但不改冻结分数。失败请求留在完整请求分母，约束检查仅对实际返回计划计算，同时单列未能评估数量，禁止隐藏失败。

5个固定案例各重复3次，规范化生成ID与别名后比较任务数量、优先级、操作/参数；忽略标题措辞差异，不能忽略字段或执行逻辑变化。主25条和重复15条分别报告。

## 模型配置与验收

复用本地已授权模型配置，qwen3.8-flash，Planner enable_thinking=false，总超时30秒，最多2次尝试，采样参数省略（服务商默认）。不改模型、不加节点、无LLM裁判、无Validator自动修复。记录每次实际模型正文、合法计划、Validator结果、Bad Case及稳定性。

100%有效Schema、≥95%显式约束继承是目标而非成绩。优先排查未报告核心约束遗漏、虚构字段、禁令违反；真实结果及P0逐例人工确认前不声称语义验收完成。原实现与脚本已归档baseline/，保护模块哈希记录在protected-modules.json。
