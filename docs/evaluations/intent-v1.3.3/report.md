# Intent Parser V1.3 语义可靠性优化交付

当前候选Prompt为 **intent-v1.3.3**，仍为qwen3.8-flash、原IntentResult Schema、单LLM节点。本轮完成Prompt、grounding反馈、冻结评分器、历史重评分、真实评测和回归测试。保留全部失败与中间版本，未用关键词补齐模型输出，未使用Mock掩盖真实失败。

**未宣布完整语义验收通过。** 下表保留冻结规则的自动分数，评分误报另作审阅记录，不修改原分或标签。评测仅代表固定合成上下文与这些请求，不能证明任意自然语言均可靠。

## 当前候选的真实评测

148条已见回归 + 20条独立未见请求 = 168条主评测；另有7个关键请求各重复3次（21条），不与主评测混成更大的独立样本量。

|组别|有效返回|约束召回|约束精确率|完整请求通过|自动否定错误数|阻断召回|
|---|---|---|---|---|---|---|
|原40条|40/40|100.00%|100.00%|40/40（100.00%）|0|100.00%|
|V1.2原28条|28/28|98.44%|100.00%|27/28（96.43%）|0|100.00%|
|V1.3新增20条（已见）|20/20|100.00%|100.00%|20/20（100.00%）|0|100.00%|
|否定12条|12/12|100.00%|100.00%|11/12（91.67%）|1|—|
|组合8条|8/8|98.11%|97.87%|7/8（87.50%）|0|100.00%|
|V1.3.1原独立20条（已见）|20/20|97.87%|97.73%|19/20（95.00%）|0|100.00%|
|V1.3.2原独立20条（已见）|20/20|97.67%|97.56%|19/20（95.00%）|0|100.00%|
|本轮独立J集20条|20/20|97.78%|95.35%|18/20（90.00%）|1|100.00%|
|关键重复21次|21/21|100.00%|100.00%|21/21（100.00%）|0|100.00%|
|主评测合计168条|168/168|98.64%|98.57%|161/168（95.83%）|2|100.00%|

主评测有效Intent返回率100.00%；Schema合法率100.00%；模式准确率100.00%；已标注核心目标扩写0条，编造决策目标0条。

最终候选共189次Parser请求，实际Provider尝试191次；每次尝试正文、耗时和状态保存在各*-live.json的model_attempts。失败保留在分母，0条阻断参考的批次显示—，不解释成阻断识别失败。

K07与J12各触发一次原话依据重试：首个输出使用了不存在的“只看...搜索渠道”，被严格grounding拒绝；第二次返回连续原话，但仍把时间混入filters。这两个步骤均保存，说明“原话可追溯”通过不等于“分类语义正确”。最终Provider响应率191/191，有效Intent返回189/189；不能把重试后的合法结构称作首轮全部成功。

原40条阻断识别10/10，全部168条应澄清样本26/26；未延续V1.3.2中8/10的退化。64条带否定/边界标注的请求均获得有效结果，自动错误2条，其中1条为上述已披露评分误报。

## 自动错误与语义复核

最终候选有7条自动Bad Case。代理逐条复核后：6条实际遗漏/分类问题，1条评分器误报。自动原分保持不变，逐条依据见[semantic-review.json](semantic-review.json)。

- O05：“排名”只在目标中出现，analysis_limits遗漏。
- K07 / F09 / J12：时间混入filters，虽已另存time_range，仍违反类别与最小片段规则。
- H05：“排除华东地区”误入analysis_limits，应为filters；未反转成包含，但分类不对。
- J18：独立样本“不要求计算响应时长”被存入analysis_limits，是本轮仍未解决的非必选内容误作限制问题。business_goal及指标未新增响应时长，不能据此忽略约束风险。
- G10：目标“比较除上海外其他城市”与filters“排除上海”一致，冻结的中文立场启发式未识别“除X外”，误判为正向要求上海。自动否定错误仍保留2条（G10与J18），不把复核结论偷偷折算成更好分数。

