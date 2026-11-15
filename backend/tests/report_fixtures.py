"""Real deterministic kernel results + explicit scripted interpretation provider."""
import json

import pandas as pd

from datetime import datetime
from app.domain.analysis_plan import AnalysisPlan
from app.domain.execution import ExecutionResultV1
from app.domain.intent import ParsedIntent
from app.llm.base import LLMResponse
from app.planning.capabilities import CapabilityRegistry, FieldState
from app.planning.validator import PlanValidator
from app.profiling.profiler import build_profile
from intent_fixtures import intent_payload
from planning_fixtures import CSV, plan, step, task
from test_planning_operations import run


def report_case(tasks=None, raw=CSV, failures=(), null_metrics=False):
    profile = build_profile(raw, ".csv", "report-dataset", "recruiting.csv")
    original = tasks or [task([step(), step("sort", {"field": "job_count", "direction": "desc"}, "S02")])]
    validated = PlanValidator(CapabilityRegistry()).validate(plan(original, profile), profile)
    registry = CapabilityRegistry()
    entries = []
    for index, candidate in enumerate(validated.plan.tasks):
        failed = candidate.task_id in failures or candidate.task_id in validated.blocked_task_ids
        result = None
        effective = profile.row_count
        if not failed:
            specs = [s.model_dump() for s in candidate.steps]
            aggregate_index = next((i for i,s in enumerate(specs) if s["operation"] in {"aggregate", "group_aggregate"}), len(specs))
            if aggregate_index:
                effective = len(run(specs[:aggregate_index], raw))
            frame = run(specs, raw)
            fields = {f.field_id: FieldState(f.logical_type, f.non_missing_count) for f in profile.fields}
            reserved, metrics = set(fields), set()
            for s in candidate.steps:
                params = registry.operations[s.operation].params_model.model_validate(s.params)
                fields = registry.propagate(s.operation, params, fields, reserved)
                reserved.update(fields)
                if s.operation in {"aggregate", "group_aggregate"}:
                    metrics = {m.alias for m in params.metrics}
            columns = [{"field": name, "label": "岗位数量" if name in metrics else next((f.display_name for f in profile.fields if f.field_id == name), name),
                "logical_type": fields[name].kind, "role": "metric" if name in metrics else "dimension",
                "unit": "条" if name == "job_count" or name == "total_count" else None} for name in fields]
            rows = json.loads(frame.to_json(orient="records", date_format="iso"))
            for column in columns:
                if column["logical_type"] == "date":
                    for row in rows:
                        if row[column["field"]] is not None:
                            row[column["field"]] = row[column["field"]].split("T")[0]
            if null_metrics:
                for row in rows:
                    for metric in metrics: row[metric] = None
            result = {"result_id": f"R{index + 1:03d}", "columns": columns, "rows": rows,
                "truncated": False, "total_result_rows": len(rows), "total_refs": []}
        entries.append({"task_id": candidate.task_id, "status": "failed" if failed else "success", "result": result,
            "effective_row_count": effective, "valid_sample_count": effective,
            "sample_definition": "进入聚合前的参与记录数；未针对单个指标剔除空值。", "scope": "本次上传样本及任务筛选范围",
            "calculation": "按当前批准的受控操作链计算，保留缺失分组。", "failure_reason": "任务执行失败或不支持。" if failed else None})
    successful = sum(e["status"] == "success" for e in entries)
    status = "failed" if not successful else ("success" if successful == len(entries) else "partial_success")
    execution = ExecutionResultV1.model_validate({"execution_id": "exec_kernel_test", "plan_id": validated.plan.plan_id,
        "plan_version": 1, "approved_plan_version": 1, "dataset_id": profile.dataset_id,
        "dataset_version": profile.dataset_version, "execution_status": status,
        "source": "imported", "producer": "deterministic-test-kernels", "tasks": entries})
    intent = ParsedIntent.model_validate(intent_payload(business_goal="比较城市岗位数量"))
    return intent, validated, execution, profile


def selection_output(payload):
    """Declared test transport response for the new internal selection contract."""
    groups = {}
    for e in payload['evidence']:
        groups.setdefault((e['task_id'], e['data_ref'], e['result_field']), []).append(e)
    priorities = {t['task_id']: t['priority'] for t in payload['tasks']}
    selected = []
    for key, values in sorted(groups.items(), key=lambda pair: (priorities[pair[0][0]], pair[0])):
        # Metadata-only coverage is supplemental when the task has metric groups.
        if key[2] == '$execution.valid_sample_count' and any(k[0] == key[0] and k[2] != key[2] for k in groups):
            continue
        evidence = next((e for e in values if e['evidence_type'] in {'ranking', 'metric'}), values[0])
        kind = evidence['evidence_type']
        finding_type = ('highlight' if kind in {'ranking', 'metric', 'maximum', 'minimum'} else
                        'coverage' if kind == 'coverage' else 'trend' if kind == 'change_rate' else
                        'concentration' if kind == 'proportion' or evidence['value'].get('comparison_kind') == 'returned_concentration' else 'difference')
        option = next((o for o in payload['recommendation_options'] if
            (o['task_id'], o['data_ref'], o['result_field']) == key), None)
        selected.append({'primary_evidence_id': evidence['evidence_id'], 'evidence_refs': [evidence['evidence_id']],
            'finding_type': finding_type, 'recommendation_id': option['option_id'] if option else 'none',
            'limitation_refs': list(payload['limitation_pool'])[:1]})
    return {'insights': selected[:8]}


class ReportProvider:
    def __init__(self, output=None, error=None):
        self.output, self.error, self.requests = output, error, []

    async def generate(self, request):
        self.requests.append(request)
        if self.error: raise self.error
        payload = json.loads(request.instruction)
        selected = []
        for evidence in sorted(payload["evidence"], key=lambda e: e["evidence_type"] == "coverage"):
            if evidence["task_id"] in {item["task"] for item in selected}: continue
            if evidence["evidence_type"] in {"ranking", "metric", "coverage"}:
                selected.append({"task": evidence["task_id"], "evidence": evidence})
        output = self.output
        if output is None and payload.get('draft_schema_version') == 'insight-selection-v2':
            output = selection_output(payload)
        if output is None:
            output = {"insights": [{"primary_evidence_id": item["evidence"]["evidence_id"],
                "evidence_refs": [item["evidence"]["evidence_id"]],
                "finding_type": "coverage" if item["evidence"]["evidence_type"] == "coverage" else "highlight",
                "implication": "该结果值得作为进一步评估的线索。", "recommendation": "结合业务适配性继续核查。",
                "limitations": ["样本范围有限。"]} for item in selected[:8]]}
        return LLMResponse(text=output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
                           provider="scripted-report", model="contract-fixture", is_mock=True)
