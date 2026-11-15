-- Expand only. No business rows, backfill, state routing or old constraints change.
CREATE TABLE workflow_expand_migrations (
    version TEXT NOT NULL PRIMARY KEY, database_kind TEXT NOT NULL,
    checksum TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TRIGGER workflow_expand_version_no_update BEFORE UPDATE ON workflow_expand_migrations
BEGIN SELECT RAISE(ABORT, 'Immutable expand migration'); END;
CREATE TRIGGER workflow_expand_version_no_delete BEFORE DELETE ON workflow_expand_migrations
BEGIN SELECT RAISE(ABORT, 'Preserve expand migration'); END;

CREATE TABLE session_messages (
    message_id TEXT NOT NULL, session_id TEXT NOT NULL REFERENCES sessions(id),
    sequence INTEGER NOT NULL CHECK(sequence >= 1), role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
    workflow_id TEXT,
    PRIMARY KEY(session_id, message_id), UNIQUE(session_id, sequence),
    FOREIGN KEY(session_id, workflow_id) REFERENCES business_workflows(session_id, workflow_id)
);
CREATE TABLE session_datasets (
    session_id TEXT NOT NULL REFERENCES sessions(id), dataset_id TEXT NOT NULL REFERENCES datasets(id),
    created_at TEXT NOT NULL, PRIMARY KEY(session_id, dataset_id)
);
CREATE TABLE business_workflows (
    workflow_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(workflow_id))>0), session_id TEXT NOT NULL REFERENCES sessions(id),
    root_run_id TEXT NOT NULL UNIQUE CHECK(length(trim(root_run_id)) > 0),
    origin_message_id TEXT, parent_workflow_id TEXT, input_file_id TEXT,
    dataset_id TEXT, dataset_version TEXT,
    goal_text TEXT NOT NULL CHECK(length(trim(goal_text)) > 0),
    goal_sha256 TEXT NOT NULL CHECK(length(goal_sha256)=64 AND goal_sha256 NOT GLOB '*[^0-9a-f]*'),
    control_status TEXT NOT NULL CHECK(control_status IN ('CREATED','PREPARING','PROFILING','PARSING_INTENT','PLANNING','VALIDATING','WAITING_FOR_CLARIFICATION','AWAITING_APPROVAL','APPROVED','RUNNING','COMPLETED','FAILED')),
    control_context TEXT NOT NULL CHECK(json_valid(control_context) AND json_type(control_context)='object'),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(typeof(revision)='integer' AND revision>=0),
    active_execution_key TEXT,
    current_plan_version_id TEXT, current_approval_id TEXT, current_execution_id TEXT,
    creation_request_id TEXT NOT NULL CHECK(length(trim(creation_request_id))>0),
    creation_payload_hash TEXT NOT NULL CHECK(length(creation_payload_hash)=64 AND creation_payload_hash NOT GLOB '*[^0-9a-f]*'),
    origin TEXT NOT NULL CHECK(origin IN ('native','legacy_default','legacy_archive')),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, materialized_at TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK(json_valid(provenance) AND json_type(provenance)='object'),
    UNIQUE(session_id, workflow_id), UNIQUE(workflow_id, dataset_id, dataset_version),
    UNIQUE(session_id, creation_request_id),
    CHECK(parent_workflow_id IS NULL OR parent_workflow_id<>workflow_id),
    CHECK(origin<>'native' OR (origin_message_id IS NOT NULL AND input_file_id IS NOT NULL)),
    CHECK((dataset_id IS NULL AND dataset_version IS NULL) OR
          (dataset_id IS NOT NULL AND dataset_version IS NOT NULL AND dataset_id IS input_file_id)),
    FOREIGN KEY(session_id, origin_message_id) REFERENCES session_messages(session_id, message_id),
    FOREIGN KEY(session_id, parent_workflow_id) REFERENCES business_workflows(session_id, workflow_id),
    FOREIGN KEY(session_id, input_file_id) REFERENCES session_datasets(session_id, dataset_id),
    FOREIGN KEY(dataset_id, dataset_version) REFERENCES dataset_profiles(dataset_id, dataset_version),
    FOREIGN KEY(workflow_id, current_plan_version_id) REFERENCES workflow_plan_versions(workflow_id, plan_version_id),
    FOREIGN KEY(workflow_id, current_approval_id) REFERENCES workflow_approval_links(workflow_id, approval_id),
    FOREIGN KEY(workflow_id, current_execution_id) REFERENCES workflow_execution_links(workflow_id, execution_id)
);
CREATE INDEX workflow_session_created ON business_workflows(session_id, created_at, workflow_id);
CREATE TRIGGER workflow_identity_immutable BEFORE UPDATE ON business_workflows
WHEN NEW.workflow_id IS NOT OLD.workflow_id OR NEW.session_id IS NOT OLD.session_id OR
     NEW.root_run_id IS NOT OLD.root_run_id OR NEW.origin_message_id IS NOT OLD.origin_message_id OR
     NEW.parent_workflow_id IS NOT OLD.parent_workflow_id OR NEW.goal_text IS NOT OLD.goal_text OR
     NEW.goal_sha256 IS NOT OLD.goal_sha256 OR NEW.creation_request_id IS NOT OLD.creation_request_id OR
     NEW.creation_payload_hash IS NOT OLD.creation_payload_hash OR NEW.origin IS NOT OLD.origin OR
     NEW.created_at IS NOT OLD.created_at OR NEW.input_file_id IS NOT OLD.input_file_id OR
     (OLD.dataset_id IS NOT NULL AND (NEW.dataset_id IS NOT OLD.dataset_id OR NEW.dataset_version IS NOT OLD.dataset_version))