因此，召回与精确率虽达到95%，独立样本仍有语义分类错误，本轮**不满足完整验收要求**。以下保留全部7条实际输出和自动失败详情。

### previous28 / O05（第1次）

请求：按库存件数排名，只列出前六项。

实际business_goal：按库存件数排名，列出前六项

```json
{
  "constraints": {
    "time_range": null,
    "filters": [],
    "metric_requirements": [
      {
        "raw_text": "库存件数",
        "validation_status": "unverified"
      }
    ],
    "analysis_limits": [
      {
        "raw_text": "只列出前六项",
        "validation_status": "unverified"
      }
    ]
  },
  "failures": [
    {
      "reason": "missing_constraint",
      "category": "analysis_limits",
      "raw_text": "排名"
    }
  ],
  "error": null
}
```

### negation / G10（第1次）

请求：排除上海，比较其他城市的岗位数量。

实际business_goal：比较除上海外其他城市的岗位数量

```json
{
  "constraints": {
    "time_range": null,
    "filters": [
      {
        "raw_text": "排除上海",
        "validation_status": "unverified"
      }
    ],
    "metric_requirements": [
      {
        "raw_text": "岗位数量",
        "validation_status": "unverified"
      }
    ],
    "analysis_limits": []
  },
  "failures": [
    {
      "reason": "polarity_error",
      "kind": "goal_stance_conflict",
      "topic": "明确排除上海",
      "expected": "prohibited",
      "violations": [
        {
          "clause": "比较除上海外其他城市的岗位数量",
          "topic": "上海",
          "stance": "required"
        }
      ]
    }
  ],
  "error": null
}
```

### combinations / K07（第1次）

请求：只看去年搜索渠道，统计点击次数和投放费用，按投放费用降序保留前两项。

实际business_goal：统计去年搜索渠道的点击次数和投放费用，并按投放费用降序保留前两项

```json
{
  "constraints": {
    "time_range": {
      "raw_text": "去年",
      "validation_status": "unverified"
    },
    "filters": [
      {
        "raw_text": "只看去年搜索渠道",
        "validation_status": "unverified"
      }
    ],
    "metric_requirements": [
      {
        "raw_text": "点击次数",
        "validation_status": "unverified"
      },
      {
        "raw_text": "投放费用",
        "validation_status": "unverified"
      }
    ],
    "analysis_limits": [
      {
        "raw_text": "按投放费用降序保留前两项",
        "validation_status": "unverified"
      }
    ]
  },
  "failures": [
    {
      "reason": "incorrect_constraint",
      "category": "filters",
      "raw_text": "只看去年搜索渠道",
      "matched_unit_indices": [
        1
      ],
      "foreign_unit_indices": [
        0
      ],
      "semantic_valid": false,
      "duplicate": false,
      "reference_aligned": false
    },
    {
      "reason": "missing_constraint",
      "category": "filters",
      "raw_text": "搜索渠道"
    }
  ],
  "error": null
}
```

### prior20 / F09（第1次）

请求：只看去年搜索渠道，比较点击次数和投放费用合计，按投放费用合计升序保留前四项。

实际business_goal：比较去年搜索渠道的点击次数和投放费用合计

```json
{
  "constraints": {
    "time_range": {
      "raw_text": "去年",
      "validation_status": "unverified"
    },
    "filters": [
      {
        "raw_text": "只看去年搜索渠道",
        "validation_status": "unverified"
      }
    ],
    "metric_requirements": [
      {
        "raw_text": "点击次数",
        "validation_status": "unverified"
      },
      {
        "raw_text": "投放费用合计",
        "validation_status": "unverified"
      }
    ],
    "analysis_limits": [
      {
        "raw_text": "按投放费用合计升序保留前四项",
        "validation_status": "unverified"
      }
    ]
  },
  "failures": [
    {
      "reason": "incorrect_constraint",
      "category": "filters",
      "raw_text": "只看去年搜索渠道",
      "matched_unit_indices": [
        1
      ],
      "foreign_unit_indices": [
        0
      ],
      "semantic_valid": false,
      "duplicate": false,
      "reference_aligned": false
    },
    {
      "reason": "missing_constraint",
      "category": "filters",
      "raw_text": "搜索渠道"
    }
  ],
  "error": null
}
```

