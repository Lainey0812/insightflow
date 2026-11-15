# 本机免登录功能测试（REQ-0054）

按用户要求，在当前 backend/.env 启用 INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE=true，后端重启后生效。原管理员凭证保留但测试模式无需输入；公开默认配置仍为 false。

## 改动

- config.py：显式本机测试开关，默认关闭，非法配置报错。
- admin.py / main.py：把开关传入原 Admin router，复用现有数据源与接口；本机测试绕过凭证输入，不建立账号或替代存储。包括受控完整请求读取。
- local_admin_access.py：检查实际客户端连接、Host、Origin 和浏览器跨站标志，不从转发头推断本机身份。
- .env.example / admin/README.md：说明开关、启动时导入配置、回切鉴权方法和本地使用边界。
- test_admin_local_access.py：13 个测试结果，覆盖本机免凭证、分页接口、刷新无 Cookie、IPv4/IPv6、远程连接、Host、跨站 Origin、转发头伪造、完整请求及关闭开关后的鉴权。

未修改前端源码、Prompt、Planner、HITL、Engine 或报告业务逻辑。私密配置没有纳入快照。

## 验证

- 专项及既有 Trace/Registry 集成测试：83 passed。
- 后端全量：783 passed，1 条原有 Starlette TestClient 弃用提示，日志见 backend-tests.txt。
- 当前真实 Admin 5174 经代理无需凭证返回列表；过滤 intent_parser 后返回 1 个节点，实际历史快照为 0。
- 浏览器现有页面刷新后无登录框，显示真实节点与历史空状态，截图见 prompt-list-local-access.jpg。
- 跨站 Origin 与不合法 Host 返回 403，详见 api-verification.json。
- 前端源码未改，未重复运行前端构建。未调用真实 LLM，未填充假历史。

## 使用及限制

直接访问 http://127.0.0.1:5174/prompts。当前只有本机可访问的开发服务，完整请求可能含用户原文，仅供本机本人测试。不要把免登录模式通过公网隧道或反向代理开放给其他人。仅靠请求头不构成部署隔离；必须保持前后端监听本机地址。后续设置 INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE=false 并重启即恢复既有鉴权。

本轮历史保存包含需求原文、修改前后源码快照、测试结果和页面截图；旧档案均保留。