BEGIN SELECT RAISE(ABORT, 'Workflow identity and pinned dataset are immutable'); END;
CREATE TRIGGER workflow_revision_guard BEFORE UPDATE ON business_workflows
WHEN NEW.revision<>OLD.revision+1
BEGIN SELECT RAISE(ABORT, 'Workflow revision must advance once'); END;
CREATE TRIGGER workflow_history_no_delete BEFORE DELETE ON business_workflows
BEGIN SELECT RAISE(ABORT, 'Preserve workflow history'); END;
CREATE TRIGGER message_identity_immutable BEFORE UPDATE ON session_messages
WHEN NEW.message_id IS NOT OLD.message_id OR NEW.session_id IS NOT OLD.session_id OR
     NEW.sequence IS NOT OLD.sequence OR NEW.role IS NOT OLD.role OR NEW.kind IS NOT OLD.kind OR
     NEW.content IS NOT OLD.content OR NEW.created_at IS NOT OLD.created_at OR
     (OLD.workflow_id IS NOT NULL AND NEW.workflow_id IS NOT OLD.workflow_id)
BEGIN SELECT RAISE(ABORT, 'Message identity and assigned workflow are immutable'); END;

CREATE TABLE workflow_plan_versions (
    plan_version_id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(plan_version_id))>0), workflow_id TEXT NOT NULL, session_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL CHECK(typeof(plan_version)='integer' AND plan_version>=1),
    plan_id TEXT NOT NULL, dataset_id TEXT NOT NULL, dataset_version TEXT NOT NULL,
    validation_version TEXT NOT NULL, payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64 AND payload_hash NOT GLOB '*[^0-9a-f]*'),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('legacy_ref','native')),
    legacy_session_id TEXT, legacy_plan_version INTEGER, record_json TEXT,
    registered_at TEXT NOT NULL,
    UNIQUE(workflow_id, plan_version), UNIQUE(workflow_id, plan_version_id),
    UNIQUE(legacy_session_id, legacy_plan_version),
    CHECK((source_kind='legacy_ref' AND legacy_session_id IS session_id AND legacy_plan_version IS plan_version AND record_json IS NULL) OR
          (source_kind='native' AND legacy_session_id IS NULL AND legacy_plan_version IS NULL AND record_json IS NOT NULL AND json_valid(record_json))),
    CHECK(record_json IS NULL OR (json_extract(record_json,'$.session_id') IS session_id AND
          json_extract(record_json,'$.plan_id') IS plan_id AND json_extract(record_json,'$.plan_version') IS plan_version AND
          json_extract(record_json,'$.dataset_id') IS dataset_id AND json_extract(record_json,'$.dataset_version') IS dataset_version AND
          json_extract(record_json,'$.validation_version') IS validation_version)),
    FOREIGN KEY(session_id, workflow_id) REFERENCES business_workflows(session_id, workflow_id),
    FOREIGN KEY(workflow_id, dataset_id, dataset_version) REFERENCES business_workflows(workflow_id, dataset_id, dataset_version),
    FOREIGN KEY(legacy_session_id, legacy_plan_version) REFERENCES plan_versions(session_id, plan_version)
);
CREATE TRIGGER workflow_legacy_plan_owner BEFORE INSERT ON workflow_plan_versions
WHEN NEW.source_kind='legacy_ref' AND NOT EXISTS (
    SELECT 1 FROM plan_versions p WHERE p.session_id=NEW.legacy_session_id AND p.plan_version=NEW.legacy_plan_version
    AND p.plan_id=NEW.plan_id AND json_extract(p.record,'$.dataset_id') IS NEW.dataset_id
    AND json_extract(p.record,'$.dataset_version') IS NEW.dataset_version
    AND json_extract(p.record,'$.validation_version') IS NEW.validation_version)
