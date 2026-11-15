# requirement-fidelity-v1

REQ-0137。新增需求保真评分，检查冻结义务是否经过意图、规划结果、批准计划和引擎执行。不改意图解析、规划、校验和执行的业务判定。回归原有通过/失败结论也不改，保真结果另记在 `fidelity`。

修改前的回归运行器副本在本目录 `before/runner.py`。

四段独立判断。约束只写在业务目标正文时，意图段记 `prose_only`。规划结果有、批准计划没有，记 `dropped_after_planning`。引擎结果仍含被排除取值，记 `excluded_value_in_result`，不因为计划版本一致而通过。`不排除` 和 `只看` 不算排除。

本版冻结义务只有典型套件 TC02。年份、地区、订单状态的引擎段只证明对应步骤跑过，不重算数字。排除城市同时核对已保存结果里不得出现被排除取值，且应保留的分组仍在。TC03–TC15 尚未列入。

真实模型运行 `rg_20261112-133157_f04289` 只跑 TC02。原回归 3/3 通过，3 次模型调用。保真 4/4 通过：`year_2026`、`include_region`、`include_status` 为 `step_ran`，`exclude_city` 为 `effect_checked`。运行器在计划可审批时代为批准，记录在该次回归结果中。

验证：`tests/test_requirement_fidelity.py` 8 项通过，`tests/test_regression.py` 通过。单测覆盖排除条件分别在意图、规划、校验、引擎丢失。