### prior-acceptance20 / H05（第1次）

请求：排除华东地区，只看已完成订单，按销售额降序比较成本和销售额。

实际business_goal：排除华东地区，比较已完成订单的成本和销售额

```json
{
  "constraints": {
    "time_range": null,
    "filters": [
      {
        "raw_text": "只看已完成订单",
        "validation_status": "unverified"
      }
    ],
    "metric_requirements": [
      {
        "raw_text": "销售额",
        "validation_status": "unverified"
      },
      {
        "raw_text": "成本",
        "validation_status": "unverified"
      }
    ],
    "analysis_limits": [
      {
        "raw_text": "排除华东地区",
        "validation_status": "unverified"
      },
      {
        "raw_text": "按销售额降序",
        "validation_status": "unverified"
      }
    ]
  },
  "failures": [
    {
      "reason": "incorrect_constraint",
      "category": "analysis_limits",
      "raw_text": "排除华东地区",
      "matched_unit_indices": [],
      "foreign_unit_indices": [
        0
      ],
      "semantic_valid": false,
      "duplicate": false,
      "reference_aligned": false
    },
    {
      "reason": "missing_constraint",
      "category": "filters",
      "raw_text": "排除华东地区"
    }
  ],
  "error": null
}
```

### independent20 / J12（第1次）

请求：只看本月搜索渠道，按成交金额升序取前五项。

实际business_goal：查看本月搜索渠道中，按成交金额升序排列的前五项数据

```json
{
  "constraints": {
    "time_range": {
      "raw_text": "本月",
      "validation_status": "unverified"
    },
    "filters": [
      {
        "raw_text": "只看本月搜索渠道",
        "validation_status": "unverified"
      }
    ],
    "metric_requirements": [
      {
        "raw_text": "成交金额",
        "validation_status": "unverified"
      }
    ],
    "analysis_limits": [
      {
        "raw_text": "按成交金额升序取前五项",
        "validation_status": "unverified"
      }
    ]
  },
  "failures": [
    {
      "reason": "incorrect_constraint",
      "category": "filters",
      "raw_text": "只看本月搜索渠道",
      "matched_unit_indices": [
        1
      ],
      "foreign_unit_indices": [
        0
      ],
      "semantic_valid": false,
      "duplicate": false,
      "reference_aligned": false
    },
    {
      "reason": "missing_constraint",
      "category": "filters",
      "raw_text": "搜索渠道"
    }
  ],
  "error": null
}
```

### independent20 / J18（第1次）

请求：只统计工单数量，不要求计算响应时长，也不要按客户等级排名。

实际business_goal：统计工单数量

```json
{
  "constraints": {
    "time_range": null,
    "filters": [],
    "metric_requirements": [
      {
        "raw_text": "工单数量",
        "validation_status": "unverified"
      }
    ],
    "analysis_limits": [
      {
        "raw_text": "不要求计算响应时长",
        "validation_status": "unverified"
      },
      {
        "raw_text": "也不要按客户等级排名",
        "validation_status": "unverified"
      }
    ]
  },
  "failures": [
    {
      "reason": "incorrect_constraint",
      "category": "analysis_limits",
      "raw_text": "不要求计算响应时长",
      "matched_unit_indices": [],
      "foreign_unit_indices": [],
      "semantic_valid": false,
      "duplicate": false,
      "reference_aligned": false
    },
    {
      "reason": "polarity_error",
      "kind": "optional",
      "violations": [
        {
          "category": "analysis_limits",
          "raw_text": "不要求计算响应时长"
        }
      ]
    }
  ],
  "error": null
}
```

## 优化内容与标签复核

