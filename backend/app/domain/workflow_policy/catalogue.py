"""Pinned mapping of the 32 frozen V1.1 rows. No runtime document loading."""
from dataclasses import dataclass
from types import MappingProxyType

CONTRACT_VERSION = "REQ-0079/VER-0001"
CONTRACT_TABLE_SHA256 = "b0717bbbb498ae50b53135633b67180cbc14f035f20cbc2524ce0a5d2219c38c"

@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    name: str
    owner: str
    source: str | None
    target: str
    preconditions: str
    required_evidence: str
    proposed_fact_kinds: tuple[str, ...]

SPECS = MappingProxyType({
    'C01': CommandSpec('C01', '开始准备', 'control', 'CREATED', 'PROFILING', '固定输入、当前 revision 和新活动令牌', '接纳命令、输入绑定和状态同事务', ('input',)),
    'C02': CommandSpec('C02', '画像完成', 'control', 'PROFILING', 'PARSING_INTENT', '画像文件版本/hash/选项一致，当前活动令牌', 'DatasetProfile+固定DatasetRef+状态检查点', ('profile',)),
    'C03': CommandSpec('C03', '意图可规划', 'control', 'PARSING_INTENT', 'PLANNING', '真实合法 Intent.next_action=proceed', '保存意图、parse标识与输入绑定', ('intent',)),
    'C04': CommandSpec('C04', '意图需澄清', 'control', 'PARSING_INTENT', 'WAITING_FOR_CLARIFICATION', '合法 Intent.next_action=clarify', '意图与澄清问题已保存', ('intent',)),
    'C05': CommandSpec('C05', '补充澄清', 'control', 'WAITING_FOR_CLARIFICATION', 'PARSING_INTENT', '同目标回答、revision；不复用旧Planner检查点', '消息、答案集、新活动令牌、状态', ('answer',)),
    'C06': CommandSpec('C06', 'Planner回调', 'control', 'PLANNING', 'VALIDATING', '意图快照/参数/活动令牌未替换', '真实候选及来源保存', ('candidate',)),
    'C07': CommandSpec('C07', '保存验证计划', 'control', 'VALIDATING', 'AWAITING_APPROVAL', '候选精确匹配；保留F0/P0；版本不可变', 'PlanVersion+归属+validation+当前指针', ('plan', 'validation')),
    'C08': CommandSpec('C08', '待审批删除任务', 'control', 'AWAITING_APPROVAL', 'AWAITING_APPROVAL', '精确版本；无执行；删除任务合法', '新PlanVersion+验证；清有效批准；历史保留', ('plan', 'validation')),
    'C09': CommandSpec('C09', '已批准但未执行修订', 'control', 'APPROVED', 'AWAITING_APPROVAL', '无已claim执行/报告；明确撤销当前批准引用', '新版本+验证；原批准仅失去当前资格', ('plan', 'validation')),
    'C10': CommandSpec('C10', '批准当前计划', 'control', 'AWAITING_APPROVAL', 'APPROVED', '完整批准资格；精确版本/约束审计/告警确认', '批准快照+归属链接+当前批准+审计', ('approval',)),
    'C11': CommandSpec('C11', '执行claim', 'control', 'APPROVED', 'RUNNING', '有效批准；幂等请求；加载版本未变化', '新Execution+批准快照+归属+当前执行+新活动令牌', ('execution',)),
    'C12': CommandSpec('C12', 'Engine成功结束', 'control', 'RUNNING', 'COMPLETED', '当前execution、令牌、revision；全部任务结果已存', 'ExecutionResult.success+控制检查点', ('execution',)),
    'C13': CommandSpec('C13', 'Engine部分成功结束', 'control', 'RUNNING', 'COMPLETED', '当前execution；真实任务失败/skipped不可丢', 'ExecutionResult.partial_success+控制检查点', ('execution',)),
    'C14': CommandSpec('C14', 'Engine全部失败结束', 'control', 'RUNNING', 'FAILED', '当前execution；没有成功任务', 'ExecutionResult.failed+错误+控制检查点', ('execution',)),
    'C15-CREATED': CommandSpec('C15-CREATED', '准备失败/中断收敛', 'control', 'CREATED', 'FAILED', '仅当前准备作业；保存错误；recover需旧worker隔离', '失败阶段+错误+有效检查点', ('failure',)),
    'C15-PROFILING': CommandSpec('C15-PROFILING', '准备失败/中断收敛', 'control', 'PROFILING', 'FAILED', '仅当前准备作业；保存错误；recover需旧worker隔离', '失败阶段+错误+有效检查点', ('failure',)),
    'C15-PARSING_INTENT': CommandSpec('C15-PARSING_INTENT', '准备失败/中断收敛', 'control', 'PARSING_INTENT', 'FAILED', '仅当前准备作业；保存错误；recover需旧worker隔离', '失败阶段+错误+有效检查点', ('failure',)),
    'C15-PLANNING': CommandSpec('C15-PLANNING', '准备失败/中断收敛', 'control', 'PLANNING', 'FAILED', '仅当前准备作业；保存错误；recover需旧worker隔离', '失败阶段+错误+有效检查点', ('failure',)),
    'C15-VALIDATING': CommandSpec('C15-VALIDATING', '准备失败/中断收敛', 'control', 'VALIDATING', 'FAILED', '仅当前准备作业；保存错误；recover需旧worker隔离', '失败阶段+错误+有效检查点', ('failure',)),
    'C16-PROFILING': CommandSpec('C16-PROFILING', '准备显式Retry', 'control', 'FAILED', 'PROFILING', '只限retryable准备失败；无已保存审核计划/执行；选择有效检查点', '新活动令牌+revision+重试接纳；保留旧失败', ()),
    'C16-PARSING_INTENT': CommandSpec('C16-PARSING_INTENT', '准备显式Retry', 'control', 'FAILED', 'PARSING_INTENT', '只限retryable准备失败；无已保存审核计划/执行；选择有效检查点', '新活动令牌+revision+重试接纳；保留旧失败', ()),
    'C16-PLANNING': CommandSpec('C16-PLANNING', '准备显式Retry', 'control', 'FAILED', 'PLANNING', '只限retryable准备失败；无已保存审核计划/执行；选择有效检查点', '新活动令牌+revision+重试接纳；保留旧失败', ()),
    'C16-VALIDATING': CommandSpec('C16-VALIDATING', '准备显式Retry', 'control', 'FAILED', 'VALIDATING', '只限retryable准备失败；无已保存审核计划/执行；选择有效检查点', '新活动令牌+revision+重试接纳；保留旧失败', ()),
    'C17': CommandSpec('C17', '首次报告排队', 'generation', None, 'queued', '精确已结束Execution与批准；全失败仅诊断，不生成成功事实', 'generation attempt=1+当前作用域/报告令牌', ('generation',)),
    'C18': CommandSpec('C18', '报告启动', 'generation', 'queued', 'generating', '当前attempt/报告令牌；重复start不重复调用', 'generation.started_at+作业检查点', ('generation',)),
    'C19': CommandSpec('C19', '提交可交付报告', 'generation', 'generating', 'completed', '合法证据、覆盖与有效当前分支；accepted=True', '报告+归属+generation.report_id同事务', ('report',)),
    'C20': CommandSpec('C20', '提交不可生成记录', 'generation', 'generating', 'unavailable', '无有效证据或无有效核心洞察；不得complete', 'unavailable报告记录+原因+generation同事务', ('report',)),
    'C21-queued': CommandSpec('C21-queued', '报告失败/Recover', 'generation', 'queued', 'failed', '当前attempt；Recover须确认旧worker退出', '失败记录+错误；Execution不变', ('failure',)),
    'C21-generating': CommandSpec('C21-generating', '报告失败/Recover', 'generation', 'generating', 'failed', '当前attempt；Recover须确认旧worker退出', '失败记录+错误；Execution不变', ('failure',)),
    'C22': CommandSpec('C22', '报告显式Retry', 'generation', 'failed', 'queued', 'expected_attempt匹配、当前分支有效且未交付；已知Root只能running/partial/failed/interrupted，缺Trace不阻断', 'attempt+1+新报告活动令牌+排队检查点', ('generation',)),
    'C23': CommandSpec('C23', '提交任务进度', 'control', 'RUNNING', 'RUNNING', '当前execution/task、revision与活动令牌；不重复任务结果', '任务状态+完整结果/引用同事务', ('task',)),
    'C24': CommandSpec('C24', '创建独立新目标', 'creation', None, 'CREATED', '新创建键；同Session消息文件授权；原Workflow不变', 'Workflow+origin/root_id/幂等键同事务', ('input', 'message')),
})