BEGIN SELECT RAISE(ABORT, 'Legacy plan reference disagrees with source'); END;
CREATE TRIGGER workflow_plan_no_update BEFORE UPDATE ON workflow_plan_versions
BEGIN SELECT RAISE(ABORT, 'Immutable workflow plan'); END;
CREATE TRIGGER workflow_plan_no_delete BEFORE DELETE ON workflow_plan_versions
BEGIN SELECT RAISE(ABORT, 'Preserve workflow plan'); END;

CREATE UNIQUE INDEX expand_approval_owner ON plan_approvals(approval_id, session_id);
CREATE UNIQUE INDEX expand_execution_owner ON executions(id, session_id);
CREATE TABLE workflow_approval_links (
    approval_id TEXT NOT NULL PRIMARY KEY, workflow_id TEXT NOT NULL, session_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL, client_request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64 AND payload_hash NOT GLOB '*[^0-9a-f]*'),
    snapshot_hash TEXT NOT NULL CHECK(length(snapshot_hash)=64 AND snapshot_hash NOT GLOB '*[^0-9a-f]*'),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('legacy_ref','native')), registered_at TEXT NOT NULL,
    UNIQUE(workflow_id, approval_id), UNIQUE(workflow_id, approval_id, plan_version_id),
    UNIQUE(workflow_id, client_request_id),
    FOREIGN KEY(approval_id, session_id) REFERENCES plan_approvals(approval_id, session_id),
    FOREIGN KEY(session_id, workflow_id) REFERENCES business_workflows(session_id, workflow_id),
    FOREIGN KEY(workflow_id, plan_version_id) REFERENCES workflow_plan_versions(workflow_id, plan_version_id)
);
CREATE TRIGGER workflow_approval_source_guard BEFORE INSERT ON workflow_approval_links
WHEN NOT EXISTS (
    SELECT 1 FROM plan_approvals a JOIN workflow_plan_versions p ON p.plan_version_id=NEW.plan_version_id
    WHERE a.approval_id=NEW.approval_id AND a.session_id=NEW.session_id AND p.workflow_id=NEW.workflow_id
    AND json_extract(a.record,'$.session_id') IS NEW.session_id
    AND json_extract(a.record,'$.plan_id') IS p.plan_id AND json_extract(a.record,'$.plan_version') IS p.plan_version
    AND json_extract(a.record,'$.dataset_id') IS p.dataset_id AND json_extract(a.record,'$.dataset_version') IS p.dataset_version
    AND json_extract(a.record,'$.validation_version') IS p.validation_version
    AND json_extract(a.record,'$.snapshot.approval_id') IS NEW.approval_id
    AND json_extract(a.record,'$.snapshot.validated_plan.plan.plan_id') IS p.plan_id
    AND json_extract(a.record,'$.snapshot.validated_plan.plan.plan_version') IS p.plan_version
    AND json_extract(a.record,'$.snapshot.validated_plan.plan.dataset_id') IS p.dataset_id
    AND json_extract(a.record,'$.snapshot.validated_plan.plan.dataset_version') IS p.dataset_version
    AND (json_extract(a.record,'$.snapshot.session_id') IS NEW.session_id OR
         (NEW.source_kind='legacy_ref' AND json_extract(a.record,'$.snapshot.session_id') IS NULL)))