- 四状态：明确要求、未指定、非必选、明确禁止只作为内部判断规则；不增加Schema字段。仅正向要求进入目标与必需指标，显式禁令及防收窄边界完整保留在analysis_limits。
- 四类约束：时间、数据子集、完整指标、排序/Top N/分析边界分别归类；排序可带指标上下文，但完整指标必须另存。禁用跨类别整句复制与裸“比较”。原话本就不连续的“按工单类别统计数量”，允许提取真实“数量”，不拼造“工单数量”。
- 已知范围保留，未知城市/客户值记录为uncertainty；整份数据主题不相关须确认输入，个别字段/统计可行性留给Planner/Validator，不越界执行。
- C07原校验拒绝非连续拼接是正确行为。约束raw_text及decision_goal仍要求来自某一份用户输入的连续原话；analysis_object/business_goal及不确定性解释可忠实改写。没有放宽到允许虚构值。
- 40条Gold原复核的9处改动继续保留：S08/R05/R08/C07/C08/P07保留已知范围或指标，R09/P10保留禁令，C09不拼造非连续指标。详见原始[标签复核](../../../backend/evaluation/intent_gold_review_v12.json)。新标签均在各自真实调用前冻结。
- 用户已确认N07/N10/N11三项语义及首轮实际返回，记录见[人工确认](../intent-v1.3/human-review-record.json)。其他标签为代理按规格审阅，未冒充全量人工Gold；最终输出的代理审阅不等于用户逐条签字。

## 冻结评分与历史比较

评分协议intent-reliable-v1.3在任何V1.3真实调用及历史重评分前冻结，之后没有修改。它检查类别、完整单元、重复、混类、无意义约束、排序上下文、预标注等价片段、目标文本中的四状态与已知额外核心目标。中文立场判断为启发式，不是通用语义蕴含证明。

原v1.1/v1.2文件、原分数和Prompt均未覆盖。历史输出按新冻结规则重评，不重新调用模型：

|保存输出/新规则|有效返回|约束召回|约束精确率|完整请求通过|自动否定错误数|阻断召回|
|---|---|---|---|---|---|---|
|V1.1 / 原40|40/40|62.07%|77.08%|24/40（60.00%）|5|100.00%|
|V1.2 / 原40|39/40|77.59%|88.46%|31/40（77.50%）|0|90.00%|
|V1.2 / 原28|28/28|98.44%|96.92%|24/28（85.71%）|3|100.00%|

只在同一规则、相同数据集下比较版本。新规则不再将混类项算作正确召回，因此不得把这里的召回率直接与历史旧评分率作提升比较。

## 中间候选及失败保留

|Prompt|主评测数|完整通过|召回|精确率|自动否定错误|
|---|---|---|---|---|---|
|intent-v1.3|108|97/108|98.71%|96.51%|3|
|intent-v1.3.1|128|119/128|97.14%|98.08%|3|
|intent-v1.3.2|148|142/148|98.76%|99.34%|0|
|intent-v1.3.3|168|161/168|98.64%|98.57%|2|

- V1.3仍出现双重否定改写、未定口径误存限制、维度冗余与时间混类。
- V1.3.1补充最小片段指导，但Prompt中的错误反例短语仍被模型复制。个别非排除目标改写也触发保守评分争议，全部保留。
- V1.3.2删除易复制的坏反例并加入完整正确JSON。关键重复21/21通过、当阶段独立H集20/20通过，但旧40条C08/P08错误proceed，阻断召回降至8/10，因此没有作为通过版本交付。
- V1.3.3加入完整clarify示例并移除互相冲突的条件：整份数据主题无关须确认，不因目标清楚就跳过；最终重新跑全部回归和新的J集。

本轮四个候选累计606次Parser请求、611次Provider尝试（含各阶段重复测试），不含历史V1.1/V1.2调用；各阶段实际次数保存在[comparison.json](comparison.json)。这些重复和已见回归不作为606条独立样本。

