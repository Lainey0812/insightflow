# InsightFlow

InsightFlow 是一个面向普通业务人员的 AI 数据分析项目。用户上传 Excel / CSV、用自然语言描述问题、确认分析方向后，系统执行计算并生成可预览、可下载的分析报告。

项目包含两个独立前端，共用一个 Python 后端：

| 系统 | 使用人群 | 主要用途 | 本地地址 |
| --- | --- | --- | --- |
| **InsightFlow 数据分析工作台** | 运营、销售、人力资源等业务人员 | 上传数据、描述问题、审核计划、查看分析报告 | http://127.0.0.1:5173 |
| **InsightFlow Admin 管理台** | 开发与测试人员 | 跟踪运行、定位问题、管理 Prompt、维护测试用例 | http://127.0.0.1:5174 |
| **共享后端 API** | 两个前端共用 | 数据解析、模型调用、审批、计算、报告及持久化 | http://127.0.0.1:8000/docs |

> 当前是本地开发与测试版本。已有真实分析主链路，但不代表所有数据场景都已通过业务质量验收。

## 两个系统分别做什么

### 1. 数据分析工作台

采用左侧历史会话、右侧聊天的布局，主要流程为：

**上传文件与提出问题 → 数据画像与意图理解 → 分析规划与校验 → 人工确认（HITL）→ 确定性计算 → 分析报告。**

- 支持单个 CSV / XLSX 文件和单个工作表，可指定表头行。
- 支持明确目标分析与探索式分析；必要时向用户澄清。
- 在聊天中展示分析方向，支持现有计划修订、删除和重新校验；未批准不能执行。
- 执行筛选、分组聚合、整体聚合、排序、Top N 和已支持的日期派生。
- 报告展示真实指标、图表、解读、证据与局限；在线预览，下载由用户自行选择。
- 保存会话、计划版本、审批、执行结果与报告，支持刷新后查询恢复。

LLM 负责理解、规划及证据范围内的解释；统计结果由受控代码计算。系统没有使用 LangChain / LangGraph，也不允许模型执行任意 Python 或 SQL。

### 2. Admin 管理台

用于观察和诊断前台真实分析任务，不是另一个分析入口。

- **运行追踪**：按 Workflow 查询实际节点、状态、耗时、异常、执行及报告关联；缺失采集明确展示。
- **Prompt 管理**：查看三个 LLM 节点的模板及历史快照，编辑草稿、单次调试、Diff 调试和关联调用。编辑草稿不会直接发布。
- **Bad Case**：记录问题、修改归因、进入对应 Prompt 修复页面，提交修复后进入待验证。
- **评测记录**：查看已保存的测试数据集、评测运行与回归对比。
- **黄金集管理**：当前版本冻结只读；Draft 支持增删改、保存并确认发布下一版；旧版本保留。Case 详情包含测试输入、预期行为和评测规则。

未开放的菜单置灰。页面不伪造运行或评测数据。黄金集管理的新版本尚未自动接入旧版固定五例评测器；新环境也不会自带本机历史数据库记录。

## 技术栈与目录

- 前端：React、TypeScript、Vite；业务图表使用 ECharts，Admin 使用 React Router。
- 后端：Python、FastAPI、Pydantic。
- 计算与存储：Pandas、OpenPyXL、SQLite、本地文件。
- 模型：OpenAI-compatible Provider，当前项目使用 qwen3.8-flash，凭证在本地配置。

```text
insightflow/
├── frontend/       # 数据分析工作台，端口 5173
├── admin/          # Admin 管理台，端口 5174
├── backend/        # 共享 FastAPI 后端，端口 8000
├── examples/       # 示例数据
├── docs/           # 设计、实施、测试与版本档案
└── var/            # 本地运行数据，首次运行时创建，不提交 Git
```

## 首次安装

需要 Python **3.11+**、Node.js **22.12+** 和 npm。两个前端独立安装依赖。

```bash
git clone https://github.com/Lainey0812/insightflow.git
cd insightflow

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e './backend[dev]'

npm --prefix frontend ci
npm --prefix admin ci
```

以上激活命令适用于 macOS / Linux。Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活虚拟环境。

### 配置后端

首次运行时，复制模板；已有配置不要覆盖：

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，填写自己的模型配置：

