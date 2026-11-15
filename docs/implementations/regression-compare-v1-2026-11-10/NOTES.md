# Admin 回归对比页（REQ-0117）

## 修改依据

REQ-0117：用户回复“继续”。REQ-0116 已确认回归运行方式，运行器与只读列表接口已存在。本版本补上两次运行的对比，以及 Admin 页面。

## 实现

- `RegressionRunService.compare(left, right)`：按用例比较两侧状态。右侧比左侧更好记为 improved，更差记为 regressed，相同记为 unchanged；blocked 与 needs_review 同级，不同则 changed；任一侧不是自动判定记为 not_compared；缺一侧记为 only_one。检查项状态不同的一并列出。
- `GET /api/v1/admin/regression-compare?left=&right=`，沿用管理员只读鉴权。页面不能启动回归，也没有写入接口。
- Admin：`/evaluations/regressions` 列出 `var/regression/runs` 并对比两次运行；`/evaluations/regressions/{run_id}` 显示每个用例的判定、失败检查和独立库中的 workflow 编号。该编号不是链接，因为它不在日常 Workflow 列表。评测中心因此变为可用，其余评测入口仍是占位。

## 验证

- 后端 `tests/test_regression.py`：对比把通过变为未通过记为 regressed，并带上检查项差异；不存在的运行返回 404。全量 1666 项通过，1 项失败为已知沙箱限制 `test_trace_comparison.py::test_git_unknown_without_repo_and_actual_commit_when_available`。
- Admin：类型检查通过；vitest 16 个文件、107 项通过（新增 `regression.test.tsx` 3 项；导航与横幅文案按新范围更新，原文件在 `before/`）；`npm run build` 通过。
- 浏览器：临时目录放入两次虚构运行，本机测试模式启动临时后端（8013）和 Admin（5184）。对比页显示 TC01 从通过变为未通过，详情页显示“运行器代为批准”，workflow 编号为纯文本。临时服务已停止，临时目录已删除，原 `var/` 未写入。截图见 `screenshots/`。

本版本没有用真实模型跑 TC01–TC12。运行命令见 README。

## 修改前副本

`before/` 保存修改前的 12 个文件。
