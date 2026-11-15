# Data Profiler · 确定性数据画像 1.1

本模块处理一个 CSV / XLSX 文件、一个工作表，产生经过 Pydantic 校验并保存到 SQLite 的 `DatasetProfile`。无需 LLM / Agent Runtime。不修改源文件、不填充空值、不去重、不计算 Excel 公式、不产生业务分析任务或报告。

## 模块与接口

```text
独立 HTTP API ─────────────────┐
                              ├→ DataProfilerService → FileStore.read（完整性检查）
Orchestrator → DataProfilerNode┘                      → profiling.build_profile
                                                     → DatasetRepository

profiling: parsers.py → type_inference.py / profiler.py → domain 契约
```

`profiling.build_profile(content, extension, dataset_id, file_name, options)` 是不含网络、数据库或模型调用的纯计算入口。相同字节、解析选项、数据集 ID 和文件名产生完全相同的 JSON；画像不加入当前时间或随机值。节点沿用已有 `NodeInput / NodeOutput / WorkflowError` 协议。

| 方法 | API | 行为 |
| --- | --- | --- |
| POST | `/api/v1/datasets` | multipart 上传并返回真实画像（201）；不调用 Planner、Engine 或 Report |
| POST | `/api/v1/datasets/{dataset_id}/profiles` | JSON 解析选项，对同一已保存源文件重算（200） |
| GET | `/api/v1/datasets/{dataset_id}/versions/{dataset_version}/profile` | 从存储读取并校验指定版本画像 |
| GET | `/api/v1/sessions/{session_id}/profile` | 读取会话 `dataset_ref` 指向的真实画像；旧 Mock 会话返回 409 |

上传参数：

| 参数 | 默认值 | 规则 |
| --- | --- | --- |
| `file` | 必填 | 单个 CSV / XLSX，非空且 ≤ 10 MB |
| `header_row` | `1` | 指定表头位置，取值 1–100001 的整数；XLSX 是工作表行号，CSV 是逻辑记录序号 |
| `sheet_name` | 不指定 | 单 Sheet 自动选择；多 Sheet 必须显式选择一个，绝不默认合并或选择第一张 |
| `encoding` | `utf-8-sig` | CSV 支持 UTF-8（含 BOM）；可显式指定 `gb18030`，不猜测编码 |
| `delimiter` | `,` | CSV 可指定逗号、分号、制表符或竖线，不猜测分隔符 |

XLSX 不使用 CSV 编码和分隔符，传入非默认 CSV 选项会报错。CSV 不允许指定工作表。会话创建 `/api/v1/sessions` 也接受这些解析参数，但后续规划及报告仍为 Mock。

例如，在后端服务启动后运行（项目根目录）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/datasets \
  -F 'file=@examples/sales.csv'
```

多 Sheet XLSX：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/datasets \
  -F 'file=@/absolute/path/data.xlsx' \
  -F 'sheet_name=销售明细' \
  -F 'header_row=6'
```

重算同一已保存工作簿时，将响应中的 `dataset_id` 填入路径：

```http
POST /api/v1/datasets/{dataset_id}/profiles
Content-Type: application/json

{"sheet_name":"销售明细","header_row":6}
```

## DatasetProfile 与身份

完整 JSON Schema 见 [dataset-profile.schema.json](dataset-profile.schema.json)，也可在 FastAPI `/docs` 查看。示例 [dataset-profile.example.json](dataset-profile.example.json) 由 `examples/sales.csv` 的实际文件字节计算，示例 ID 仅用于文档，不是数据库中的资源。

| 字段 | 定义 |
| --- | --- |
| `dataset_id` | 上传文件生成的不可猜测 ID；每次重新上传是独立数据集 |
| `dataset_version` | 原始文件 SHA-256 + 格式 + 已解析的有效选项 + `table-v2` 解析契约的规范 JSON 哈希 |
| `content_sha256` | 原始文件字节 SHA-256，不做重写或内容标准化 |
| `schema_version / profiler_version` | 输出契约版本 / 计算实现版本 |
| `sheet_name / available_sheets / options` | 已选择工作表、可用工作表及实际使用的解析选项 |
| `row_count / column_count / total_cell_count` | 不含表头的数据行数、字段数、两者乘积 |
| `missing_cell_count / missing_cell_rate` | 所有字段缺失数之和；缺失率分母为数据单元格总数 |
| `duplicate_row_count / duplicate_row_rate` | 完全重复行数（不计首次出现）及其占数据行数的比例 |
| `fields` | 按原始列顺序排列的字段画像 |
| `quality_issues` | 质量问题代码、严重程度、数量、字段引用及最多 5 个示例记录序号 |
| `provenance` | 固定 `source=uploaded`，数据集 ID 和版本必须与画像一致 |

