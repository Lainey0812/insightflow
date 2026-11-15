# Admin Trace V0.3 实施与验证记录

关联用户需求 REQ-0046；这份文档是实施说明，不是新用户任务书或用户验收确认。

## 实现

复用既有 Trace sidecar 与 Run/Span/Event/Manifest、只读访问 Cookie 和业务 Repository。Manifest 为新运行追加 Git、精确输入指纹、Prompt/事实校验器指纹、模型端点哈希；输入使用时独立核验。新增受控快照仅保留数值、引用和文本哈希，不留完整业务原文。旧 Manifest 原始 JSON 不改写。

对比 API 和页面支持 URL 两侧 Run ID、可比性逐项检查、稳定节点身份与节点内重试对齐、旧唯一父子路径兼容、状态/耗时/错误/拒绝规则、已保存内容投影与原始 Trace 跳转。没有新建 Run 来源、编辑 Prompt、自动修复或模型节点。

Planner、Validator、HITL、Engine、Report Prompt 与事实校验规则未修改。ReportWorkflow 与 AnalysisReportService 只有观察点变化。详细文件清单和差异见 modified-files.json / code-diff.txt，最终代码见 admin-trace-v0.3-source.zip。

## 最终验证

- 后端全量 **726 passed**，1 个现有 Starlette/httpx 弃用警告；backend-full-03.txt。
- 新增比较专项 **22 passed**；comparison-tests-02.txt。
- Admin **38 passed**（原 31 + 新 7）；admin-tests-04.txt。
- Admin TypeScript 检查 + Vite 构建通过；admin-build-06.txt。
- 原业务 frontend **52 passed**；frontend-tests-01.txt。
- 原业务 frontend TypeScript + 构建通过；frontend-build-01.txt。
- 浏览器真实历史 Run 验证：选择两条记录、完整/部分/失败分开、规则可读、历史保存报告投影与未知 LLM 内容、刷新恢复、最终服务重启后恢复。browser-checks.json、browser-after-restart.txt 和 JPG 截图。
- 本机只读 API / SQLite 两轮核对：三组真实历史运行，5 条原 Run JSON SHA 读取前后全部一致；无权限比较返回 403；live-comparisons-01.json / 02.json。新增模型调用 **0**，旧模型来源为实际 qwen3.8-flash，早期 upstream 为明确标注的合成测试 fixture。
- 新运行采集链路的独立 controlled transport 示例见 controlled-runtime-example.json，明确不是实际模型返回，未计入真实 LLM 验收。

早期错误同样保留：Admin 旧文案断言失败、移除未使用导入前的类型检查失败日志均未删除。曾提出额外真实模型重试，被自动审批拒绝后没有执行、没有绕过；改为历史记录只读验证，见 live-retry-not-executed.txt。

## 剩余边界

- 当前项目无 Git 历史，commit=unknown；没有擅自初始化 Git。
- 历史输入指纹与未保存的候选原文不能补回。快照不是逐字全文差异工具；自由文本仅比较哈希，不以哈希变化判断语义质量。
- 当前兼容 Provider 返回的 model 是请求模型标识；供应商实际解析的模型版本/Token/默认采样参数未采集。
- comparable 只指业务输入与 scope 可验证一致，不代表严格控制了供应商采样条件，也不建立 Prompt 改动与结果的因果关系。
- 同数值但不同身份元数据的审批/执行对象会得到不同精确哈希，保守返回部分可比较。
- 仅覆盖报告生成节点；其他业务节点埋点、Evaluation Center、Prompt 编辑不在本轮。
- 单进程恢复边界沿用既有实现；进行中读取不保证多个表/业务 DB 原子快照；单快照 256 KiB，Evidence 展示上限100项，截断显式标记。

验收建议：框架、历史数据追溯、只读运行对比与回归检查可供用户测试；不以这些测试结果宣称模型洞察质量提升。需求与所有旧版继续保留。