BEGIN SELECT RAISE(ABORT, 'Approval does not reference workflow plan'); END;
CREATE TABLE workflow_execution_links (
    execution_id TEXT NOT NULL PRIMARY KEY, workflow_id TEXT NOT NULL, session_id TEXT NOT NULL,
    approval_id TEXT NOT NULL, plan_version_id TEXT NOT NULL, dispatch_key TEXT NOT NULL,
    client_request_id TEXT NOT NULL, payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64 AND payload_hash NOT GLOB '*[^0-9a-f]*'),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('legacy_ref','native')), registered_at TEXT NOT NULL,
    UNIQUE(workflow_id, execution_id), UNIQUE(workflow_id, session_id, execution_id),
    UNIQUE(workflow_id, client_request_id),
    FOREIGN KEY(execution_id, session_id) REFERENCES executions(id, session_id),
    FOREIGN KEY(session_id, workflow_id) REFERENCES business_workflows(session_id, workflow_id),
    FOREIGN KEY(workflow_id, approval_id, plan_version_id) REFERENCES workflow_approval_links(workflow_id, approval_id, plan_version_id)
);
CREATE TRIGGER workflow_execution_source_guard BEFORE INSERT ON workflow_execution_links
WHEN NOT EXISTS (
    SELECT 1 FROM executions e JOIN workflow_plan_versions p ON p.plan_version_id=NEW.plan_version_id
    WHERE e.id=NEW.execution_id AND e.session_id=NEW.session_id AND p.workflow_id=NEW.workflow_id
    AND json_extract(e.request,'$.session_id') IS NEW.session_id
    AND json_extract(e.request,'$.plan_id') IS p.plan_id AND json_extract(e.request,'$.plan_version') IS p.plan_version
    AND json_extract(e.approval,'$.approval_id') IS NEW.approval_id
    AND json_extract(e.approval,'$.validated_plan.plan.plan_id') IS p.plan_id
    AND json_extract(e.approval,'$.validated_plan.plan.plan_version') IS p.plan_version
    AND json_extract(e.approval,'$.validated_plan.plan.dataset_id') IS p.dataset_id
    AND json_extract(e.approval,'$.validated_plan.plan.dataset_version') IS p.dataset_version
    AND (e.result IS NULL OR (json_extract(e.result,'$.execution_id') IS NEW.execution_id
         AND json_extract(e.result,'$.session_id') IS NEW.session_id
         AND json_extract(e.result,'$.approval_id') IS NEW.approval_id)))
