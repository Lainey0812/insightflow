# 模型等待上限调整为 60 秒

依据 REQ-0061，将 backend/.env 的 INSIGHTFLOW_LLM_TIMEOUT_SECONDS 从 30 改为 60；其余环境变量原样保留。不复制 .env 或密钥进入档案，不修改源码、Prompt、thinking、模型和业务规则。

沿用现有共享配置，因此 Provider、Intent Parser、Analysis Planner、Insight Generator 的等待上限均为 60 秒，并非新建 Planner 专属设置。重启前核对没有活动业务准备阶段或模型调用；重启后直接从实际 app.state 服务实例读取，四项均为 60。原后台任务、计划、数据及历史记录不清理。

后端和两个前端健康访问结果另存 health-verification.json，运行实例配置验证保存 runtime-verification.json。不为本次可逆配置修改额外发送模型请求；此前 90 秒诊断和原超时记录保留。扩展等待预算不修复已发现的筛选值语义错误，也不保证每次模型调用都在一分钟内返回。
