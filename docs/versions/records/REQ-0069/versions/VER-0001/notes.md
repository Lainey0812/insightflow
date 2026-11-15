# InsightFlow 双栏聊天工作台 V1

关联需求：REQ-0069；继续执行与沟通偏好：REQ-0070。实施日期：2026-10-30。

## 页面与交互

桌面左侧展示真实咨询历史，右侧展示当前咨询消息、计划审核和执行结果。欢迎页保留文件上传、表头行参数、目标驱动与探索模式。当前步骤位于对话顶部，不随长消息滚动消失。窄屏使用历史抽屉，支持 Escape 关闭、焦点返回和抽屉内键盘焦点约束；打开抽屉时对话区域设为 inert，切回桌面时自动关闭抽屉。

使用 frontend-design 的设计流程，方案见 design-plan.md。白色对话区、浅灰绿色历史区、深绿主操作；样式限定在 chat-shell，不改 Admin 与独立报告页。

## 运行锁定与状态来源

presentation.ts 只读取 Session 和报告生成记录。CREATED、PREPARING、PROFILING、PARSING_INTENT、PLANNING、VALIDATING、RUNNING，以及审批记录 executing/validating，均视为运行中。当前已批准版本对应的最新服务端已接受 Execution 仍有 queued/generating 报告时，也保持锁定。未批准新版本不会继承旧执行的报告状态。

运行期间禁用输入、文件选择、拖放、发送、新建分析及历史切换；事件处理器也检查锁定条件。actionPending 在 React 更新前阻止重复提交。澄清状态恢复输入；审核和完成状态保留只读输入区与新咨询入口。本轮没有增加自由追问或自然语言改计划能力。

步骤文案来自保存的业务状态，不伪造 Span、百分比或节点完成证据。原审批资格和错误提示保留，未解决约束仍阻止批准。报告生成中与 Engine 完成分开展示；报告完成不等于业务目标完全覆盖。

## 修改文件

- App.tsx：布局、运行锁定、PREPARING 轮询、重复请求防护、报告异步回调防止覆盖已切换咨询、响应式抽屉状态。
- SessionSidebar.tsx：真实历史、运行提示、键盘与焦点管理。
- Welcome.tsx：简洁引导和建议入口。
- MessageComposer.tsx：统一对话输入区、上传参数、锁定事件防护。
- MessageList.tsx：对话呈现、真实请求等待提示、减少动画偏好。
- WorkflowProgress.tsx：简化当前步骤及可展开过程、真实失败信息。
- chat-workspace.css：独立作用域布局和响应式样式。
- workflow/presentation.ts：纯展示状态映射。
- tests/chat-workspace.test.tsx：新增 15 项测试。
- tests/report-workflow.test.tsx：修正已完成执行测试夹具缺失批准版本的问题。

完整路径与哈希见 source-diff.json、source-before.json、source-after.json。前后源码 ZIP 均保留。哈希对比确认 backend/app、backend/tests 和 admin/src 未修改；没有删除源文件。

## 验证结果

- 最终前端测试：9 个文件、67 项通过，见 tests-release.txt。
- TypeScript 与 Vite 构建通过，见 build-release.txt。
- 后端回归：837 项通过，1 个 warning，见 backend-regression.txt。
- tests-first.txt 保留首次 51/52 通过的失败记录：旧报告轮询夹具没有设置批准版本。随后修正夹具，使其符合真实执行前提，未放宽生产关联规则。
- 浏览器桌面 1280×900：双栏、欢迎输入、真实历史消息与计划内嵌呈现正常。
- 浏览器窄屏 390×844：侧栏默认隐藏、抽屉打开后背景不可操作、Escape 关闭并返回焦点、打开抽屉后切回桌面恢复主区域。
- 真实历史咨询刷新后恢复同一计划；未解决“总订单数”约束时批准按钮仍禁用。真实 Planner 超时咨询保留失败信息与原重试入口。
- 浏览器检查仅读取已有咨询，没有上传文件、批准或删除任务，没有新增模型调用。运行锁定和澄清恢复由自动化测试覆盖；本轮未另发起新的真实 LLM 端到端分析。
- 临时浏览器尺寸已恢复。

截图：desktop-welcome.jpg、desktop-conversation.jpg、mobile-history.jpg。

## 边界

仅实现当前浏览器工作台的交互锁定，不提供跨标签页或跨设备的后端并发互斥。没有调整 Prompt、模型参数、审批规则或计算算法。历史 Mock 咨询仍按原记录保留，不将其作为真实分析验证证据。原有 Planner 超时不在本次 UI 改版范围内。

本地页面：http://127.0.0.1:5173/。需求与版本档案持续保留，不代表已经提交 Git 或完成远程备份。
