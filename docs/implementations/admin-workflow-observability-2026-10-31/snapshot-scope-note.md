# 快照范围纠正

首次 before.zip 仅覆盖 backend Python 与 admin/src，没有 SQL 迁移文件和 admin/tsconfig.json。自动扫描第一次生成的 changes.json / changes.patch / after.zip 将四个早已存在的 SQL 文件误分类为 added；这些 SQL 没有在本轮修改，也没有实施数据库迁移。该初始扫描结果保留以供追溯，不能作为实际修改清单。

权威交付清单为 changes-final.json、changes-final.patch、source-final.zip 和 source-final.json。tsconfig.json 的基线依据修改前的工具读取记录重建，只增加 resolveJsonModule；不冒充 before.zip 已含原文件。
