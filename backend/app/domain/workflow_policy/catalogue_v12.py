"""V1.2 overrides only C19, preserving the pinned V1.1 mapping."""
from types import MappingProxyType
from .catalogue import SPECS as V11_SPECS, CommandSpec

CONTRACT_VERSION = "REQ-0081/lifecycle-contract-v1.2"
CONTRACT_TABLE_SHA256 = 'cf709ac682c78fcedfe522ad3264903ac9c987a43c845f5d8c133d677b56c300'
_specs = {key: value for key, value in V11_SPECS.items() if key != "C19"}
_specs['C19-A'] = CommandSpec('C19-A', 'Report Commit Authorization', 'generation', 'generating', 'completed', '提交前验证当前Workflow、Execution、attempt、有效generating状态、revision和active key；合法报告与证据；不要求accepted', '未来业务事务原子提交Report、ReportGeneration、归属链接及提交元数据；此处仅授权尝试事务', ('report',))
_specs['C19-B'] = CommandSpec('C19-B', 'Report Completion Observation', 'span', 'running', 'complete', '由已提交持久事实核对得出accepted=True；精确Report/Generation/归属及提交身份与对应Span一致；不使用仅内存返回值', '只允许对应report_persistence Span完成；不得改业务事实、Root或其他Span；终态相同完成只读幂等', ())
SPECS_V12 = MappingProxyType(_specs)
del _specs