BEGIN SELECT RAISE(ABORT, 'Execution does not reference workflow approval'); END;
CREATE TABLE workflow_report_links (
    report_id TEXT NOT NULL PRIMARY KEY REFERENCES analysis_reports(id), workflow_id TEXT NOT NULL,
    session_id TEXT NOT NULL, execution_id TEXT NOT NULL,
    accepted_report_attempt INTEGER NOT NULL CHECK(typeof(accepted_report_attempt)='integer' AND accepted_report_attempt>=1),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('legacy_ref','native')), registered_at TEXT NOT NULL,
    UNIQUE(workflow_id, report_id),
    FOREIGN KEY(workflow_id, session_id, execution_id) REFERENCES workflow_execution_links(workflow_id, session_id, execution_id)
);
CREATE TRIGGER workflow_report_source_guard BEFORE INSERT ON workflow_report_links
WHEN NOT EXISTS (
    SELECT 1 FROM analysis_reports r JOIN workflow_execution_links e ON e.execution_id=NEW.execution_id
    JOIN workflow_plan_versions p ON p.plan_version_id=e.plan_version_id
    WHERE r.id=NEW.report_id AND e.workflow_id=NEW.workflow_id AND e.session_id=NEW.session_id
    AND json_extract(r.report,'$.report_id') IS NEW.report_id
    AND json_extract(r.report,'$.execution_source') IS 'engine'
    AND json_extract(r.report,'$.execution_id') IS NEW.execution_id
    AND json_extract(r.report,'$.plan_version') IS p.plan_version
    AND json_extract(r.report,'$.dataset_id') IS p.dataset_id AND json_extract(r.report,'$.dataset_version') IS p.dataset_version
    AND json_extract(r.audit,'$.session_id') IS NEW.session_id AND json_extract(r.audit,'$.approval_id') IS e.approval_id
    AND json_extract(r.audit,'$.execution_id') IS NEW.execution_id AND json_extract(r.audit,'$.plan_id') IS p.plan_id
    AND (NEW.source_kind='legacy_ref' OR EXISTS (SELECT 1 FROM report_generations g
         WHERE g.execution_id=NEW.execution_id AND g.status IN ('completed','unavailable')
         AND json_extract(g.record,'$.report_id') IS NEW.report_id
         AND json_extract(g.record,'$.attempt') IS NEW.accepted_report_attempt)))
BEGIN SELECT RAISE(ABORT, 'Report does not reference workflow execution'); END;
CREATE TRIGGER workflow_approval_no_update BEFORE UPDATE ON workflow_approval_links
BEGIN SELECT RAISE(ABORT, 'Immutable approval binding'); END;
CREATE TRIGGER workflow_approval_no_delete BEFORE DELETE ON workflow_approval_links
BEGIN SELECT RAISE(ABORT, 'Preserve approval binding'); END;
CREATE TRIGGER workflow_execution_no_update BEFORE UPDATE ON workflow_execution_links
BEGIN SELECT RAISE(ABORT, 'Immutable execution binding'); END;
CREATE TRIGGER workflow_execution_no_delete BEFORE DELETE ON workflow_execution_links
BEGIN SELECT RAISE(ABORT, 'Preserve execution binding'); END;
CREATE TRIGGER workflow_report_no_update BEFORE UPDATE ON workflow_report_links
BEGIN SELECT RAISE(ABORT, 'Immutable report binding'); END;
CREATE TRIGGER workflow_report_no_delete BEFORE DELETE ON workflow_report_links
BEGIN SELECT RAISE(ABORT, 'Preserve report binding'); END;

CREATE TABLE session_workflow_routes (
    session_id TEXT NOT NULL PRIMARY KEY REFERENCES sessions(id),
    mode TEXT NOT NULL CHECK(mode IN ('legacy','shadow','workflow_v2')),
    default_workflow_id TEXT, migration_version TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(session_id, default_workflow_id) REFERENCES business_workflows(session_id, workflow_id)
);
CREATE TABLE workflow_backfill_items (
    source_type TEXT NOT NULL, source_key TEXT NOT NULL, decision_version INTEGER NOT NULL CHECK(decision_version>=1),
    source_hash TEXT NOT NULL CHECK(length(source_hash)=64 AND source_hash NOT GLOB '*[^0-9a-f]*'),
    workflow_id TEXT REFERENCES business_workflows(workflow_id),
    status TEXT NOT NULL CHECK(status IN ('proposed','verified','unresolved','conflict','failed')),
    rule_version TEXT NOT NULL, evidence TEXT NOT NULL CHECK(json_valid(evidence)),
    error_code TEXT, recorded_at TEXT NOT NULL,
    PRIMARY KEY(source_type, source_key, decision_version)
);
CREATE TRIGGER workflow_backfill_no_update BEFORE UPDATE ON workflow_backfill_items
BEGIN SELECT RAISE(ABORT, 'Append a new backfill decision'); END;
CREATE TRIGGER workflow_backfill_no_delete BEFORE DELETE ON workflow_backfill_items
BEGIN SELECT RAISE(ABORT, 'Preserve backfill decisions'); END;