```dotenv
INSIGHTFLOW_LLM_BASE_URL=https://your-provider.example/v1
INSIGHTFLOW_LLM_MODEL=qwen3.8-flash
INSIGHTFLOW_LLM_API_KEY=your-api-key
INSIGHTFLOW_LLM_TIMEOUT_SECONDS=60
INSIGHTFLOW_INTENT_ENABLE_THINKING=false
INSIGHTFLOW_PLANNER_ENABLE_THINKING=false
```

Base URL 必须匹配实际供应商的 OpenAI-compatible 接口，并支持项目要求的结构化输出。未配置模型时，真实分析会明确失败，不会自动用 Mock 结果替代。

本机测试 Admin，可在同一文件中设置：

```dotenv
INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE=true
```

该模式仅用于本机测试。后端和两个前端保持绑定 `127.0.0.1`，不要通过公网、隧道或共享代理暴露。共享部署应关闭此模式，并配置服务端读取、快照和标注凭证；详情见 [Admin 说明](admin/README.md)。

`.env` 不提交 Git。任何 `VITE_` 变量都会进入浏览器，禁止放入模型密钥或服务端凭证。

## 日常启动

**同时使用两个系统时，需要三个终端。两个系统共用同一个后端，只需启动一次。** 以下命令均从项目根目录开始。

### 终端一：共享后端

```bash
source .venv/bin/activate
cd backend
set -a
source .env
set +a
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

后端读取进程环境变量，**仅创建 `.env` 不会自动加载**；上面的 `source` 步骤用于加载自己的本地配置。配置变更后重新加载环境并重启后端。

- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/v1/health

### 终端二：InsightFlow 数据分析工作台

```bash
cd frontend
npm run dev
```

打开 **http://127.0.0.1:5173**。上传文件、输入问题，审核计划后开始分析。

### 终端三：Admin 管理台

```bash
cd admin
npm run dev
```

打开 **http://127.0.0.1:5174/traces/workflows**。

常用页面：

| 页面 | 地址 |
| --- | --- |
| Workflow 运行追踪 | http://127.0.0.1:5174/traces/workflows |
| Prompt 管理 | http://127.0.0.1:5174/prompts |
| Bad Case | http://127.0.0.1:5174/bad-cases |
| 当前黄金集版本 | http://127.0.0.1:5174/evaluations/golden |
| Draft 黄金集 | http://127.0.0.1:5174/evaluations/golden/draft |

两个 Vite 服务默认将 `/api` 代理到 `127.0.0.1:8000`。只启动其中一个前端也可以，但真实数据功能仍需后端。退出服务使用对应终端的 `Ctrl+C`；端口占用时先检查已有进程，不要重复启动。

Admin 的端口和 API 代理可通过 `admin/.env.example` 对照配置到 `admin/.env.local`，与后端 `.env` 分开。

## 测试与构建

从项目根目录执行：

```bash
# 后端自动化测试
(cd backend && ../.venv/bin/python -m pytest)

# 数据分析工作台
npm --prefix frontend test
npm --prefix frontend run build

# Admin 管理台
npm --prefix admin test
npm --prefix admin run typecheck
npm --prefix admin run build
```

前端构建产物分别位于 `frontend/dist/` 和 `admin/dist/`。这些命令不会替代真实模型与浏览器端到端验收；历史测试结果及已知失败保存在 `docs/`，不能将构建成功视为业务质量验收通过。

## 数据与版本记录

- 业务数据、上传文件、Trace、模型调用快照等默认保存在项目 `var/`，可通过 `INSIGHTFLOW_DATA_DIR` 指定位置。
- 本地运行数据库、真实密钥、上传文件、依赖和构建产物均不上传 GitHub。克隆仓库不会恢复这些本机运行数据。
- 需求原文、源码 / Prompt 快照、评测及失败记录持续保留。旧版不删除、不覆盖，变更追加记录。
- 早期需求档案是本地历史记录，不等于过去每一版都拥有 Git Commit。

更多资料：[需求与版本索引](docs/versions/INDEX.md) · [档案规则](docs/versions/README.md) · [工作流说明](docs/workflow-v1.md) · [报告模块](docs/report-module.md) · [数据画像](docs/data-profiler.md) · [Admin 说明](admin/README.md)。
