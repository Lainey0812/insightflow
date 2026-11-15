# Prompt工作台 V1 交付

2026-11-15，REQ-0155 / prompt-workbench-v1。

## 页面与功能

入口 `/prompts`。左侧真实三个LLM节点（Intent Parser、Analysis Planner、Insight Generator）；右侧运行时版本卡片、编辑、调试 & Diff、历史版本、关联内容。白底、蓝色强调、独立节点目录与大编辑区；窄屏切为横向节点选择。当前运行时来源不能确认时显示unknown，不使用最新历史版本冒充当前版本。

- 编辑：默认载入当前运行时System Prompt；可以明确选择历史版本编辑。右下“调试此草稿”携带本页修改转到单独调试。未调试草稿只在内存，切换节点、版本或离开页面会丢失，界面已提示；运行后登记不可变快照。
- 固定User组合、重试、动态Schema生成与服务源码属于复合Prompt来源；本轮保持只读展示。调试User消息可单独编辑，或通过已有受控历史请求载入。**本轮并不支持在浏览器编辑动态Python组装逻辑或在线启用/发布版本。**
- 单独调试：测试名称、User输入、输出JSON Schema。使用已登记模板或编辑页System草稿，调用现有模型Provider；展示返回、JSON可解析性、模型、耗时与Call链接。前端等待255秒，后端每次受控超时不超过122秒；两侧串行，不增加自动重试或Agent节点。
- Diff调试：选择两个真实快照，查看保存片段的文本Diff；两个版本对同一输入和Schema分别调用，展示左右结果。快速连续切换版本时使用同步参数引用，避免URL更新相互覆盖。
- 历史版本：分页展示完整版本号、哈希、登记时间、Commit、变更说明和可展开System内容；User组合/完整来源仍可通过旧详情访问。调试草稿显式标记，不等于部署版本。旧目录移至 `/prompts/catalog`，旧版本、Diff、调用、Trace深链全部保留。
- 关联内容：支持当前页版本名称/哈希/ID搜索、版本筛选、测试记录分页、调用链接。新增调试用例与实际调用分开展示，普通生产调用不能冒充评测案例。**旧评测未记录精确快照归属时，本轮不自动补造关联；当前列表完整覆盖本工作台保存的调试记录，尚未打通所有历史评测目录的Prompt索引。**版本多于一页时用版本分页继续选择，搜索当前页有明确标签。

## 后端与存储

新增 `POST /admin/prompt-debug` 和 `GET /admin/prompts/{node}/versions/{snapshot_id}/tests`，沿用Admin认证、标注写入凭证及快照读取凭证。本地测试模式沿用既有loopback限制；凭证仅保留页面内存，不写URL或浏览器存储。

复用唯一PromptRegistry存储、LLMRequestSnapshot、LLMCallRecord、请求/响应捕获。System草稿以内容派生版本幂等登记，provenance新增兼容值 `admin_debug_draft`，原有默认不变，保留基准来源指针且source_commit为空，不冒充真实部署源码。原快照不可变，生产运行时模板绑定不变。

在同一Registry增加 `prompt_debug_cases` 调试测试元数据表，首次调试时幂等创建，UPDATE/DELETE不可变触发器保护。字段id、node_id、created_at、record；record保存test_id、case_name、输入/Schema哈希、精确模板和operation关联。调用状态与输出仍从现有Registry读取，不建立第二套LLM事实。GET没有记录时返回真实空状态，不创建该表。不修改原Registry迁移版本或已有不可变触发器。原业务库与Trace库不新增表。

每次真实模型请求独立Call ID，调试不绑定业务Run/Span，不触发Session、Planner流程、审批、Engine或报告生成，也不会替换线上System。相同内容重复调试复用同一模板但产生新的测试与Call；Diff一侧失败保留另一侧结果。失败前尚无HTTP调用时，历史关联显示unavailable，不能把无调用推断成功。

**调试结果是Provider协议与JSON语法结果，不执行各节点的业务后置校验器，也不提供Schema完整验证或业务质量评分。**界面与返回均提示此边界；不是生产流程回放或效果评测。本轮没有调整真实分析的业务算法、Prompt正文、模型参数。

## 真实浏览器与模型验证

使用无真实用户数据的合成测试，当前模型qwen3.8-flash：

1. 页面修改System为只返回ok=true；输入合成文本并指定简单Schema；真实返回 `{"ok":true}`，约1.68秒。test_id `pdt_30b22530df824d99aced83b3eee3206c`，call_id `call_0c807afe4ea24f9aa9f8c7680a928ba5`。
2. 第二个草稿返回ok=false，通过同一后端接口实测成功，未激活线上版本。
3. 浏览器选择两个已登记草稿，对完全相同User与Schema运行，左返回true约1.38秒，右返回false约3.06秒。test_id `pdt_cfbf4ce6f98340efb410c7aabf3a482e`；Call分别 `call_4223faed6fc54b31af664c142e5eed23`、`call_f33c36905c51431f850dd27d5b922d2d`。
4. 读取实际捕获的请求，断言两侧User消息和response_format逐项相等、Call均无业务run_id/span_id；原运行时Snapshot仍为 `pt_d1d10797a55a1c7…` 对应已登记版本。
5. 关联页选中true草稿可查2个实际测试与2条Call；刷新可重新读取。最后页面回到当前生产Prompt编辑页，未发布测试草稿。

证据：real-debug-evidence.json（仅本轮合成输入/输出），real-debug-second.json，editor-final.png、debug-diff-results.png、related-tests.png。真实连通性验证不代表模型业务质量改善。首次启动引用已不存在的旧/tmp脚本失败，随后新建启动脚本加载现有环境启动成功；未输出或归档.env与密钥。

## 验证结果与既有失败

- Admin TypeScript、构建通过；存在大于500KB构建块警告，未隐藏警告。
- 新工作台6例与旧Prompt14例：20 passed。覆盖当前/最新版本区分、编辑传递、显式调用、Diff、版本过滤、历史读取；旧目录用例随兼容目录路径迁移2处。
- 后端Prompt专项：52 passed，包括新功能7例。覆盖三个真实模板来源、请求捕获、草稿不可变、隔离、权限拒绝、跨节点/同版本/Schema拒绝、Diff一侧失败和数据库重读。
- 后端全量（参数化新增3例前）：1760 passed、1 failed；失败 `test_failure_diagnosis.py::test_success_has_no_failure_and_records_inputs_without_user_text`。使用修改前admin.py与domain契约的独立源码副本同样复现，属于已有诊断隐私测试失败；未在本轮改其业务行为或测试断言。
- Admin全量：262 passed、10 failed。10项涉及Trace/Comparison旧路由行为。独立副本恢复本轮修改前routes.tsx后同样复现这10项，见admin-before-traces.log，不将其算作本轮修复完成，也未为消除失败修改Trace。
- 原Frontend：102 passed，构建通过。

因此不能宣称“所有既有回归全绿”。本轮Prompt功能已通过专项与真实调用验证；既有11个失败应独立登记处理。本轮未给这些历史问题编造通过记录。

## 交付文件与保留

实际文件见changed-files.txt；before.zip、before-tests.zip保留前态，after.zip保留后态。测试失败日志、真实合成调试记录及所有旧版需求/评测/Prompt保留。后续建议：完整业务节点校验型调试、历史评测精确快照索引、持久草稿保存与显式发布契约，分别实施，不通过本次页面编辑自动改写线上加载机制。
