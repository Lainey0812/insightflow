# InsightFlow Admin Trace V0.3 — 历史追溯与运行对比

关联需求 **REQ-0046**。审计与修改前源码：[开发前审计](audits/workflow-trace-v0.3/design.md)、[源码快照](audits/workflow-trace-v0.3/before-source.zip)。V0.1/V0.2 需求、失败记录、评测和业务数据继续保留。

## 使用入口

打开 http://127.0.0.1:5174/traces，勾选两次运行，点击“对比所选运行”。跨页选择保留在 URL；也可在 `/traces/compare` 输入两个 Run ID。`/versions` 提供追溯入口。对比 URL 带 `left`、`right`，刷新/重新打开后按 ID 读取，不依赖前端内存。

Run 详情底部有不可变 RunManifest，可展开查看 Git、Prompt、模型、版本和关键输入指纹。对比页显示状态、真实耗时、错误、节点对齐、拒绝规则、Evidence/候选/报告受控内容，并可跳回原始 Trace 和节点。

本轮浏览器与 API 验收沿用原 V0.2 的验证后端数据目录 `var/workflow-trace-v01-verification-02`。这是此前实际执行并调用 qwen 的合成测试数据；不声称是用户默认 `var` 的业务数据，也没有复制成第二套运行记录。

## 审计结论与真实来源

| 信息 | 历史 V0.1/V0.2 | V0.3 新运行 | 来源/限制 |
| --- | --- | --- | --- |
| Prompt/生成策略/报告 Schema | 已保存版本标识 | 保留并加 Prompt 内容 SHA | 运行时加载的静态模块版本，非供应商版本号 |
| Plan Validator/Registry | 已保存 | 继续保存 | 此次不可变审批快照中的版本 |
| 报告事实校验器 | 有源码 SHA | 加组合指纹 | fact_validation.py + claims.py，磁盘指纹不等于 Git Commit |
| 模型/timeout/thinking | 请求配置有记录，返回模型见 Event | 同时可看 Provider 返回的模型标识 | 当前 CompatibleLLMProvider 的返回元信息仍是请求模型标识，供应商实际解析的模型版本未采集；null 不作为供应商默认值；端点仅保留哈希 |
| temperature/top_p/Token 用量 | 未采集 | 仍为 unknown | 不擅自加入采样参数或伪造 Token 用量 |
| Git Commit/dirty | 未采集 | 在 Git 仓库中读取实际 HEAD/dirty | 当前项目没有 Git，因此 unknown；没有初始化仓库 |
| 数据/目标/Intent/审批/Execution 输入指纹 | 未采集 | SHA256 + 实际消费核验 Event | 精确比较，不做语义相似匹配 |
| 原始 LLM 文本 | 未保留 | 不保留全文，保存原文 SHA、长度、候选投影 | 无效 JSON 也记录原文 SHA；候选结构不可用时 parsed=false |
| Evidence/报告 | 成功报告可读取 | 运行时受控快照，报告仍在业务 Repository | 历史投影标记 immutable_saved_report_projection，未冒充当时快照 |

没有用当前配置回填历史 Manifest。API 对历史 JSON 增加可选字段的 null/空默认值，数据库原始记录不改写；UI 缺失版本明确标记 unknown。

## 最小契约扩展与存储

复用原 Run、Span、Event、Manifest、状态和 Repository，不新增平行 Run。

- 新 RunManifest `schema_version=workflow-trace-v0.3`；增加可选 `git`、`capture_scope`、`input_sha256`。默认旧版仍按 v0.1 读取。
- `input_sha256`：dataset（文件内容/数据版本/解析选项）、profile、user_goal、intent、approved_plan（完整审批快照）、execution（完整真实结果）。使用 canonical JSON SHA256，键排序、严格有限数值、保留原始字符串，不先改写原话。
- 入队时保存 Manifest；实际使用时重新计算六类指纹，写 `inputs.verified`。缺失或冲突核验不能判成同输入。审批/执行 ID 与时间等身份信息也参与相应对象哈希，因此同数值的新执行可能只判为部分可比较。
- Span 增加可选 `node_key`、`node_attempt`，旧记录为 null。新节点键包含祖先的节点重试序号，如 `parent#2/child`；Run 重试 `attempt/retry_of_run_id` 保持原含义。
- 同一 `observability/trace.sqlite3` 新增 `trace_snapshots` 表，Run+kind 唯一；内容不可变，外键校验 Run/Span 一致，单条最多 256 KiB。
- 快照种类：`evidence`、`llm_output`、`report`。只保留数值、引用、状态及自由文本哈希，不含原始记录、Prompt 文本、密钥、完整模型文本或任意本地路径。Evidence 投影最多 100 项并标记 truncated，原完整内容哈希单独保留。自由文本哈希不是加密或匿名保证，不用于公开发布。
- snapshot 写入与输入读取在原 fail-open 边界内；失败标记采集器降级和 Run incomplete，成功的计算/报告不受影响。保留策略沿用显式清理前保留，不自动删除旧档案。

历史成功报告投影必须同时匹配 Run.report_id、execution、dataset ID/version、plan version；不取 report_generations 中后一次重试的内容补前一次。失败 Run 没有保存的内容为 unknown。

## 可比性与节点对齐

