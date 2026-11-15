# 业务报告展示 V1

2026-10-28，按用户指定结构改造现有报告预览和可选 HTML 导出：

1. INSIGHTFLOW / 业务分析报告，实际分析标题与范围副标题。
2. 执行摘要，重点指标卡。
3. 核心发现与业务解读。
4. 建议进一步分析。
5. 数据说明。

图表、完整表格、证据、统计口径、原始 ExecutionResult 与版本仍可展开查看。失败任务及部分覆盖提示保留可见，不用“已完成报告”掩盖目标缺口。

## 数据映射

新增 `ReportPresentation` 为只读展示模型，不替代 AnalysisReport，也不改变其已保存 JSON。`reporting/presentation.py` 从保存的 `result_data`、任务操作链、执行元数据及指定版本 DatasetProfile 确定性映射；不调用 LLM，不重新执行计算。旧报告同样可使用新结构，原报告 ID 和执行 ID 不变。

API：`GET /api/v1/reports/{report_id}/presentation`，沿用报告会话鉴权。下载接口继续由用户主动点击，使用同一展示映射导出 HTML。展示接口不可用时，页面保留原报告预览作为兼容降级。

单一成功核心任务、单维度、单个可加指标（sum/count）、明确降序 Top N、完整返回表、无并列时，生成具体的排名比较叙述。多核心任务、升序、平均值、截断、缺失分组或并列时使用一般报告内容，不强行套用城市销售故事。Top N 超过10时也使用一般内容，避免把大量类别拼入摘要。

所有新数值证据使用 V 开头的 ID，绑定原 task_id、data_ref、result_field 与来源结果行。仅在展示模型中增加，保留原 E 开头的证据。金额保留源数值精度，百分比用 Decimal 计算，四舍五入到一位小数；分母非正不显示比例，含负值不计算构成比例。

当前销售报告的三个分母明确为：

- 领先第二名：`(21250 - 20250) / 20250 × 100 = 4.9%`。
- 上海相对济南：`5760 / 21250 × 100 = 27.1%`。
- 前两名占比：`(21250 + 20250) / (21250 + 20250 + 5760) × 100 = 87.8%`，只占前三名合计。

标题中的 2026、华东、已完成来自真实操作参数和字段名称；不是对用户文字做硬编码。建议中的订单数量、平均订单金额、产品类别结构仅在画像有相应字段时出现，并明确尚未执行。没有为“接近”“明显”设置隐藏的统计阈值；正文使用实际差额/比例描述，不宣称已检验统计显著性或因果关系。

## 改动文件

新增：`backend/app/domain/report_presentation.py`、`backend/app/reporting/presentation.py`、`backend/tests/test_report_presentation.py`、`frontend/src/tests/business-report.test.tsx`、两份前端销售报告测试快照。

修改：`backend/app/api/reports.py`、`backend/app/reporting/export.py`、`frontend/src/api/client.ts`、`frontend/src/types/report.ts`、`frontend/src/reporting/ReportPage.tsx`、`frontend/src/reporting/report.css`。没有改动已保存报告、LLM Prompt、审批或执行规则。

## 验证

当前报告 ID：`report_9bc9b4b0184f4d3084ede0fb806230d3`。浏览器已核对标题、三张指标卡、三个发现、分母说明、60/16样本口径；展开图表后切换表格仍是济南21250、南京20250、上海5760。预览没有触发下载或模型调用，HTML 导出通过后端接口与内容测试，没有再次触发浏览器文件下载。

截图、模型、测试与构建记录见 [展示验收目录](evaluations/report-business-v1)。此前已复现的审计问题另见 [审计记录](audits/report-module-2026-10-28/README.md)，本次结构调整不意味着自由文本语义校验已全部修复。
