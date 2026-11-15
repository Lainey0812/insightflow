"""Browser regression harness over the original C2 databases. No schema init, recovery or LLM."""
import sys,sqlite3,hashlib,json
from pathlib import Path
from types import SimpleNamespace
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');sys.path.insert(0,str(root/'backend'))
from fastapi import FastAPI
from app.api.admin import create_admin_router
from app.api.errors import install_error_handlers
from app.storage.trace_repository import TraceRepository
from app.storage.prompt_registry import PromptRegistryRepository
from app.storage.report_repository import ReportRepository
from app.observability.recorder import TraceRecorder
from app.services.workflow_trace import WorkflowTraceService
from app.services.workflow_observability import WorkflowObservabilityService
source=root/'var/verification/c2-closure-release03'
artifact=root/'docs/implementations/admin-workflow-observability-2026-10-31'
def connect(path):
 conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
 conn.execute('PRAGMA query_only=ON');return conn
class ReadOnlyBusiness:
 path=source/'insightflow.sqlite3'
 def connect(self):return connect(self.path)
class ReadOnlyTrace(TraceRepository):
 def __init__(self):self.path=source/'observability/trace.sqlite3'
 def connect(self):return connect(self.path)
class ReadOnlyRegistry(PromptRegistryRepository):
 def __init__(self):self.path=source/'prompt_registry/registry.sqlite3'
 def connect(self):return connect(self.path)
class ReadOnlyReports(ReportRepository):
 def __init__(self):self.database=ReadOnlyBusiness()

def digest_databases():
 out={}
 for name,path in [('business',ReadOnlyBusiness.path),('trace',ReadOnlyTrace().path),('registry',ReadOnlyRegistry().path)]:
  with connect(path) as conn:
   tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
   data={t:[tuple(r) for r in conn.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}
  out[name]=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
 return out
sessions=SimpleNamespace(database=ReadOnlyBusiness())
recorder=TraceRecorder(None if '--trace-off' in sys.argv else ReadOnlyTrace());captures=SimpleNamespace(repository=ReadOnlyRegistry())
trace=WorkflowTraceService(sessions,recorder,captures);views=WorkflowObservabilityService(trace)
app=FastAPI(title='InsightFlow Admin fixed C2 sample / readonly')
router=create_admin_router(recorder,ReadOnlyReports(),'verification-read',captures,local_test_mode=True,workflow_trace=trace,workflow_observability=views)
app.include_router(router);app.include_router(router,prefix='/api/v1',include_in_schema=False);install_error_handlers(app)
if __name__=='__main__':
 if '--digest' in sys.argv:print(json.dumps(digest_databases()));sys.exit()
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=8006 if '--trace-off' in sys.argv else 8005)
