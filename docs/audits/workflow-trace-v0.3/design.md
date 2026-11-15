# Trace V0.3 开发前审计与最小兼容方案

2026-10-28，关联 REQ-0046。修改前源码见 before-source.zip；历史 V0.1/V0.2 档案保留。

## 已有事实来源

- Run/Span/Event 存于既有 observability/trace.sqlite3；审批、执行结果、不可变报告在既有业务 SQLite。report_generations 是每个 execution 最新尝试，不能拿它补历史 Run。
- RunManifest 在 queue 时记录报告 Prompt（当前 report-insights-v1.1.9）、生成策略、审批快照的 Validator/Registry 版本、Provider/模型/timeout/thinking 和源码文件 SHA。后续写入禁止修改 Manifest。
- Prompt/策略/Schema 是运行时所用模块的静态版本标识；Validator/Registry 来自该次审批快照。模型配置是请求配置，llm.returned 保存 Provider 的返回元信息。当前 CompatibleLLMProvider.model 实际仍回传请求模型标识，不代表供应商实际解析的模型版本；必须区分，后者尚未采集。
- temperature/top_p/usage 为 null：未发送或未采集，不能当成默认采样值。Provider 目前并未显式发送 temperature/top_p；不补供应商默认值。
- 目录不是 Git 仓库，没有 commit；不初始化 Git。源码 SHA 是磁盘文件指纹，不保证等同于热修改前已加载的 Python 字节码。
- Span 有 name/parent，无稳定身份和节点重试序号；Run 级 attempt/retry_of 已真实保存。
- 只保存候选数量、证据引用、拒绝规则；没有原始 LLM 响应快照。成功报告含真实 Evidence/Insights；失败前产生的证据没有单独快照，不能从执行结果重建并冒充当时保存。

## 文件变更计划

- domain/tracing.py：可选 Git/输入指纹及受控快照契约；Span 可选 node_key/node_attempt，默认 null 保留历史 unknown。
- observability/provenance.py、snapshots.py、comparison.py：确定性采集、白名单快照、可比性与按身份对齐。无 LLM。
- storage/trace_repository.py：同一 sidecar 增加不可变受控快照表，非第二套 Run；读取 Run Events。
- observability/recorder.py：现有 fail-open 边界内采集，旧 Manifest 不更新。
- workflow/reporting.py、services/analysis_report.py：仅追加输入读取回调及观察点，不改变业务决策。
- api/admin.py：复用权限的只读 snapshots/comparison API。
- admin：Manifest/列表两次运行选择/独立 comparison URL/对比页面、类型、样式、测试。
- 新增后端自动化测试与交付文档，原接口兼容。

## 受控内容与比较范围

Manifest 只保存 dataset/profile、精确用户目标、Intent、审批计划、完整 ExecutionResult 的 SHA 与绑定。哈希不等于脱敏或防篡改；不提供任意文件路径读取。审批 ID 和执行 ID 不同即使数值相同也不当作相同审批/执行。

新增快照保留 Evidence 的数值与来源引用、LLM 候选证据组合/类型/自由文本 SHA、报告状态/洞察引用与文字 SHA，不保留原始数据、自由文本或完整原始 LLM 响应。所有文本单元仅哈希，不靠不完整的正则脱敏。受控快照与原始输出哈希区别标识；管理员凭证沿用，不扩展普通会话权限。成功历史报告只按 Run.report_id 与 execution/dataset/plan 绑定读取不可变报告投影，标注其来源，绝不回填 Manifest；失败历史内容 unknown。

comparable 要求关键输入（dataset、profile、goal、intent、approved plan、execution）指纹相同、明确 scope、完整采集与版本/模型信息；模型和版本差异单独展示，结论仅针对本报告生成范围的输入一致性，不表示因果归因。已知不同或部分同一且不全可验证 -> partially_comparable；没有足够内容或绑定证据 -> unknown。每项明确 same/different/unknown 与根据。

Span 新节点使用祖先语义路径 node_key + node_attempt；Run 重试次数单独显示。历史仅对无歧义的祖先 name 路径做显式标注的兼容匹配，重复/孤儿/环不按列表顺序配对，返回 unmatched。

## 验证

先单元/集成（历史缺字段、输入差异、不可变、Span 乱序/重试/歧义、权限、降级、重启、快照边界），再 Admin 组件/类型/构建与完整后端回归。浏览器使用已保存真实 qwen 报告 Run；不新建 LLM 节点，也不声称比较证明某个 Prompt 的效果。