`field_id` 按 1 起始列位置生成，例如 `field_0001`。它不依赖列名、字段值、类型或随机数：重算、同位置更名和数值变化不影响 ID，重复列名也不会冲突。字段引用使用 **`dataset_id + dataset_version + field_id`**。重排列后 ID 对应新的位置，不提供跨重排的语义身份追踪。

同一文件自动选择唯一 Sheet 与显式指定该 Sheet 的版本相同；默认表头与显式指定 `header_row=1` 的版本相同。切换表头行、Sheet、编码或分隔符会产生不同版本。原始字节变化（包括重新保存工作簿导致的字节变化）也会改变版本。源文件不允许原地替换：重算前检查字节数及 SHA-256，改变后返回 `DATASET_INTEGRITY_ERROR`，应重新上传。

画像版本不可覆盖，相同输入重复计算可幂等读取相同结果。计算实现升级至 1.1.0 / `table-v2`，旧画像仍可读取（缺少 `header_row` 时默认为 1）；使用新规则重算会创建新的版本标识，不覆盖旧结果。画像和源文件元数据在同一事务保存；服务重启后按 ID 与版本读取。未来改变解析或画像规则时必须明确升级契约，不能用新规则覆盖旧结果。

## 统计口径

- 默认第一条 CSV 记录 / Excel 第一行是表头；可显式传入 `header_row` 指定其他位置，不自动猜测。该行之前的标题、说明、空行及公式不参与画像。完全空表头、只有表头、空文件均拒绝。重复列名保留原名称；空列名用展示占位名称，非文本 Excel 表头转为显示文本并提示。
- 缺失：`None`、空字符串、仅空白字符的字符串。`NA / NULL / null / NaN / N/A` **不是默认缺失标记**。仅在判定缺失和识别格式时查看去除首尾空格的文本，原始值不改写。
- 每列提供 `missing_count / missing_rate / non_missing_count / unique_count`。缺失率分母是全部数据行；唯一值数排除缺失，按解析后的类型及原值计数，不将数字 `1`、字符串 `"1"`、布尔 `true` 合并。
- `samples` 为按输入顺序出现的前 5 个非缺失唯一值，保留类型；日期 / 时间以 ISO 字符串序列化。超过 120 字符的文本样本截断并标记 `truncated=true`，唯一值计算仍使用完整值。
- 重复行与疑似重复列按解析后的完整值和类型逐项比较；不做模糊重复识别，不删除任何记录。全空行仍计入统计；空白文本和 `None` 在重复比较中保留区别。
- CSV 空记录（空行）按全缺失行保留；带引号的换行属于同一条记录。质量问题中的记录序号保留原始位置，从文件第一条逻辑记录开始计数，不因指定表头行而重置，也不是多行 CSV 的物理文本行号。
- Excel 从 `header_row` 行的 A 列读至最后一个有值单元格形成的矩形范围；质量提示使用原工作表行号。表头上方的合并标题可忽略，跨越表头或位于数据区的合并单元格仍拒绝。尾部仅有格式的空区域不属于表格，并给出 `TRAILING_EMPTY_RANGE` 提示。范围内部空行 / 空列保留。单元格仍以 openpyxl 解析出的实际类型为准。
- 公式只保留公式文本；不执行公式，也不把缺失或过期缓存伪装成结果。Excel 错误单元格保留错误文本并提示。

## 基础类型

Physical Type 描述**解析后的实际存储值类型**：`null / boolean / integer / float / string / date / datetime / time / mixed`。CSV 的非空值始终为 `string`；Excel 使用解析后的原生类型。非缺失整数与浮点数可归并为 `float`，date / datetime 可归并为 `datetime`，其他不兼容组合为 `mixed`。全缺失为 `null`。

Logical Type 使用固定、保守、可测试的格式规则：

| 类型 | 规则 |
| --- | --- |
| `empty` | 全部缺失 |
| `boolean` | 原生布尔值，或文本 true / false（忽略大小写）；0/1 不自动视作布尔 |
| `integer` | 原生整数，或无前导零的有符号十进制整数文本 |
| `number` | 原生浮点，或小数 / 科学计数法文本；整数和 number 共存提升为 number |
| `date` | 原生 date，或有效的 ISO `YYYY-MM-DD` |
| `datetime` | 原生 datetime，或有效的 ISO 日期时间；date 与 datetime 共存可提升 |
| `time` | 原生 time，或有效的 ISO 时间 |
| `text` | 其他文本，包括带前导零的数字编码、货币符号、百分号、不明确日期格式 |
| `mixed` | 无法按上述规则兼容的多种逻辑类型 |

