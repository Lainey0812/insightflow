from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install_error_handlers
from app.api.admin import create_admin_router
from app.storage.trace_repository import TraceRepository
from app.observability.recorder import TraceRecorder
from app.api.routes import create_router
from app.api.datasets import create_dataset_router
from app.api.intents import create_intent_router
from app.api.plans import create_plan_router
from app.api.reports import create_report_router
from app.api.executions import create_execution_router
from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.factory import create_provider
from app.llm.compatible_provider import CompatibleLLMProvider
from app.llm.capture import CallRecorder
from app.storage.prompt_registry import PromptRegistryRepository
from app.services.plan_review import PlanReviewService
from app.services.data_profiler import DataProfilerService
from app.services.intent_parser import IntentParserService
from app.services.analysis_planner import AnalysisPlannerService
from app.services.analysis_report import AnalysisReportService
from app.services.analysis_engine import AnalysisEngineService
from app.services.prompt_registration import register_loaded_templates
from app.storage.execution_repository import ExecutionRepository
from app.storage.report_repository import ReportRepository
from app.planning.capabilities import CapabilityRegistry
from app.storage.dataset_repository import DatasetRepository
from app.storage.database import Database
from app.storage.file_store import FileStore
from app.storage.session_repository import SessionRepository
from app.storage.lifecycle_reader import LifecycleReader
from app.services.lifecycle import LifecycleService
from app.workflow.orchestrator import WorkflowOrchestrator
from app.workflow.reporting import ReportWorkflow


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None, *,
               bootstrap_identity: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    repository = SessionRepository(Database(settings.data_dir))
    files = FileStore(settings.data_dir, settings.max_upload_bytes)
    datasets = DatasetRepository(repository.database)
    profiler = DataProfilerService(files, datasets)
    llm = provider or create_provider(settings)
    captures = CallRecorder(retention_days=settings.llm_request_retention_days)
    try:
        captures.repository = PromptRegistryRepository(settings.data_dir / 'prompt_registry')
    except Exception:
        import logging
        logging.getLogger('app.llm.capture').error('Prompt registry unavailable; HTTP LLM requests will be blocked')
    if isinstance(llm,CompatibleLLMProvider):
        llm.capture = captures
    parser = IntentParserService(llm, settings.llm_timeout_seconds, max_attempts=settings.intent_max_attempts,
                                 enable_thinking=settings.intent_enable_thinking)
    registry = CapabilityRegistry()
    planner = AnalysisPlannerService(llm, registry, settings.llm_timeout_seconds,
        max_attempts=settings.planner_max_attempts, enable_thinking=settings.planner_enable_thinking)
    report_service = AnalysisReportService(llm, registry, settings.llm_timeout_seconds, settings.report_enable_thinking)
    prompt_sources={key:service.prompt_source for key,service in
        [('intent_parser',parser),('analysis_planner',planner),('insight_generator',report_service)] if service.prompt_source}
    reports = ReportRepository(repository.database)
    executions = ExecutionRepository(repository.database)
    traces = TraceRecorder()
    if settings.trace_enabled:
        try:
            traces.repository = TraceRepository(settings.data_dir / 'observability')
        except Exception:
            import logging
            traces.degraded = True
            logging.getLogger('app.trace').warning('Trace initialization failed; business remains available; observations may be missing')
    reporting = ReportWorkflow(repository, datasets, executions, reports, report_service, traces)
    engine = AnalysisEngineService(repository,datasets,files,executions,registry)
    review = PlanReviewService(repository, datasets, registry, files)
    from app.storage.workflow_expand import apply_expand
    from app.storage.workflow_identity import WorkflowIdentityRepository
    # Explicit opt-out exists for pre-Expand compatibility fixtures/embedders only.
    # The deployed application always enables identity bootstrap.
    if bootstrap_identity:
        apply_expand(repository.database.path, 'business')
    identities = WorkflowIdentityRepository(repository.database) if bootstrap_identity else None
    from app.observability.hitl import HITLObserver
    review.observations = HITLObserver(repository, identities, traces) if identities else None
    from app.observability.downstream import DownstreamObserver
    downstream = DownstreamObserver(repository,executions,traces)
    engine.observations = downstream
    reporting.observations = downstream
    workflow = WorkflowOrchestrator(repository, parser, profiler, planner, review, traces, identities)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        engine.recover_interrupted()
        workflow.recover_interrupted()
        reports.recover_interrupted()
        traces.recover()
        if captures.repository:
            try:
                captures.repository.recover()
                captures.repository.prune_expired()
            except Exception:
                import logging
                logging.getLogger('app.llm.capture').error('Prompt registry recovery failed; HTTP calls blocked')
                captures.repository = None
        app.state.prompt_registration = register_loaded_templates(captures.repository, prompt_sources)
        yield

    app = FastAPI(title="InsightFlow", version="0.1.0", lifespan=lifespan,
                  description="Real Workflow V1: profile → intent → planner → validation → HITL → engine. real_workflow=true; manual_review=true retains manual import; legacy sessions stay isolated.")
    app.state.traces = traces
    app.state.llm_captures = captures
    app.state.repository = repository
    app.state.workflow = workflow
    app.state.datasets = datasets
    app.state.profiler = profiler
    app.state.intent_parser = parser
    app.state.analysis_planner = planner
    app.state.capability_registry = registry
    app.state.report_service = report_service
    app.state.reports = reports
    app.state.report_workflow = reporting
    app.state.executions = executions
    app.state.analysis_engine = engine
    app.state.plan_review = review
    app.include_router(create_router(repository, files, workflow, review))
    app.include_router(create_dataset_router(files, datasets, profiler, repository))
    app.include_router(create_intent_router(parser, datasets))
    app.include_router(create_plan_router(planner, datasets, registry))
    app.include_router(create_report_router(report_service, datasets, reports, executions))
    app.include_router(create_execution_router(engine,executions,reporting))
    runtime_templates={key:source.snapshot.template_snapshot_id for key,source in prompt_sources.items()}
    lifecycle = LifecycleService(LifecycleReader(repository.database.path, settings.data_dir / 'observability' / 'trace.sqlite3'))
    app.state.lifecycle = lifecycle
    from app.services.workflow_trace import WorkflowTraceService
    workflow_trace = WorkflowTraceService(repository,traces,captures)
    app.state.workflow_trace = workflow_trace
    from app.services.workflow_observability import WorkflowObservabilityService
    workflow_observability = WorkflowObservabilityService(workflow_trace)
    app.state.workflow_observability = workflow_observability
    admin_router = create_admin_router(traces, reports, settings.admin_read_token,captures,settings.admin_snapshot_token,runtime_templates,
                                      local_test_mode=settings.admin_local_test_mode, lifecycle=lifecycle, workflow_trace=workflow_trace, workflow_observability=workflow_observability)
    app.include_router(admin_router)
    app.include_router(admin_router, prefix='/api/v1', include_in_schema=False)
    install_error_handlers(app)
    return app


app = create_app()
