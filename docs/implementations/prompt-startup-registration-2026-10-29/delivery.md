# 当前 Prompt 页面为空：原因与修复（REQ-0055）

## 根因

三个服务在实例化时通过 TemplateSource 校验并绑定了实际完整模板，但旧实现只在 CallRecorder.begin 发起真实模型调用时（或报告追踪路径）登记快照。只读查询没有写入副作用，因而未运行新分析时，当前模板虽已加载却未落库。不是 Prompt 文件内容为空，也不是权限问题。

## 最小修复

新增 services/prompt_registration.py，在原 FastAPI 启动生命周期完成存储恢复后登记当前已配置 HTTP Provider 对应的三个服务模板。再次检查 source.build 与服务绑定 hash 相同，复用原 repository.register 的哈希、版本冲突和幂等规则。没有第二套存储，没有改 Prompt、模型配置、输出 Schema 或节点业务逻辑。

登记失败按节点记录受控错误代码并保留真实 not_registered 状态；不改版本号、不覆盖冲突历史、不伪造成功。实际模型调用边界原有的模板验证与保存检查继续执行；注册失败不会通过 Mock 掩盖。

模板登记与实际模型调用分离：启动登记不生成 LLMCallRecord、LLMRequestSnapshot、Run 或 Span。未配置 HTTP Provider 的服务不制造当前模板绑定；未留存旧版不从当前内容重建。

## 真实实例验证

三个节点各有 1 个不可变登记快照：

- Intent Parser：intent-v1.3.3+composition-v0.1。
- Analysis Planner：planner-v1.2+composition-v0.1。
- Insight Generator：report-insights-v1.1.9+composition-v0.1（现用代码版本号，不表示新增质量验收）。

实际本地 SQLite 为 var/prompt_registry/registry.sqlite3，prompt_templates=3，llm_calls=0，llm_request_snapshots=0。静态模板 API 快照分别保存为 *-current-snapshot.json；无 API Key、用户上传数据或最终动态请求。

浏览器当前 Intent Parser 历史页已显示 1 个已绑定且登记的版本；点击查看版本可显示实际 System、User 组合、重试指令及来源定义。截图 intent-history.jpg 和 intent-version-detail.jpg。旧版缺失并未填补。

## 验证

- 专项及既有快照/权限测试：62 passed。
- 后端全量：788 passed，1 条现有 TestClient 弃用提示。
- 新增测试覆盖三个节点启动登记、当前模板内容一致、无模型调用、重复启动保留原快照时间与内容、并发幂等、冲突不覆盖、来源不符拒绝、存储缺失与未配置模型。
- 前端源码未修改，未重复构建。真实模型调用数为 0；不据此宣称模型业务质量改善。

## 边界

本轮只使当前真实模板可查看，不恢复历史部署、不补造 Trace、调用和旧版本。Git Commit 仍 unknown，因为工作区无 Git 仓库。只保存模板不能代表发生过模型调用，也不能代表该 Prompt 已通过业务质量验收。
