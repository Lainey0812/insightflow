# 等值筛选核对补充完成

追加说明，不覆盖 VER-0001 或报告。只读检查脚本先后错误使用 columns 和 name 键，分别产生 KeyError，未写业务数据。按实际 DatasetProfile.fields / FieldProfile.original_name 修正检查后，filter-value-check.json 已保存真实核对结果：CSV 内容哈希与保存画像一致；“华东地区”“已完成订单”各自精确命中 0 条。

这个补充只完成元数据核对文件，没有再次调用模型。真实模型仍只有一次，耗时约 52 秒；不修改原响应、不修正其错误筛选、不执行计算，不改变已保存的旧 Session 或配置。VER-0001 中模型时延和技术校验结论不变，追加明确的业务 Bad Case 证据文件。
