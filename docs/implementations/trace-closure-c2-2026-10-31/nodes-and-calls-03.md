# 正式真实运行节点清单（03）

Root: `run_15c55fbf4a624e3c8ff4eb2c07abb526`；Workflow: `wf_65b741d8c88b45a2940abace3c8f92e5`。全部 Span 直接归属该 Root，parent_span_id=null。

| 节点 | attempt | 状态 | 耗时 ms | span_id | 真实结果引用 |
|---|---:|---|---:|---|---|
|data_profiler|1|complete|5.863|`span_e69bd8abb3a54f44b62e0ac7035ebd35`|dataset_id=efe94407426a425f8c0e464ad92a5e22<br>dataset_version=0fcb048be730a06701110f2cb88ee638412f7625c1f2d566ee6e419df2534c2a|
|intent_parser|1|complete|2802.214|`span_0cf8c784309c485ab53dd885f2bbb9cf`|operation_id=acf1ec3a45e148ca95da6b2ca8626a98|
|analysis_planner|1|complete|6740.223|`span_9c4952a8f2fe477d929bce9ce5cb3a1c`|operation_id=cfb2f82f34e84403ab7203a0e6dde813|
|plan_validator|1|complete|4.383|`span_a1a64abd59ce4bd09bf4ac81937654ca`|validation_role=planner_output|
|plan_validator|2|complete|3.588|`span_ec138a65e1084cf8a6db24f828525c2d`|validation_role=initial_plan_save|
|hitl|1|complete|20.054|`span_d0ecca95419f4cf9acf0e2a13e3f5230`|dataset_id=efe94407426a425f8c0e464ad92a5e22<br>dataset_version=0fcb048be730a06701110f2cb88ee638412f7625c1f2d566ee6e419df2534c2a<br>approval_id=approval_1404ce3086f44124bfd7c0aee4f45b29|
|plan_validator|3|complete|2.325|`span_53d9f26581bc4c8a97d8e8c8b318d2bd`|validation_role=hitl_approve|
|analysis_engine|1|complete|8.704|`span_2aa77ff0ba094a299ad2cf1f80e53cd7`|approval_id=approval_1404ce3086f44124bfd7c0aee4f45b29<br>plan_version_id=wpv_a69aaaf0ac668ccca2ad8ec8356c35275a6296576074b91f79f09277fb1c06ac<br>result_ref=exec_1739e70a5bd6468eb9ed55005379e3e2|
|evidence_builder|1|complete|2.415|`span_e2f5b36236e14e049462c793182d2433`|approval_id=approval_1404ce3086f44124bfd7c0aee4f45b29<br>plan_version_id=wpv_a69aaaf0ac668ccca2ad8ec8356c35275a6296576074b91f79f09277fb1c06ac<br>result_ref=exec_1739e70a5bd6468eb9ed55005379e3e2<br>report_run_id=run_73539e80f42648a5a26dbb1787084f1f|
|chart_builder|1|complete|1.316|`span_cac4bb8fa2f640a6ac9555749b171929`|approval_id=approval_1404ce3086f44124bfd7c0aee4f45b29<br>plan_version_id=wpv_a69aaaf0ac668ccca2ad8ec8356c35275a6296576074b91f79f09277fb1c06ac<br>result_ref=exec_1739e70a5bd6468eb9ed55005379e3e2<br>report_run_id=run_73539e80f42648a5a26dbb1787084f1f|
|insight_generator|1|complete|6494.631|`span_9944acf699364609bd14469998d67521`|approval_id=approval_1404ce3086f44124bfd7c0aee4f45b29<br>plan_version_id=wpv_a69aaaf0ac668ccca2ad8ec8356c35275a6296576074b91f79f09277fb1c06ac<br>result_ref=exec_1739e70a5bd6468eb9ed55005379e3e2<br>report_run_id=run_73539e80f42648a5a26dbb1787084f1f|
|fact_validator|1|complete|10.32|`span_632e45eb23ea4238baa4a31166eeb829`|approval_id=approval_1404ce3086f44124bfd7c0aee4f45b29<br>plan_version_id=wpv_a69aaaf0ac668ccca2ad8ec8356c35275a6296576074b91f79f09277fb1c06ac<br>result_ref=exec_1739e70a5bd6468eb9ed55005379e3e2<br>report_run_id=run_73539e80f42648a5a26dbb1787084f1f|
|report_assembler|1|complete|2.474|`span_555d9f5d608341f8bed1d941e419090c`|approval_id=approval_1404ce3086f44124bfd7c0aee4f45b29<br>plan_version_id=wpv_a69aaaf0ac668ccca2ad8ec8356c35275a6296576074b91f79f09277fb1c06ac<br>result_ref=exec_1739e70a5bd6468eb9ed55005379e3e2<br>report_run_id=run_73539e80f42648a5a26dbb1787084f1f|
|report_persistence|1|complete|7.72|`span_21dc79dd4d3a4abeb2e3b6ae93cc5f83`|approval_id=approval_1404ce3086f44124bfd7c0aee4f45b29<br>plan_version_id=wpv_a69aaaf0ac668ccca2ad8ec8356c35275a6296576074b91f79f09277fb1c06ac<br>result_ref=exec_1739e70a5bd6468eb9ed55005379e3e2<br>report_run_id=run_73539e80f42648a5a26dbb1787084f1f<br>report_id=report_4d0455e523c645d99660ed61467dfc1e|

## LLM 调用

| 节点 | 状态 | 耗时 ms | call_id | span_id | 模板快照 |
|---|---|---:|---|---|---|
|intent_parser|succeeded|2766.089|`call_93ade34088ef4cb6bc4de47a4181fad9`|`span_0cf8c784309c485ab53dd885f2bbb9cf`|`pt_c61175023dfaa7f9b7248cd3b30a2baa6eb9a1bff93889fba0183a285b441754`|
|analysis_planner|succeeded|6632.367|`call_adb5fe785b0743b99081fc5d27529c12`|`span_9c4952a8f2fe477d929bce9ce5cb3a1c`|`pt_00d2887d1cbeb11e82cba23892064ef53a8603d6c4286cdc8eca73701bb9a272`|
|insight_generator|succeeded|6422.679|`call_182e98a54ca44e68a598236c56c8c16c`|`span_9944acf699364609bd14469998d67521`|`pt_c2cb54912d2bf620ff6d1cecddecbf440606c6ed094a7706163e91734932dedb`|

原始结构化记录和请求 Schema/消息快照引用见 real-run-03.json。实际消息保持在私有 Registry 数据库并受原有权限控制；此清单不复制密钥或完整请求。
