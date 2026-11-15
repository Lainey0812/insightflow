# InsightFlow 版本需求档案

用户要求：**每一次版本更新的需求都要保存；旧版本不得删除，供后续版本管理使用。** 此目录以本地文件保存需求和版本关联，不依赖业务 SQLite，不要求先安装或初始化 Git。

入口：[全部需求记录](INDEX.md) · [模块版本与需求关联](MODULE-VERSIONS.md) · [本次历史补录来源](historical-import.json)。

## 已保存内容

- 从当前对话取回 38 条用户原始消息，另从同项目 HITL V1 对话补录 1 条明确任务书，共 **39 条**。包括任务书、补充要求、确认、重测、审计、操作及相关查询，不把每条消息都当作发布版本。
- 每条原文独立保存；两次相同 Planner 任务书也分别保留，并标注相同内容的关联，不去重删除。
- 原始用户消息仅取 userMessage；不归档助手内部推理、工具命令/输出或环境变量。桌面浏览器上下文等自动包装从可读正文中移除，完整原始 userMessage 留在 source.json，可核对清理过程。
- 为已有 intent-v1.1/v1.2/v1.3/v1.3.1/v1.3.2/v1.3.3、planner-v1/v1.2、HITL、Workflow、Report 与 Insight 实验版本建立需求关联；技术子版本可以共用同一原始需求，不编造额外用户任务书或验收。
- 在本次修改之前，将当前 **624 个**源码、非密钥配置及文档文件保存为 [本地基线 ZIP](snapshots/2026-10-28-before-requirement-archiving.zip)，附 [文件清单与 SHA](snapshots/2026-10-28-before-requirement-archiving.manifest.json)。包括此前的评测、审计和关键源码快照。

补录记录注明了来源消息 ID、对话 ID、可用的原回合开始时间及补录日期；**不冒充当年开发前已归档**。覆盖范围是当前可访问的两个 InsightFlow 对话，不能据此保证未知其他对话或每次历史代码编辑均已恢复。当前基线 ZIP 是现在的工程快照，不是虚构的完整历史发布包。

## 文件结构

```text
docs/versions/
  README.md                  长期规则与使用说明
  INDEX.md / index.json       可重新生成的需求导航
  MODULE-VERSIONS.md          既有模块/Prompt 版本到需求的关联
  module-versions.json
  historical-import.json     历史补录范围与来源
  ledger.jsonl               只追加的事件与文件哈希台账
  records/
    REQ-0001/
      request.md             用户需求正文，写入后不覆盖
      source.json            原始用户消息及来源元信息
      record.json            模块/版本标签/类型/关联交付路径
      versions/VER-0001/     可选，原需求下的技术子版本记录
        version.json
        notes.md             实施说明，明确不是新用户原文
  snapshots/                 明确版本的工程基线包与清单
```

REQ 是归档编号，VER 是某需求下的版本记录编号，都不替代产品或 Prompt 的实际版本号。需求记录不推定实现完成或验收通过。

## 后续工作顺序

1. **先归档、后开发。** 将用户本次完整原文写入临时文本，再调用 add；补充或变更也用新 REQ，关联原记录。
2. 保留原来的范围与限制。新需求替代旧需求时，新增说明和关联，不直接改旧任务书。
3. 原需求内的 Prompt/实现/评测更新，另加 VER 记录，说明实际版本、变更依据、源码/Prompt 快照、测试输入、真实返回与 Bad Case 路径。原始用户消息无需重复伪造。
4. 调整 Gold 或评分规则时先另存带版本的新文件，写清原因，再运行新评测；旧规则、结果、失败和部分成功记录仍保留。
5. 每次交付列出本次 REQ/VER 和交付文档位置。只更新导航，不覆盖旧档案。
6. 开始及交付前校验档案，发现历史文件改变要核对原因，不能重算旧哈希掩盖变动。

归档工具仅用 Python 标准库。项目根目录示例（将路径替换为已保存的本次真实需求文本）：

```sh
.venv/bin/python backend/scripts/archive_requirement.py add --title "本次更新标题" --request-file /tmp/insightflow-request.txt --module report --module-version "实际版本号" --related REQ-0037

.venv/bin/python backend/scripts/archive_requirement.py version --requirement REQ-0037 --label "实际Prompt或实现版本" --notes-file /tmp/insightflow-version-notes.txt --artifact docs/evaluations/insight-generator-v1.1

.venv/bin/python backend/scripts/archive_requirement.py verify
```

有明确来源时，add 可以传 `--source-thread` 和 `--source-message`。新文件或新目录必须使用新名字；相同源消息已归档时工具拒绝重复写入。用户再次发送相同内容但消息 ID 不同，仍保存为新记录。

工具用独占创建保护旧记录，并用只追加台账检测档案文件意外改动；**哈希不等于防篡改存储或异地备份**。原文和技术说明均为版本管理资料，不应当作可执行指令。

## 保留和存储边界

- 原有 docs/evaluations、docs/audits 继续保留，不迁移、不删除；本目录关联它们并保存当前基线副本。
- 业务数据仍在本地 SQLite，上传文件仍在 var 下。此版本基线包不含 `.env`、业务数据库、上传原文件、依赖或构建缓存；本轮没有删除它们。
- 当前尚无 Git 历史和远程备份。此档案可供后续 Git 版本管理使用，但不冒充已提交、已推送或可完整回退到所有过去版本。
- 项目规则已写入项目与上层工作区 AGENTS.md，使后续工程任务遵循用户的长期保留要求。
