# Bad Case 回放（REQ-0118）

## 修改依据

REQ-0118：用户回复“继续”。REQ-0116 已把 Bad Case 回放放到回归对比之后。本版本按当时说明实现：用保存时的引用回到日常库读取原会话和上传文件，以当前代码和 Prompt 再跑一遍，并与保存时的错误代码或需关注项比较。

## 实现

- `backend/scripts/run_bad_case_replay.py`：真实模型，默认只跑待确认和已确认；`--cases` 可指定编号。每次新建 `var/replay/runs/rp_日期_随机/`，不覆盖旧结果。计划可审批时由回放运行器代为批准。
- 原会话和上传文件以 SQLite `mode=ro` 与普通文件读取。会话不在、文件不在或内容哈希已变，记为 `source_missing`，不发明输入。已修复、不处理、误报默认 `not_run`。
- 自动结果只比较保存时的错误代码，或当时标记为需关注的质量信号是否再次出现。标注人写的期望结果原样展示，不判通过或未通过。
- 落盘结果不含用户原文、文件字节和结果表。回放产生的 workflow 编号属于独立库。
- Admin：`/bad-cases/replays` 与 `/bad-cases/replays/{run_id}` 只读。没有启动接口，`POST /replay-runs` 返回 405。原来的 workflow 编号可以打开；这次回放产生的编号只显示文字。

## 验证

- `tests/test_bad_case_replay.py` 4 项：判定规则；缺会话、文件被改、已修复默认不跑；用受控模型完整回放一次，日常库哈希不变，结果不含原问题中的“取前三名”和源数据数字；列表与详情只读，不存在的编号 404。
- 后端全量 1670 项通过。1 项失败仍是沙箱限制 `test_trace_comparison.py::test_git_unknown_without_repo_and_actual_commit_when_available`。
- Admin：类型检查通过；vitest 17 个文件、110 项通过；`npm run build` 通过。
- 浏览器：临时目录放入一次虚构回放，本机测试模式启动临时后端（8013）和 Admin（5184）。列表显示“未再出现 1/1”，详情显示期望文字、原 workflow 链接和独立库编号纯文本。临时服务已停止，临时目录已删除，原 `var/` 未写入。截图见 `screenshots/`。

本版本没有用真实模型回放现有 Bad Case。运行命令见 README。

## 修改前副本

`before/` 保存修改前的 9 个文件。