所有阶段每条剩余失败（含重试、重复测试）汇总为[all-phases-bad-cases.json](all-phases-bad-cases.json)，保留各阶段来源文件，不只展示末轮成功记录。阶段独立集在用于调优后，下一阶段均降为已见回归；最终J集在当前Prompt冻结后首次调用。

## 配置、来源与完整性

- 模型：qwen3.8-flash；enable_thinking=false；总超时30秒；最多2次尝试；temperature/top_p/max_tokens未指定，使用服务商默认值。未新增模型节点，无裁判模型。
- Prompt：intent-v1.3.3，完整文本[prompt.txt](prompt.txt)；Schema版本保持原IntentResult/V1，canonical SHA256 `a83e21c4f20a3e1512e67b10c3620a922520865d6b2d7f3ae4e4f2231c36723a`。parser_version=1.1是已有契约元信息，不冒充新Schema版本。
- 单次评测上下文由真实Data Profiler解析明确标识的合成CSV生成，覆盖销售、招聘、工单、项目、库存、投放、金融及能源。只发送字段元信息与行数，sample_rows=[]；没有读取或上传个人招聘工作簿。
- 真实Provider输出is_mock=false；每条结果保存完整原始请求、结构化结果、调用尝试与错误。评测记录器只包裹既有Provider，不追加LLM调用。记录脱敏配置Key；不记录鉴权头。
- 历史及当前冻结清单共46项字节校验通过；83个非本轮目标业务模块哈希未变，评分器哈希未变，见[integrity-check.json](integrity-check.json)。

## 文件与测试

实际业务代码修改仅Intent Prompt、grounding函数及安全重试反馈。新增离线reliable_evaluation；调整评测/重评分脚本以保留全部尝试并防覆盖；新增各阶段冻结标签、专项测试、设计及报告。没有改Planner、HITL、Engine、Report业务实现，也未改变前端。

- backend/app/intent/prompt.py
- backend/app/intent/validation.py
- backend/app/services/intent_parser.py
- backend/app/intent/reliable_evaluation.py（新增）
- backend/scripts/evaluate_intent.py、rescore_intent.py
- backend/evaluation/*_v13.json、*_v131.json、*_v132.json、*_v133.json
- backend/tests/test_intent_v13.py、test_intent_v131_holdout.py、test_intent_v132_acceptance.py、test_intent_v133_holdout.py；原focused评测测试读取历史Prompt，保持当时未见性断言。
- README.md、docs/intent-parser.md、intent-evaluation.md、intent-llm-check.md、docs/evaluations/intent-v1.3*。

完整后端回归：**494 passed，1项既有Starlette TestClient弃用提示**。新增覆盖四状态、目标中的否定反转、重复/混类/无意义约束、指标与排序分类、条件等价片段、C07连续原话、虚构筛选值拒绝、上下文隔离、失败分母、有限重试、原输出和Key脱敏、独立集互斥及历史文件完整性。测试中的受控Provider只证明工程契约，真实语义成绩来自上述实际调用。

复现时先在当前终端安全加载本地模型环境，应用/脚本不会自动读取.env。使用新输出文件名，避免覆盖归档：

```bash
cd backend
../.venv/bin/python -m pytest -q
../.venv/bin/python scripts/evaluate_intent.py --live --cases evaluation/intent_final_unseen_v133.json --output ../docs/evaluations/intent-v1.3.3/independent-rerun-NEW.json
```

已评测样本重跑只能验证稳定性，不能再次称作未见。后续接线仍须尊重clarify暂停；本轮独立Parser不会触发Planner或Engine。

## 验收边界

三项关键语义已取得用户确认，最终候选还进行了代理逐条语义检查，结果单列，不替代用户全量审阅。完整请求仍有结构化遗漏/混类，自动否定评分还存在“除X外”识别盲点；即使召回和精确率满足95%，也不把这些问题抹去或宣称完全验收。评分器的下一次修订须作为新协议单独冻结，再评历史与全新样本，不能用本轮结果回调当前规则。
