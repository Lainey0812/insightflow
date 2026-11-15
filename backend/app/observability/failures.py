"""Deterministic failure attribution for Admin. Classification is by error code only; it never inspects raw content."""

CATEGORIES = {
    'file_input': ('文件或解析参数', '检查上传文件格式及表头行、工作表、编码、分隔符等解析参数。'),
    'data_content': ('数据内容', '文件可解析，但数据本身不满足分析条件。核对源数据或筛选范围。'),
    'model_service': ('模型服务', '模型调用超时、不可用或未配置。检查模型服务与网络，结果与 Prompt 无直接关系。'),
    'model_output': ('模型输出不合规', '模型已返回，但输出未通过结构、溯源或事实校验。结合调用记录与 Prompt 版本排查。'),
    'capacity': ('容量限制', '输入或输出超过系统上限。缩小数据范围或调整分批策略。'),
    'plan_blocked': ('规划或校验阻断', '计划无可执行任务、核心需求未覆盖或约束未通过证明。查看规划与校验节点。'),
    'interrupted': ('进程中断', '服务重启或进程退出导致未完成。可按检查点重试，不代表业务逻辑错误。'),
    'unclassified': ('未归类', '该错误代码尚无归类规则。按节点、错误代码与事件记录排查。'),
}

_CODES = {
    'file_input': {
        'EMPTY_FILE', 'EMPTY_HEADER', 'HEADER_ROW_OUT_OF_RANGE', 'NON_TEXT_HEADERS', 'BLANK_COLUMN_NAMES',
        'DUPLICATE_COLUMN_NAMES', 'SHEET_NOT_FOUND', 'SHEET_SELECTION_REQUIRED', 'UNSUPPORTED_SHEET',
        'CSV_SHEET_NOT_SUPPORTED', 'XLSX_CSV_OPTIONS', 'CSV_ENCODING_ERROR', 'UNSUPPORTED_FILE', 'FILE_TOO_LARGE',
        'INVALID_CSV', 'INVALID_XLSX', 'XLSX_ARCHIVE_LIMIT', 'CSV_ROW_WIDTH_MISMATCH', 'INTENT_INPUT_TOO_LONG', 'INTENT_INPUT_INVALID',
        'ANALYSIS_GOAL_REQUIRED',
    },
    'data_content': {
        'EMPTY_DATASET', 'NO_DATA_ROWS', 'DATASET_LIMIT_EXCEEDED', 'MERGED_CELLS_UNSUPPORTED',
        'UNSUPPORTED_CELL_TYPE', 'UNSUPPORTED_FORMULA', 'NON_FINITE_VALUE', 'INVALID_DATA', 'TYPE_MISMATCH',
        'NON_FINITE_RESULT', 'NUMERIC_PRECISION_LOSS', 'SCOPE_NO_MATCHES', 'DATASET_INTEGRITY_ERROR',
        'SOURCE_FILE_NOT_FOUND',
    },
    'model_service': {
        'LLM_TIMEOUT', 'LLM_HTTP_ERROR', 'LLM_UNAVAILABLE', 'LLM_CALL_FAILED', 'LLM_NOT_CONFIGURED',
        'PLANNER_LLM_CALL_FAILED', 'REPORT_LLM_CALL_FAILED', 'PLANNER_NOT_AVAILABLE', 'HTTP_ERROR',
    },
    'model_output': {
        'LLM_INVALID_JSON', 'LLM_INVALID_OUTPUT', 'LLM_INCOMPLETE_OUTPUT', 'LLM_REFUSED', 'LLM_UNGROUNDED_OUTPUT',
        'INTENT_SCHEMA_INVALID', 'PLANNER_INVALID_JSON', 'PLANNER_SCHEMA_INVALID', 'PLANNER_BUSINESS_INVALID',
        'PLAN_SCHEMA_INVALID', 'REPORT_LLM_INVALID_OUTPUT', 'REPORT_NO_VALID_INSIGHTS', 'REPORT_UNVERIFIED_FACT',
        'REPORT_INVALID_EVIDENCE_REFERENCE', 'REPORT_INVALID_EVIDENCE_TYPE', 'REPORT_INVALID_RECOMMENDATION',
        'REPORT_INVALID_LIMITATION_REFERENCE', 'REPORT_INVALID_FACT_BINDING', 'REPORT_INVALID_COMPARISON',
        'REPORT_DUPLICATE_FINDING', 'REPORT_CORE_FINDINGS_MISSING', 'REPORT_BOUNDARY_VIOLATION',
        'REPORT_DENOMINATOR_INVALID', 'REPORT_MOCK_LLM_REJECTED',
    },
    'capacity': {
        'PLANNER_CONTEXT_TOO_LARGE', 'DATASET_CONTEXT_TOO_LARGE', 'INTENT_REQUEST_TOO_LARGE',
        'PLANNER_OUTPUT_TOO_LARGE', 'REPORT_INPUT_TOO_LARGE', 'REPORT_CONTEXT_TOO_LARGE', 'REPORT_CAPACITY_EXCEEDED',
        'REPORT_TOTAL_CAPACITY_EXCEEDED', 'REPORT_FACT_COMPOSITION_TOO_LARGE', 'FULL_EXECUTION_TOO_LARGE',
        'SCOPE_ENUMERATION_TOO_LARGE',
    },
    'plan_blocked': {
        'NO_EXECUTABLE_TASKS', 'COVERAGE_BLOCKED', 'CORE_NOT_COVERED', 'BLOCKING_UNCERTAINTY',
        'UNVERIFIED_CONSTRAINTS', 'UNCONFIRMED_CONSTRAINTS', 'EMPTY_PLAN', 'INVALID_FIELD_REFERENCE',
        'UNSUPPORTED_OPERATION', 'INVALID_STEP_PARAMS', 'REQUIRES_TRANSFORMATION', 'REAL_PLANNER_REQUIRED',
    },
    'interrupted': {
        'PROCESS_INTERRUPTED', 'EXECUTION_INTERRUPTED', 'REPORT_PROCESS_INTERRUPTED', 'TRACE_PROCESS_INTERRUPTED',
    },
}
_BY_CODE = {code: category for category, codes in _CODES.items() for code in codes}

