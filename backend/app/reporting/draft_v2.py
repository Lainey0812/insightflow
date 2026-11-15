"""Internal selection contract. No model-written factual or explanatory prose."""
from typing import Literal
from copy import deepcopy

from pydantic import Field
from app.domain.analysis_plan import Name, PlanModel


class SelectedInsight(PlanModel):
    primary_evidence_id: Name
    evidence_refs: list[Name] = Field(min_length=1, max_length=8)
    finding_type: Literal['highlight', 'difference', 'concentration', 'trend', 'coverage']
    recommendation_id: Name
    limitation_refs: list[Name] = Field(max_length=5)


class InsightSelection(PlanModel):
    insights: list[SelectedInsight] = Field(min_length=1, max_length=8)


def allowed_finding_types(evidence):
    """The request and deterministic validator share the existing capability rule."""
    from .fact_validation import COMPATIBLE
    return [kind for kind, supported in COMPATIBLE.items() if evidence.evidence_type in supported
            and not (kind == 'concentration' and evidence.evidence_type == 'comparison'
                     and evidence.value.get('comparison_kind') != 'returned_concentration')]


def selection_schema(evidence, recommendations, limitation_pool, required_groups):
    schema = InsightSelection.model_json_schema()
    def portable(value):
        if isinstance(value, dict):
            if value.get('pattern') == r'\S':
                value['pattern'] = r'[\s\S]*\S[\s\S]*'
            for child in value.values():
                portable(child)
        elif isinstance(value, list):
            for child in value:
                portable(child)
    portable(schema)
    properties = schema['$defs']['SelectedInsight']['properties']
    ids = [e.evidence_id for e in evidence]
    properties['primary_evidence_id']['enum'] = ids
    properties['evidence_refs']['items']['enum'] = ids
    properties['recommendation_id']['enum'] = ['none', *recommendations]
    properties['limitation_refs']['items']['enum'] = list(limitation_pool)
    branches, groups = [], {}
    for e in evidence:
        binding = (e.task_id, e.data_ref, e.result_field, e.value.get('source_scope', e.scope))
        groups.setdefault(binding, []).append(e)
    for binding, items in groups.items():
        group_ids = [e.evidence_id for e in items]
        recommendation_ids = ['none', *[key for key, option in recommendations.items()
            if (option['task_id'], option['data_ref'], option['result_field']) == binding[:3]]]
        for kind in properties['finding_type']['enum']:
            compatible_ids = [e.evidence_id for e in items if kind in allowed_finding_types(e)]
            if compatible_ids:
                branch = deepcopy(schema['$defs']['SelectedInsight'])
                branch['properties']['finding_type']['enum'] = [kind]
                branch['properties']['primary_evidence_id']['enum'] = compatible_ids
                branch['properties']['evidence_refs']['items']['enum'] = group_ids
                branch['properties']['recommendation_id']['enum'] = recommendation_ids
                branches.append(branch)
    # Keep the base properties for existing readers; the intersection now enforces
    # real primary-ID/type compatibility at the model request boundary.
    schema['$defs']['SelectedInsight']['anyOf'] = branches
    schema['properties']['insights']['minItems'] = max(1, len(required_groups))
    return schema