不推断“客户 ID、金额、地区”等业务语义，不进行行级语义抽取，也不将类型识别结果写回原数据。`physical_type_counts / logical_type_counts` 保存每种非缺失基础类型的实际数量，用于解释混合类型判断。

## 质量提示与错误

成功画像可包含这些提示：重复列名、空列名、非文本表头、全空行 / 列、重复行、逐值相同的疑似重复列、混合物理 / 逻辑类型、数据区重复表头、公式、Excel 错误值和尾部空范围。提示与结构错误分开：存在提示仍可得到画像，不会自动清洗。

| 错误码 | HTTP | 含义 |
| --- | --- | --- |
| `UNSUPPORTED_FILE` | 422 | 只支持 CSV / XLSX，不支持 XLS、XLSM |
| `HEADER_ROW_OUT_OF_RANGE` | 422 | 指定行在 CSV 逻辑记录或工作表中不存在 |
| `EMPTY_FILE / EMPTY_DATASET / EMPTY_HEADER / NO_DATA_ROWS` | 422 | 文件或表格为空、无有效表头或数据行 |
| `CSV_ENCODING_ERROR / INVALID_CSV / CSV_ROW_WIDTH_MISMATCH` | 422 | 编码、引号 / 文本结构或行宽异常 |
| `INVALID_XLSX` | 422 | 工作簿损坏、加密或不是有效 XLSX |
| `SHEET_SELECTION_REQUIRED / SHEET_NOT_FOUND` | 422 | 多 Sheet 需选择 / 指定名称不存在；`details.available_sheets` 提供名称 |
| `MERGED_CELLS_UNSUPPORTED / UNSUPPORTED_SHEET` | 422 | 合并单元格导致矩形结构不明确 / 非数据工作表 |
| `UNSUPPORTED_CELL_TYPE / UNSUPPORTED_FORMULA` | 422 | 暂不支持的原生值（例如时长）/ 无法读取为文本的特殊公式 |
| `CSV_SHEET_NOT_SUPPORTED / XLSX_CSV_OPTIONS` | 422 | 解析选项与文件格式不匹配 |
| `FILE_TOO_LARGE` | 413 | 上传超过 10 MB |
| `DATASET_LIMIT_EXCEEDED / XLSX_ARCHIVE_LIMIT` | 422 | 超过行列 / 单元格 / 解压内容上限 |
| `DATASET_INTEGRITY_ERROR` | 409 | 源文件已发生变化 |
| `DATASET_NOT_FOUND / PROFILE_NOT_FOUND / SOURCE_FILE_NOT_FOUND` | 404 | 数据集、版本画像或源文件缺失 |
| `REAL_PROFILE_NOT_AVAILABLE` | 409 | 历史会话仅有 Mock 画像或当前尚无画像 |

统一错误仍为 `{"error":{"code":...,"message":...,"node_name":...,"retryable":false,"details":...}}`。独立上传失败时删除本次失败的临时源文件；工作流内失败则保存失败会话和原文件以保留上下文，且停止 Planner，不兜底返回模拟统计值。

当前画像上限：10 万数据行、256 列、200 万数据单元格；XLSX 解压内容 50 MB / 1 万 ZIP 条目，声明维度过大的工作表也会拒绝。单次全量计算确切指标，不使用抽样估计。没有增加后台任务系统，仍使用本地单进程部署。

## 测试和后续读取

从项目根目录执行：

```bash
cd backend
../.venv/bin/python -m pytest -q
```

新增测试：`test_header_row.py`（指定表头、原始行号、版本及 API / 工作流）、`test_data_profiler.py`（解析 / 类型 / 指标 / 契约）与 `test_dataset_api.py`（API / 持久化 / 工作流）。Excel 由 openpyxl 在内存生成，涵盖空文件、混合类型、重复名称、多 Sheet、公式、损坏与结构异常。旧审批流程、画像到意图的依赖屏障和 Mock 报告测试继续回归。

后续 Planner 使用传入的 `DatasetProfile`，或用 `SessionState.dataset_ref` 调用 `DatasetRepository.profile(id, version)`。必须携带版本和字段 ID，不依赖唯一列名；真实统计执行模块尚未实现，不能将旧 Mock 报告关联为真实文件分析结果。
