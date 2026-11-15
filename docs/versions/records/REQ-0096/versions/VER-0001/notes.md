# 数据概况优先报告 V1.3 — REQ-0096

## 结果与页面顺序

1. 标题、原始分析目标与数据来源。
2. 数据概况四卡：上传记录、本次纳入、关键字段完整记录、关键字段缺失记录。
3. 执行摘要；原业务 KPI 保留在“查看关键业务指标”展开区域。
4. 各分析方向：真实图表或表格、方向纳入记录、指标样本量、对应洞察、事实核对与证据。
5. 整体总结与下一步建议。总结使用已保存覆盖/报告状态，不重新生成业务断言；建议按原文精确去重。
6. 完整分析范围与统计口径。
7. 数据局限、未完成任务、来源与原始计算结果入口。

已匹配图表的洞察不在报告前面重复罗列；未绑定洞察保存在补充展开区域。历史 Presentation 的规则发现保留独立历史展开区。公开 AnalysisReport 内容不变。

## 数据来源与限制

上传数量来自保存报告。Engine 成功任务且 result_id 对应真实结果、执行日志存在时，effective_row_count 用于方向纳入数。单方向可展示总卡；多个方向即便数量相同也不认为范围相同、不累加，显示“分方向统计”。指标样本量沿用执行记录 valid_sample_count，不当作联合完整行数。

现有记录没有关键字段联合缺失的去重行集合，两张相关卡诚实显示“未统计”，没有将缺失单元格或逐列计数冒充缺失行数。要得到这两个数，需要后续明确关键字段、筛选范围及联合统计，并保存可追溯结果；本次未改 Engine 或读取原始文件重算。

Presentation 新增可选 dataset_overview，只有 DatasetProfile 的 dataset_id、dataset_version 和 row_count 与报告精确匹配才提供字段数、上传范围缺失单元格数和疑似重复记录数。该侧车字段默认为 null，兼容旧展示数据；不修改保存报告或原画像。展示版本枚举保持兼容，读取布局由本需求版本 V1.3 标识。

## 实际修改文件

- frontend/src/reporting/ReportPage.tsx：统一新布局、数据卡片、方向数量及洞察去重组织。
- frontend/src/reporting/report.css：四卡数据概况与窄屏两列响应式样式。
- frontend/src/types/report.ts：可选画像概况及已有执行元数据类型。
- frontend/src/tests/business-report.test.tsx、report.test.tsx：新顺序、单方向来源、多方向隔离、未知统计及交互验证。
- backend/app/domain/report_presentation.py：可选 DatasetOverview 展示契约。
- backend/app/reporting/presentation.py：精确版本画像事实的只读映射。
- backend/app/reporting/export.py：与页面一致的顺序、计数条件及洞察来源。
- backend/tests/test_report_presentation.py：画像关联、导出顺序和原有安全断言适配。

## 验证

- 完整后端：1587 passed，83.83 秒；保留已有 Starlette/httpx 弃用提示。
- 前端：75 passed；TypeScript 与 Vite 构建通过。
- 未修改 Admin，本轮未重复执行 Admin 测试。
- 浏览器验证原报告刷新正常；上传 60 行、12 字段，上传范围缺失单元格 0、疑似重复记录 0。四方向各纳入 60 条，指标样本量亦按记录展示。
- 真实 HTML 下载成功，六个主内容标题按顺序出现，质量说明与页面一致。
- overview.png、direction.png 为真实页面；browser-verification.json 保存不含密钥的核验结果。
- 未调用真实 LLM、未重新执行分析、未修改已保存报告。

## 失败记录与边界

旧测试对固定标题、卡片和前置发现列表的断言随新展示结构更新；首次失败日志保留。中间导出测试要求不绑定的洞察完全消失，与本次保留补充发现要求冲突，改为只检查该内容不能进入图表解读，未放宽证据匹配条件。

现有报告标题偏技术、部分百分比过长、解释泛化及同轴混合量纲问题仍保留，不宣称本次布局调整提高了模型洞察质量。整体总结为既有状态与适用范围说明，并非额外 LLM 综合结论。

本次需求先归档 REQ-0096，before.zip / after.zip 保存九个文件前后源码；旧需求、报告、Prompt 与评测未覆盖。
