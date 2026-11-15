# profiler-node-detail-v1

REQ-0132。只调整 Data Profiler 的右侧节点详情。左侧完整 Workflow 与右侧详情的双栏布局保持不变。

核对结果：`ProfileInput` 是文件信息加 `ProfileOptions`。完整画像已经保存在数据集仓库，包含文件元数据、解析选项、行列与单元格统计、字段统计和 `quality_issues`。节点 span 原先只保存解析选项、文件扩展名、文件大小、数据集标识、行数和字段数。质量信号数量和概览计数已经产生并保存在画像中，但没有写进 span。

本次没有修改画像计算，也没有增加数据清洗。新的成功 span 额外保存 `quality_issue_count`、`file_format`、`profiler_version`、`sheet_name`、单元格数、缺失单元格、缺失率、重复行和重复率。文件名仍只留在已保存画像里，不写入 span。历史 span 不回填。

Admin 中 `data_profiler` 使用独立详情：顶部是名称、状态、耗时，以及已采集的行数、字段数和质量信号数量。成功时不显示诊断区。失败时在顶部显示错误代码和已有说明，并可展开已保存的错误详情。只有 Input 和 Output。Input 展示 span 上的文件与解析信息；画像读取成功后补充文件名、格式、内容校验和画像配置。Output 展示数据集概览、字段 Schema、字段统计、真实质量信号，以及去掉字段样例值后的结构化 JSON。其他节点的 Tab 不变。

真实节点 `wf_d37a472ad4de4d28b5c2df9646c84914` 的数据画像为成功，耗时 24.6 ms。已保存画像为 48 行、10 个字段、480 个单元格、缺失单元格 0、重复行 0、质量信号 0。该 0 是 `quality_issues` 空数组的长度。Input 显示表头行 6、文件类型 xlsx 和文件大小 60764 字节。Output 表格有 10 行，JSON 可展开，且不包含 `samples`。左右栏宽度约 755px 和 503px。需求理解节点仍保留 Prompt & Model。

验证：Admin 类型检查通过；`workflows`、`failure-diagnosis`、`quality-signals` 共 19 项通过。后端 `test_normal_preparation_and_two_validator_sites_and_call_links` 通过，并确认新 span 写入了质量信号数量和文件格式。
