# Workflow 图详情（REQ-0126）

运行追踪侧栏只保留 Workflow（`/traces/workflows`）。Run Explorer 与 Trace Detail 不再出现在导航里。`/traces` 和 `/traces/detail` 重定向到 Workflow 列表，避免旧地址被当成运行 ID。`/traces/:runId` 与 `/traces/compare` 仍可通过地址打开，但不在菜单中。

列表去掉 Workflow ID、Session ID、业务生命周期、失败归因查询。表格最后一列是「查看详情」，进入 `/traces/workflows/:workflowId`。Workflow ID 本身不再是链接。

详情页左右约 60/40。左侧用纵向节点图展示这条 Workflow 的全部 span。当前观测数据的 `parent_span_id` 为空，所以按记录顺序连成一条链，不补造父子关系。若以后出现父节点，同一套展平结果按深度缩进。右侧只显示当前选中节点的状态、输入、输出、事件和已采集的 LLM 调用。默认选中地址里的 `span`，否则选第一条错误或暂停节点，再否则选第一个节点。

详情页不再放业务生命周期摘要、失败定位、质量信号、发现项、关联对象、报告尝试列表和 Bad Case 标注。这些能力仍留在各自页面，只是不挂在这张图上。

浏览器核对 `wf_d37a472ad4de4d28b5c2df9646c84914`：侧栏只有 Workflow；列表无查询表单，每行有查看详情；详情左图 14 个节点，左右栏约 755px / 503px。点击「洞察生成」后右侧标题变为洞察生成，输入显示 `input_bytes` 48803，输出含 `execution_id` 与 `report_run_id`。

Admin 相关测试 6 个文件 32 项通过，`tsc --noEmit` 无输出。
