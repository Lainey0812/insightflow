"""Immutable, plan-bound calculation definitions; no inferred business semantics."""
import hashlib
import json

from pydantic import Field
from typing import Literal
from app.domain.analysis_plan import PlanModel
from app.domain.errors import AppError
from app.domain.models import now


class BasisRequest(PlanModel):
    expected_revision: int = Field(ge=0, strict=True)
    plan_id: str
    plan_version: int = Field(ge=1, strict=True)
    row_grain: Literal['unknown', 'record', 'entity', 'detail']
    entity_field_id: str | None = None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS plan_analysis_bases (
        session_id TEXT NOT NULL, plan_version INTEGER NOT NULL, record TEXT NOT NULL,
        PRIMARY KEY(session_id,plan_version),
        FOREIGN KEY(session_id,plan_version) REFERENCES plan_versions(session_id,plan_version))''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS approval_basis_owner ON plan_approvals(approval_id,session_id)')
    conn.execute('''CREATE TABLE IF NOT EXISTS approval_analysis_bases (
        approval_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL, plan_version INTEGER NOT NULL, record TEXT NOT NULL,
        FOREIGN KEY(approval_id,session_id) REFERENCES plan_approvals(approval_id,session_id),
        FOREIGN KEY(session_id,plan_version) REFERENCES plan_analysis_bases(session_id,plan_version))''')
    for table in ('plan_analysis_bases', 'approval_analysis_bases'):
        for action in ('UPDATE', 'DELETE'):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable analysis basis'); END")


def load(conn, session_id, version):
    row = conn.execute('SELECT record FROM plan_analysis_bases WHERE session_id=? AND plan_version=?',(session_id,version)).fetchone()
    return json.loads(row[0]) if row else None


def register(conn, record, declaration=None):
    row = conn.execute('SELECT profile FROM dataset_profiles WHERE dataset_id=? AND dataset_version=?',
                       (record.dataset_id,record.dataset_version)).fetchone()
    # Legacy fixtures/records without an exact profile cannot claim a basis.
    if row is None:
        return
    profile = json.loads(row[0]); fields = {f['field_id']:f for f in profile['fields']}
    if declaration is None:
        previous = load(conn,record.session_id,record.plan_version-1)
        declaration = ({'row_grain':previous['row_grain'],'entity_field_id':previous.get('entity_field_id')}
                       if previous and previous['dataset_id'] == record.dataset_id and previous['dataset_version'] == record.dataset_version
                       else {'row_grain':'unknown','entity_field_id':None})
    grain, entity = declaration['row_grain'], declaration.get('entity_field_id')
    if grain == 'entity':
        field = fields.get(entity)
        if not field or field['missing_count'] or field['unique_count'] != profile['row_count']:
            raise AppError('ENTITY_GRAIN_NOT_VERIFIED','该标识含缺失或重复，不能确认每行一个实体。请明确去重字段后重新提出分析需求。',422)
    elif entity is not None:
        raise AppError('ENTITY_FIELD_NOT_APPLICABLE','只有每行一个实体的声明可以指定实体标识。',422)
    metrics = []
    for task in record.validated_plan.plan.tasks:
        for step in task.steps:
            for metric in step.params.get('metrics',[]) if step.operation in {'aggregate','group_aggregate'} else []:
                field_id = metric.get('field'); function = metric['function']
                name = fields.get(field_id,{}).get('display_name',field_id or '记录')
                basis = ('逐行计数，不是业务实体去重数量' if function == 'count' and field_id is None else
                         '先排除缺失，再按字段不同值计数' if function == 'distinct_count' else
                         '统计该字段非空记录数' if function == 'count' else '按该字段非空值执行指定聚合')
                metrics.append({'task_id':task.task_id,'step_id':step.step_id,'alias':metric['alias'],
                    'field_id':field_id,'label':name[:1800], 'function':function,'basis':basis,
                    'unit_status':'record_count' if function in {'count','distinct_count'} else 'not_declared'})
    value = {'version':'analysis-basis-v1','session_id':record.session_id,'plan_id':record.plan_id,
        'plan_version':record.plan_version,'dataset_id':record.dataset_id,'dataset_version':record.dataset_version,
        'plan_hash':digest(record.validated_plan.plan.model_dump(mode='json')),
        'row_grain':grain,'entity_field_id':entity,'metrics':metrics,
        'entity_field_options':[{'field_id':f['field_id'],'label':f['display_name'][:1800],
            'unique_non_null':f['missing_count']==0 and f['unique_count']==profile['row_count']} for f in fields.values()],
        'declaration_source':'user' if declaration['row_grain'] != 'unknown' else 'unconfirmed',
        'created_at':now()}
    value['digest'] = digest(value)
    conn.execute('INSERT INTO plan_analysis_bases VALUES (?,?,?)',(record.session_id,record.plan_version,json.dumps(value,ensure_ascii=False)))


def bind_approval(conn, approval):
    value = load(conn, approval.session_id, approval.plan_version)
    if value:
        conn.execute('INSERT INTO approval_analysis_bases VALUES (?,?,?,?)',
            (approval.approval_id,approval.session_id,approval.plan_version,json.dumps(value,ensure_ascii=False)))


def approved(conn, session_id, version, approval_id, plan):
    value = load(conn,session_id,version)
    if value is None:
        return None  # Historical plan, no invented confirmation.
    row = conn.execute('SELECT session_id,plan_version,record FROM approval_analysis_bases WHERE approval_id=?',(approval_id,)).fetchone()
    if (not row or row['session_id'] != session_id or row['plan_version'] != version or json.loads(row['record']) != value
            or value['plan_id'] != plan.plan_id or value['dataset_id'] != plan.dataset_id
            or value['dataset_version'] != plan.dataset_version or value['plan_hash'] != digest(plan.model_dump(mode='json'))
            or value['digest'] != digest({k:v for k,v in value.items() if k != 'digest'})):
        raise AppError('ANALYSIS_BASIS_MISMATCH','当前计划口径与审批副本不一致，需要审核当前版本。',409)
    return value
