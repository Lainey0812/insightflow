"""Isolated SQLite protocol tests, not a production Report writer or migration.

The child commits all protocol records then exits without returning accepted.
Recovery uses a fresh readonly transaction, never the child's in-memory result.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from app.domain.workflow_policy import WorkflowPolicyValidatorV12
from app.domain.workflow_policy.models import BusinessFact, PolicyCommand
from app.domain.workflow_policy.validator_v12 import PolicySnapshotV12
from app.domain.workflow_policy.report_commit import (
    CommitMetadata, CommitRecords, CompletionSpan, ReportOwnership, reconcile_report_commit)
from workflow_policy_v12_fixtures import authorization_case, observation_case


CHILD = r'''
import json,os,sqlite3,sys
path,config_path,point=sys.argv[1:]
v=json.load(open(config_path))
c=sqlite3.connect(path);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL')
c.execute('BEGIN IMMEDIATE')
w=c.execute('SELECT revision,active_key FROM protocol_workflows WHERE workflow_id=?',(v['workflow_id'],)).fetchone()
assert w==(v['authorized_revision'],v['authorized_key'])
g=json.loads(c.execute('SELECT record FROM protocol_generations WHERE execution_id=?',(v['execution_id'],)).fetchone()[0])
assert g['generation_status']=='generating' and g['binding']==v['generation']['binding']
c.execute('INSERT INTO protocol_reports VALUES (?,?,?,?,?)',(
    v['report_id'],v['workflow_id'],v['payload'],json.dumps(v['report']),json.dumps(v['metadata'])))
if point=='after_report':os._exit(71)
c.execute('UPDATE protocol_generations SET record=? WHERE execution_id=?',(json.dumps(v['generation']),v['execution_id']))
if point=='after_generation':os._exit(71)
c.execute('INSERT INTO protocol_ownership VALUES (?,?,?,?)',(
    v['report_id'],v['workflow_id'],v['execution_id'],json.dumps(v['ownership'])))
changed=c.execute('UPDATE protocol_workflows SET revision=?,active_key=NULL WHERE workflow_id=? AND revision=? AND active_key=?',(
    v['committed_revision'],v['workflow_id'],v['authorized_revision'],v['authorized_key'])).rowcount
assert changed==1
c.commit()
os._exit(71)  # Crash after COMMIT and before any accepted=True response.
'''


def prepare(tmp_path):
    s,c=observation_case()
    # A reader computes the digest from actual persisted payload, not a hash
    # claimed by a stored projection or received from a model.
    payload=json.dumps({'report_id':s.authorization.report_id,'execution_id':s.binding.execution_id,
                        'finding':'synthetic test payload'},sort_keys=True,separators=(',',':'))
    digest=sha256(payload.encode()).hexdigest()
    pre_snapshot,pre_command=authorization_case()
    pre_command=pre_command.model_copy(update={'facts':(pre_command.facts[0].model_copy(update={'digest':digest}),)})
    assert WorkflowPolicyValidatorV12().validate(pre_snapshot,pre_command).decision=='allow'
    auth=s.authorization.model_copy(update={'report_digest':digest,'payload_hash':pre_command.payload_hash()})
    report=s.commit_records.report.model_copy(update={'digest':digest})
    metadata=s.commit_records.metadata.model_copy(update={'authorization':auth})
    span=s.completion_span.model_copy(update={'report_digest':digest,'commit_payload_hash':auth.payload_hash})
    s=s.model_copy(update={'authorization':auth,'completion_span':span,
        'commit_records':s.commit_records.model_copy(update={'report':report,'metadata':metadata})})
    g=s.commit_records.generation
    pending=g.model_copy(update={'generation_status':'generating','report_id':None})
    path=tmp_path/'protocol.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('CREATE TABLE protocol_workflows (workflow_id TEXT PRIMARY KEY,session_id TEXT,revision INTEGER,active_key TEXT)')
        conn.execute('CREATE TABLE protocol_generations (execution_id TEXT PRIMARY KEY,workflow_id TEXT REFERENCES protocol_workflows(workflow_id),record TEXT)')
        conn.execute('CREATE TABLE protocol_reports (report_id TEXT PRIMARY KEY,workflow_id TEXT REFERENCES protocol_workflows(workflow_id),payload TEXT,projection TEXT,audit TEXT)')
        conn.execute('CREATE TABLE protocol_ownership (report_id TEXT PRIMARY KEY REFERENCES protocol_reports(report_id),workflow_id TEXT REFERENCES protocol_workflows(workflow_id),execution_id TEXT REFERENCES protocol_generations(execution_id),record TEXT)')
        conn.execute('INSERT INTO protocol_workflows VALUES (?,?,?,?)',(s.workflow_id,s.session_id,auth.authorized_revision,auth.authorized_active_key))
        conn.execute('INSERT INTO protocol_generations VALUES (?,?,?)',(s.binding.execution_id,s.workflow_id,pending.model_dump_json()))
    config={'workflow_id':s.workflow_id,'execution_id':s.binding.execution_id,'report_id':report.fact_id,
            'authorized_revision':auth.authorized_revision,'authorized_key':auth.authorized_active_key,
            'committed_revision':metadata.committed_revision,'payload':payload,'report':report.model_dump(mode='json'),
            'generation':g.model_dump(mode='json'),'ownership':s.commit_records.ownership.model_dump(mode='json'),
            'metadata':metadata.model_dump(mode='json')}
    file=tmp_path/'input.json';file.write_text(json.dumps(config))
    return s,c,path,file


def read_records(path,auth=None,*,execution_id=None):
    # This function intentionally exists only in tests. A production reader is
    # still a separately reviewed integration task.
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        if auth is None:
            # Recovery starts from a durable execution ID, not a surviving call
            # object. Discover the report and authorization in this same read.
            initial=conn.execute('SELECT record FROM protocol_generations WHERE execution_id=?',(execution_id,)).fetchone()
            generation=BusinessFact.model_validate_json(initial[0])
            audit=conn.execute('SELECT audit FROM protocol_reports WHERE report_id=?',(generation.report_id,)).fetchone()
            auth=CommitMetadata.model_validate_json(audit[0]).authorization
            assert auth.binding.execution_id==execution_id
        row=conn.execute('SELECT payload,projection,audit FROM protocol_reports WHERE report_id=?',(auth.report_id,)).fetchone()
        g=conn.execute('SELECT record FROM protocol_generations WHERE execution_id=?',(auth.binding.execution_id,)).fetchone()
        link=conn.execute('SELECT record FROM protocol_ownership WHERE report_id=?',(auth.report_id,)).fetchone()
        w=conn.execute('SELECT revision,active_key FROM protocol_workflows WHERE workflow_id=?',(auth.workflow_id,)).fetchone()
        report=None;metadata=None
        if row:
            report=BusinessFact.model_validate_json(row[1]).model_copy(update={'digest':sha256(row[0].encode()).hexdigest()})
            metadata=CommitMetadata.model_validate_json(row[2])
        records=CommitRecords(read_consistency='transactional',writer_isolated=True,report=report,
            generation=BusinessFact.model_validate_json(g[0]) if g else None,
            ownership=ReportOwnership.model_validate_json(link[0]) if link else None,metadata=metadata)
        return records,w
    finally:conn.close()


@pytest.mark.parametrize('point',['after_report','after_generation','after_commit'])
def test_real_process_exit_atomicity_and_lost_ack_recovery(tmp_path,point):
    s,c,path,file=prepare(tmp_path)
    child=subprocess.run([sys.executable,'-c',CHILD,str(path),str(file),point],capture_output=True,text=True,timeout=10)
    assert child.returncode==71 and child.stdout==''
    assert child.stderr=='',child.stderr
    records,w=read_records(path,s.authorization)
    result=reconcile_report_commit(s.authorization,records)
    if point=='after_commit':
        assert result.accepted is True and result.reason_code=='COMMIT_PERSISTED'
        s=s.model_copy(update={'commit_records':records,'revision':w[0],'active_execution_key':w[1]})
        decision=WorkflowPolicyValidatorV12().validate(s,c)
        assert decision.action=='observe' and decision.expected_transition.owner=='span'
        assert w[1] is None
        assert read_records(path,s.authorization)[0]==records
    else:
        assert records.report is records.ownership is records.metadata is None
        assert records.generation.generation_status=='generating'
        assert result.accepted is False and result.reason_code=='COMMIT_ABSENCE_VERIFIED'
        assert w[0]==s.authorization.authorized_revision
        assert WorkflowPolicyValidatorV12().validate(s.model_copy(update={'commit_records':records}),c).decision=='deny'


def test_partial_or_corrupt_commit_is_not_guessed_success(tmp_path):
    s,c,path,file=prepare(tmp_path)
    child=subprocess.run([sys.executable,'-c',CHILD,str(path),str(file),'after_commit'],capture_output=True,timeout=10)
    assert child.returncode==71
    with sqlite3.connect(path) as conn:
        # Simulate damage, not a normal writer: persisted payload no longer has
        # the hash committed in audit/target Span.
        conn.execute('UPDATE protocol_reports SET payload=?',('changed content',))
    records,_=read_records(path,s.authorization)
    result=reconcile_report_commit(s.authorization,records)
    assert result.accepted is None and result.status=='inconsistent'
    assert result.reason_code=='COMMIT_REPORT_MISMATCH'
    assert WorkflowPolicyValidatorV12().validate(s.model_copy(update={'commit_records':records}),c).decision=='deny'


def test_missing_return_alone_is_not_evidence_of_failure():
    s,c=observation_case()
    result=reconcile_report_commit(s.authorization,None)
    assert result.status=='unknown' and result.accepted is None
    # There is deliberately no callback_received/accepted parameter to set false.
    assert WorkflowPolicyValidatorV12().validate(s.model_copy(update={'commit_records':None}),c).reason_code=='POLICY_COMMIT_NOT_CONFIRMED'


def test_recovery_reconstructs_authorization_when_all_call_memory_is_gone(tmp_path):
    s,c,path,file=prepare(tmp_path)
    execution_id=s.binding.execution_id
    trace_path=tmp_path/'saved-span.json'
    trace_path.write_text(s.completion_span.model_dump_json())
    child=subprocess.run([sys.executable,'-c',CHILD,str(path),str(file),'after_commit'],capture_output=True,timeout=10)
    assert child.returncode==71 and child.stdout==b''
    del s,c  # No callback receipt, authorization object, or live request survives.
    records,w=read_records(path,execution_id=execution_id)
    recovered=records.metadata.authorization
    verdict=reconcile_report_commit(recovered,records)
    assert verdict.accepted is True
    snapshot=PolicySnapshotV12(session_id=recovered.session_id,workflow_id=recovered.workflow_id,
        root_run_id=recovered.root_run_id,revision=w[0],active_execution_key=w[1],control_status='COMPLETED',
        binding=recovered.binding,authorization=recovered,commit_records=records,
        completion_span=CompletionSpan.model_validate_json(trace_path.read_text()))
    command=PolicyCommand(command_id='C19-B',session_id=recovered.session_id,workflow_id=recovered.workflow_id,
        request_id=recovered.request_id,expected_revision=recovered.authorized_revision,
        active_execution_key=recovered.authorized_active_key,binding=recovered.binding)
    decision=WorkflowPolicyValidatorV12().validate(snapshot,command)
    assert decision.action=='observe' and decision.expected_transition.owner=='span'