HINTS = {
    'EMPTY_HEADER': '指定的表头行为空。对照输入摘要中的 input_header_row 与文件实际表头位置。',
    'HEADER_ROW_OUT_OF_RANGE': '表头行超出文件行数。对照输入摘要中的 input_header_row。',
    'SHEET_NOT_FOUND': '指定的工作表不存在。对照输入摘要中的 input_sheet_name。',
    'SHEET_SELECTION_REQUIRED': '文件含多个工作表，需要指定 sheet_name。',
    'CSV_ENCODING_ERROR': '编码不匹配。对照输入摘要中的 input_encoding，可尝试 gb18030。',
    'CSV_ROW_WIDTH_MISMATCH': '数据行列数与表头行不一致。常见原因是表头行或分隔符填错：对照 input_header_row、input_delimiter 与源文件。',
    'LLM_TIMEOUT': '模型调用超过等待上限。查看该节点调用记录的耗时。',
    'NO_EXECUTABLE_TASKS': '计划中没有可执行任务。查看 analysis_planner 的 executable_count / blocked_count。',
}


def classify(code):
    category = _BY_CODE.get(code or '', 'unclassified')
    label, guidance = CATEGORIES[category]
    return {'category': category, 'label': label, 'hint': HINTS.get(code or '', guidance)}


def first_failure(nodes, business_error=None, generation_error=None):
    """Earliest failed/interrupted node wins; business errors are used only when no node failed."""
    failed = [n for n in nodes if n.get('status') in {'error', 'suspended', 'failed', 'interrupted'}]
    failed.sort(key=lambda n: (n.get('started_at') or '\uffff', n.get('span_id') or ''))
    if failed:
        node = failed[0]
        code = node.get('error_code') or 'TRACE_STAGE_FAILED'
        inputs = {k: v for k, v in (node.get('attributes') or {}).items() if k.startswith('input_')}
        return {**classify(code), 'code': code, 'source': 'node', 'node_name': node.get('name'),
                'node_key': node.get('node_key'), 'span_id': node.get('span_id'), 'inputs': inputs}
    for source, code in (('business', business_error), ('report_generation', generation_error)):
        if code:
            return {**classify(code), 'code': code, 'source': source, 'node_name': None, 'node_key': None,
                    'span_id': None, 'inputs': {}}
    return None
