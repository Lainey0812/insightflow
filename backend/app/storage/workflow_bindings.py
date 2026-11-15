"""Atomic ownership links for registered single-flow Sessions; no lifecycle authority switch."""
import hashlib
import json
from app.domain.errors import AppError
from app.domain.models import now
from app.observability.provenance import digest


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def identity(conn, state):
    if not state.workflow_id and not state.root_run_id:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='business_workflows'").fetchone() and conn.execute('SELECT 1 FROM business_workflows WHERE session_id=?',(state.id,)).fetchone():
            raise AppError('WORKFLOW_IDENTITY_MISMATCH','已登记流程缺少显式身份，不能退回旧路径。',409)
        return None
    rows=conn.execute('SELECT * FROM business_workflows WHERE session_id=?',(state.id,)).fetchall()
    if len(rows)!=1 or (rows[0]['workflow_id'],rows[0]['root_run_id'],rows[0]['input_file_id']) != (state.workflow_id,state.root_run_id,state.file.id):
        raise AppError('WORKFLOW_IDENTITY_MISMATCH','业务归属与已登记身份不一致。',409)
    return rows[0]


def bind_approval(conn, state, approval, request, source_kind='native'):
    wf=identity(conn,state)
    if wf is None:return
    plan=state.review_plan
    if wf['dataset_id'] is None:
        conn.execute('UPDATE business_workflows SET dataset_id=?,dataset_version=?,revision=revision+1 WHERE workflow_id=?',
            (plan.dataset_id,plan.dataset_version,state.workflow_id))
    elif (wf['dataset_id'],wf['dataset_version'])!=(plan.dataset_id,plan.dataset_version):
        raise AppError('WORKFLOW_DATASET_MISMATCH','流程固定数据版本不一致。',409)
    pvid='wpv_'+sha(state.workflow_id+':'+str(plan.plan_version))
    conn.execute('''INSERT OR IGNORE INTO workflow_plan_versions
        (plan_version_id,workflow_id,session_id,plan_version,plan_id,dataset_id,dataset_version,
         validation_version,payload_hash,source_kind,legacy_session_id,legacy_plan_version,registered_at)
        VALUES (?,?,?,?,?,?,?,?,?,'legacy_ref',?,?,?)''',
        (pvid,state.workflow_id,state.id,plan.plan_version,plan.plan_id,plan.dataset_id,plan.dataset_version,
         plan.validation_version,sha(plan.model_dump_json()),state.id,plan.plan_version,now()))
    stored=conn.execute('SELECT payload_hash FROM workflow_plan_versions WHERE plan_version_id=?',(pvid,)).fetchone()
    if stored['payload_hash']!=sha(plan.model_dump_json()):
        raise AppError('WORKFLOW_PLAN_CONFLICT','不可变计划归属冲突。',409)
    conn.execute('INSERT INTO workflow_approval_links VALUES (?,?,?,?,?,?,?,?,?)',
        (approval.approval_id,state.workflow_id,state.id,pvid,request.approval_request_id,
         sha(request.model_dump_json()),digest(approval.snapshot),source_kind,now()))


def bind_execution(conn,state,execution_id,request):
    wf=identity(conn,state)
    if wf is None:return None
    approval=state.engine_approval
    link=conn.execute('SELECT * FROM workflow_approval_links WHERE approval_id=? AND workflow_id=?',
        (approval.approval_id,state.workflow_id)).fetchone()
    if link is None:
        # On-demand reference registration for a pre-C2 immutable Approval; not an approval replay or Trace backfill.
        from app.domain.plan_review import ReviewApproval
        from types import SimpleNamespace
        row=conn.execute('SELECT record,request FROM plan_approvals WHERE approval_id=? AND session_id=?',
            (approval.approval_id,state.id)).fetchone()
        if row is None:raise AppError('WORKFLOW_APPROVAL_UNBOUND','审批缺少可核验归属。',409)
        saved=ReviewApproval.model_validate_json(row['record'])
        if saved.snapshot!=approval:raise AppError('WORKFLOW_APPROVAL_UNBOUND','旧审批快照不一致。',409)
        raw_request=row['request']
        request_ref=SimpleNamespace(approval_request_id=json.loads(raw_request)['approval_request_id'],model_dump_json=lambda:raw_request)
        bind_approval(conn,state,saved,request_ref,'legacy_ref')
        link=conn.execute('SELECT * FROM workflow_approval_links WHERE approval_id=?',(approval.approval_id,)).fetchone()
    key=execution_id+'@'+str(state.revision)
    conn.execute('INSERT INTO workflow_execution_links VALUES (?,?,?,?,?,?,?,?,?,?)',
        (execution_id,state.workflow_id,state.id,approval.approval_id,link['plan_version_id'],key,
         request.execution_request_id,sha(request.model_dump_json()),'native',now()))
    return dict(conn.execute('SELECT * FROM workflow_execution_links WHERE execution_id=?',(execution_id,)).fetchone())


def current_execution(conn,state,execution_id,plan_version,approval_id):
    wf=identity(conn,state)
    if wf is None:return None
    link=conn.execute('SELECT * FROM workflow_execution_links WHERE execution_id=?',(execution_id,)).fetchone()
    if (not link or link['workflow_id']!=state.workflow_id or link['approval_id']!=approval_id or
        not state.engine_execution_ids or state.engine_execution_ids[-1]!=execution_id or
        state.current_plan_version!=plan_version or state.dataset_ref is None or state.file.id!=state.dataset_ref.dataset_id):
        raise AppError('WORKFLOW_EXECUTION_STALE','执行已不属于当前流程分支。',409)
    return dict(link)


def branch_hash(state):
    return sha(json.dumps({'workflow_id':state.workflow_id,'root_run_id':state.root_run_id,
        'plan_version':state.current_plan_version,'plan':state.review_plan.model_dump(mode='json') if state.review_plan else None,
        'approval_id':state.engine_approval.approval_id if state.engine_approval else None,
        'executions':state.engine_execution_ids,'dataset':state.dataset_ref.model_dump(mode='json') if state.dataset_ref else None},
        sort_keys=True,ensure_ascii=False,separators=(',',':')))
