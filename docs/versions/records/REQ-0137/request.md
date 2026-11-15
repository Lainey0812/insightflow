下一步我们进入 InsightFlow 需求保真评测。

重点验证：用户原始需求中的目标和约束，能否经过 Intent Parser、Analysis Planner、Plan Validator，最终准确落实到 Analysis Engine。
因为如果用户说「排除实习岗位」，最终 Engine 却没有执行这个条件，那么即使计划版本完全一致、计算完全正确、报告完全可追溯，业务结果依然是错误的。
