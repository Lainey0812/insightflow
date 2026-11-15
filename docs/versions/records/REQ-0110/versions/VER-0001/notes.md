# 前端到 Admin 最小打通 V1

日期：2026-11-09。需求：REQ-0110（确认 REQ-0109 建议的第一步）。

## 改动

- 后端：无改动。`GET /sessions/{id}` 的 response_model 为完整 SessionState，已返回 workflow_id。
- frontend/src/types/contracts.ts：Session 增加可选 `workflow_id`。
- frontend/src/config/admin.ts（新增）：读取 `VITE_ADMIN_URL`，默认 `http://127.0.0.1:5174`；只接受 http/https，非法值不显示链接。生成 `/traces/workflows/{encodeURIComponent(workflow_id)}`。
- frontend/src/vite-env.d.ts（新增）：声明 VITE_ADMIN_URL 类型。
- frontend/src/components/WorkflowProgress.tsx：“查看过程”面板底部显示运行编号与“在 Admin 中查看”（新标签页，rel=noopener noreferrer）。无 workflow_id 时不显示。
- frontend/src/chat-workspace.css：新增 `.workflow-admin-link` 样式。
- frontend/src/tests/admin-link.test.tsx（新增）：URL 构造、非法协议拒绝、有/无 workflow_id 的渲染。
- README.md：Admin 段落补充入口与 VITE_ADMIN_URL 说明。

修改前文件副本：docs/implementations/frontend-admin-link-v1-2026-11-09/before/。

## 验证

- frontend `npm test`：12 文件 100 passed（原 97 + 新 3）；`npm run build` 成功（含 tsc）。
- 浏览器打开链接目标 http://127.0.0.1:5174/traces/workflows/wf_c3781c6be06a4fbfa1428e36813a35e8，正确显示业务状态、关联 ID 与 16 节点时间线。

## 限制

- 未在真实浏览器中从用户前端点击该链接：5173 未运行，且已有会话受本地访问凭证限制；新建会话会写入真实库并可能调用模型，本轮未做。渲染与 href 由组件测试覆盖。
- Admin 若开启只读凭证，跳转后仍需按原方式授权；本轮未改权限。
- manual_review / legacy 会话无 workflow_id，不显示入口。