逐项返回 `same` / `different` / `unknown` 和核验根据；关联引用、模型配置、版本、Git、源码差异分开显示。

- **comparable**：六类关键业务输入和报告生成 scope 经实际消费核验均一致，必要版本与请求配置已采集，双方无追踪缺口。只指本报告生成范围的输入可比，允许版本或模型不同并明确列出；不代表严格受控模型实验、结果质量更好或已建立因果关系。未采集的供应商采样默认值始终 unknown。
- **partially_comparable**：有部分指纹/关联依据，同时有差异或缺口。不同目标、数据、审批或执行结果不当作同输入复测。
- **unknown**：缺少足够的关键输入或关联依据。相同 Prompt/名称/行数不能独自证明输入一致。

新节点按 `(node_key,node_attempt)` 匹配。历史节点只在双方祖先 name 路径唯一时兼容对齐，并标记 `legacy_unique_path`，节点重试序号保持 unknown。重复名称、父节点重试歧义、缺失父节点、环和身份冲突保持未匹配。绝不按列表序号 zip 配对。

## API

沿用 `X-Admin-Token` 或同源短期 HttpOnly Cookie；缺凭证 403，未配置管理员凭证 503。所有新查询 `Cache-Control: no-store`，没有对比写入、版本修改或自动修复接口。

```text
GET /admin/comparison?left=<run_id>&right=<run_id>
GET /admin/runs/{run_id}/snapshots
```

同时支持 `/api/v1/admin/...`。旧四个 GET 接口保留。

comparison 响应含 `left/right` 原 Run、`comparability` 分项、`source_files`、对齐后的 `spans`、`artifacts` 和 `diagnostics`。两侧 ID 相同返回 422，不存在返回 404；存储不可读返回受控 503。运行中标记 live，允许手动刷新，不承诺跨多个存储读取的原子时间点。

```json
{
  "comparability": {"status":"partially_comparable"},
  "spans": [{"node_key":"fact_validator","node_attempt":null,"match_basis":"legacy_unique_path"}],
  "artifacts": {"left":{"llm_output":{"availability":"unknown"}}}
}
```

上例仅摘录结构；包含实际 ID、全部 Manifest/Span/规则/投影的三个真实响应见 [live-comparisons-01.json](audits/workflow-trace-v0.3/live-comparisons-01.json)。

## 真实历史验证

| 对比 | 实际结果 | 可比性判断 |
| --- | --- | --- |
| run_138b… vs run_8f390… | complete / partial；同样报告五阶段，成功节点仍不能把 partial 改成 complete | partially_comparable；历史关键输入指纹缺失，绑定与状态可读 |
| run_2a66… vs run_da8e… | 同 execution 的第 1、2 次报告尝试，均 failed，retry_of 保留 | partially_comparable；相同执行引用不补造输入核验 |
| run_c9c… vs run_138b… | failed / complete；失败的事实校验 Span、错误和候选拒绝规则可定位 | partially_comparable；不同引用与未知指纹分开列出 |

只读脚本逐个核对数据库原始 JSON 与 API 版本字段，并核对读取前后五条 Run 原始 JSON 的 SHA 完全一致。403 权限检查通过。本轮新增真实模型调用数为 **0**，没有把测试替身冒充真实模型采集。额外真实重试被自动审批拒绝后未执行，原因及替代验证见 [记录](audits/workflow-trace-v0.3/live-retry-not-executed.txt)。

浏览器已验证列表勾选、深层路由、失败/partial/规则、不可变报告投影、缺失 LLM 内容提示、刷新恢复；截图与记录见 [验收目录](audits/workflow-trace-v0.3/)。

## 自动化验证

最终命令与结果见验收日志：后端完整测试、Admin 测试/类型检查/构建、原 frontend 测试/构建均通过。专项覆盖：真实业务 Repository + 明确标注的 scripted Provider、六类输入差异、消费核验缺失/冲突、版本缺失、乱序和重试匹配、旧/新节点混合、重复祖先歧义、权限、快照不可变/越界、写入降级、重启读取和历史报告错绑拒绝。最终测试数量见 [版本记录](audits/workflow-trace-v0.3/version-notes.md)，早期失败日志未删除。

## 修改清单与边界

详见 [modified-files.json](audits/workflow-trace-v0.3/modified-files.json) 和 [修改差异](audits/workflow-trace-v0.3/code-diff.txt)。核心新增：observability/provenance.py、snapshots.py、comparison.py、TraceComparisonPage.tsx、后端/前端专项测试和只读复核脚本；扩展原 tracing 契约/Repository/Recorder/Admin API 及 Manifest/列表展示。ReportWorkflow/AnalysisReportService 只追加观察点，不调整业务决策。

Planner、Validator、HITL、Engine、Report Prompt/事实校验规则和主 Workflow 编排未修改。没有 Evaluation Center、Prompt 编辑、多 Agent 或新 LLM 节点。

仍有边界：只覆盖 Report Workflow；历史原文/输入指纹无法补回；Git 尚不存在；源码磁盘指纹不保证等同进程加载字节码；保存引用与哈希不等于防篡改备份；当前单进程恢复边界不扩展为分布式追踪；受控内容可诊断证据组合和拒绝规则，但不能逐字阅读或语义评测未保存的模型原文。
