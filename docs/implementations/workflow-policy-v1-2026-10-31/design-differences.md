# Phase 03-B1 契约差异与暂停范围

REQ-0080；冻结源：REQ-0079/VER-0001。原契约不修改。

## D01 — C19 accepted=True 的时序冲突（阻断）

冻结 `contract-tables.json` 的 C19：source=generating，target=completed，guard 包含“合法证据、覆盖与有效当前分支；accepted=True”，required evidence 为“报告+归属+generation.report_id同事务”。README第3.3/9节同时要求真正业务提交后才可成功观测。

当前 `backend/app/storage/report_repository.py:65` 的 `ReportRepository.finish` 在事务内插入报告并更改generation，退出事务后才返回True。`backend/app/workflow/reporting.py:28` 的 `generate` 获取accepted后才调用Trace成功结束。

作为“接纳提交命令”的纯前置校验，C19不能以尚未发生的成功提交为前置事实；作为提交后校验，又不再处于规定的generating前态。用可由调用者提供的布尔值冒充提交证据会破坏安全性。其他命令的required evidence可表达预定事务效果，但C19把已提交accepted=True也明确写在guard，不能静默重新分类。

处理：暂停C19的允许实现。目录中保留C19映射，任何C19请求均明确deny/POLICY_CONTRACT_CONFLICT，不因为候选报告合法而放行。其余31条可独立实现，不扩展Trace状态。

待评审建议（本轮不执行）：区分提交前资格与提交后accepted确认；由新契约明确两个时点的owner/事实及责任，再追加新版本。不能覆盖V1.1，也不能伪造receipt。

## D02 — 幂等记录与命令键的存储尚未定义（非新契约冲突）

冻结第8.4节已明确未来Writer决定持久位置。本轮使用纯领域输入的既有命令记录，不创建表/Repository。allow只是当前快照的资格判断，不构成幂等预约或数据库锁。旧revision重复请求只可命中同载荷完成记录，输出read-only replay且无转换；进行中不重新allow。

## D03 — Legacy适用域（兼容边界）

native_v1.1与legacy_session_v1显式分离。Policy不为legacy发新原生许可，返回POLICY_LEGACY_DELEGATED；现有Session服务未导入本模块，继续按原逻辑运行。不能把该返回值描述为旧API已收紧。

## 本轮验收影响

只能交付31条目标允许实现及C19安全拒绝。测试中必须区分31/32正向覆盖与32/32映射覆盖；不宣称32条全部验收通过。Phase 03-B2须先评审D01并追加契约决议，当前不建议进入。
