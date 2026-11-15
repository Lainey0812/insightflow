# Report Module 针对性审计记录（2026-10-28）

审计进行中用户追加了业务报告结构改造。本文件保留已实际复现的发现；后续实施的展示层不等于这些问题已全部修复。未改动 Planner、Validator、HITL 和 Engine。

离线复现脚本：`reproduce.py`；结果及被检查版本的源文件 SHA：`reproduction-results.json`。使用隔离临时数据库、受控模型返回及真实计算内核，不代表真实模型错误率，也没有改动用户会话。

| 级别 | 发现 | 复现依据与影响 |
| --- | --- | --- |
| P1 | 自由解释校验有漏报 | 仅含销售额证据时，“济南利润高于南京”“销售额源自当地促销补贴”“The profit share is ninety percent.”均被 materialize 接受。正则不是语义证明器；加“可能意味着”不能替代证据。位置：`reporting/fact_validation.py:65` |
| P1 | 原报告排名/图表固定降序 | 真实 top_n asc 输出上海10、南京20、济南30；Evidence 却给济南降序第1，ChartSpec 固定 value_desc。位置：`reporting/evidence.py:67`、`visualization.py:23`。新业务展示仅对明确的降序操作链生成排名叙述，升序回退一般报告，但旧图表方向问题未修复 |
| P2 | 已确认约束未完整进入洞察上下文 | 内部隔离批准快照含“不要分析利润”，原始查询亦含该边界；report LLM payload 没有原始查询或结构化 constraints，确认后相关 limitation 也被移除。位置：`services/analysis_report.py:99`。此复现直接构造服务端测试快照，不是生产批准或鉴权绕过 |
| P2 | 合法警示误拦截 | “销售额不能证明盈利能力”“两个分组值得继续比较”被当作未验证事实拒绝；会引起不必要的报告失败。位置：`reporting/fact_validation.py:59` |
| P2 | 常规报告重试不保留完整历史 | 第1次失败 error/时间在 queue 第2次后被覆盖，Session 也只留1条当前记录。位置：`storage/report_repository.py:49`。完整模型输入输出记录目前来自验收包装脚本，常规 Provider 没有等价持久化审计 |
| P2 | 大整数派生值被 float 舍入 | 源结果 9007199254740993，原 Evidence 返回合计 9007199254740992.0。位置：`reporting/evidence.py:150`。新业务视图用 Decimal 格式化/派生，不修改已保存的原报告证据；原 Evidence Builder 的边界问题仍在 |

确认保留的能力：真实结果来自执行时批准快照；报告失败不改 Engine 状态；真实报告读取受会话凭证约束；无证据不调用 LLM；成功任务/失败任务分开披露；Top N 不自动推断总体占比。导入报告 API 仍是公开兼容边界，不应把 imported 来源当作服务端 Engine 复算。

建议后续单独修复 P1：显式传递原始目标与所有已确认边界，统一数值/排名与原批准排序方向，补充自由解释的正反例评测；不要通过更多随意关键词替换伪造事实校验成功。本次新增展示层仅对有明确支持的数据形态生成可追溯的确定性叙述，不扩大 Engine 能力，也不把审计反例写入线上报告。
