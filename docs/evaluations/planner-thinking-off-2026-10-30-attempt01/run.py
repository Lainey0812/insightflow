"""Single exact saved-payload replay; not a frontend Workflow run."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'backend'))

from app.domain.analysis_plan import AnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.domain.prompt_registry import CallBinding
from app.llm.base import LLMRequest
from app.llm.capture import CallRecorder
from app.llm.compatible_provider import CompatibleLLMProvider
from app.observability.provenance import digest
from app.planning.capabilities import CapabilityRegistry
from app.planning.output import validate_draft
from app.planning.validator import PlanValidator
from app.storage.prompt_registry import PromptRegistryRepository


def save(name, value):
    with (OUT / name).open('x') as file:
        file.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


async def main():
    # Parse literal env assignments without executing shell substitutions or printing credentials.
    env_bytes = (ROOT / 'backend/.env').read_bytes()
    config = {}
    for line in env_bytes.decode().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, text = line.removeprefix('export ').partition('=')
        if sep:
            parts = shlex.split(text, comments=True)
            config[key.strip()] = ' '.join(parts)
    config.update({k: v for k, v in os.environ.items() if k.startswith('INSIGHTFLOW_')})
    repo = PromptRegistryRepository(ROOT / 'var/prompt_registry')
    source_id = 'request_09602ba75f6943a8ae0d5f1d6f1c277f'
    snapshot = repo.snapshot(source_id)
    payload = repo.payload(source_id)
    assert snapshot and payload
    assert payload['model'] == config['INSIGHTFLOW_LLM_MODEL']
    endpoint = config['INSIGHTFLOW_LLM_BASE_URL'].rstrip('/') + '/chat/completions'
    assert hashlib.sha256(endpoint.encode()).hexdigest() == snapshot.client_config['endpoint_sha256']
    operation = 'diagnostic_thinking_off_' + uuid4().hex
    provider = CompatibleLLMProvider(config['INSIGHTFLOW_LLM_BASE_URL'], payload['model'],
        api_key=config.get('INSIGHTFLOW_LLM_API_KEY', ''), timeout=60,
        capture=CallRecorder(repo))
    schema = payload['response_format']['json_schema']
    request = LLMRequest(purpose=schema['name'], system_prompt=payload['messages'][0]['content'],
        instruction=payload['messages'][1]['content'], response_schema=schema['schema'],
        enable_thinking=False, call_binding=CallBinding(
            template=repo.template(snapshot.template_snapshot_id), operation_id=operation,
            call_sequence=1, retry_index=0))
    expected = dict(payload, enable_thinking=False)
    assert provider.build_payload(request) == expected
    result = {'started_at': datetime.now(timezone.utc).isoformat(), 'purpose': 'same messages/schema, explicit thinking disabled diagnostic',
        'source_request_snapshot_id': source_id, 'operation_id': operation,
        'original_timeout_seconds': snapshot.client_config['timeout_seconds'], 'diagnostic_timeout_seconds': 60, 'diagnostic_enable_thinking': False,
        'template_snapshot_id': snapshot.template_snapshot_id, 'request_hash': digest(payload),
        'source_payload_verified': digest(payload) == snapshot.request_hash, 'diagnostic_request_hash': digest(expected), 'only_payload_change': 'enable_thinking=false', 'model_parameters': snapshot.model_parameters,
        'run_id': None, 'span_id': None, 'application_configuration_changed': False}
    save('started.json', result)
    start = perf_counter()
    try:
        async with asyncio.timeout(60):
            response = await provider.generate(request)
        result.update(model_status='succeeded', elapsed_seconds=perf_counter()-start,
            call_id=response.call_id, request_snapshot_id=response.request_snapshot_id)
        with (OUT / 'raw-model-output.txt').open('x') as file:
            file.write(response.text)
        registry = CapabilityRegistry()
        draft = validate_draft(response.text, registry)
        result['draft_schema_status'] = 'passed'
        # Reuse the original profile and app-generated core requirements, never synthesize data.
        context = json.loads(payload['messages'][1]['content'])
        with sqlite3.connect('file:' + str(ROOT / 'var/insightflow.sqlite3') + '?mode=ro', uri=True) as conn:
            states = [json.loads(r[0]) for r in conn.execute('SELECT state FROM sessions')]
        profile = next(DatasetProfile.model_validate(s['profile']) for s in states if s.get('profile') and s['profile']['dataset_id'] == context['profile']['dataset_id'])
        context = json.loads(payload['messages'][1]['content'])
        plan = AnalysisPlan(plan_id='diagnostic_plan_' + uuid4().hex, dataset_id=profile.dataset_id,
            dataset_version=profile.dataset_version, plan_version=1, tasks=draft.tasks,
            core_requirements=context['core_requirements'])
        validated = PlanValidator(registry).validate(plan, profile)
        save('validated-plan.json', validated.model_dump(mode='json'))
        result.update(validator_coverage=validated.coverage_status, executable_task_ids=validated.executable_task_ids,
            blocked_task_ids=validated.blocked_task_ids, validation_results=[r.model_dump() for r in validated.validation_results])
    except BaseException as error:
        result['elapsed_seconds'] = perf_counter()-start
        code = getattr(getattr(error, 'error', None), 'code', None)
        result.update(diagnostic_error_code=code or ('LLM_TIMEOUT' if isinstance(error, TimeoutError) else type(error).__name__))
        result.setdefault('model_status', 'failed')
        result['error_stage'] = 'post_response_validation' if 'call_id' in result else 'provider_wait'
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        records = repo.calls(operation_id=operation)
        result['calls'] = [c.model_dump(mode='json') for c in records]
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        assert (ROOT / 'backend/.env').read_bytes() == env_bytes
        save('result.json', result)
        print(json.dumps({k: result.get(k) for k in ['model_status','elapsed_seconds','diagnostic_error_code',
            'draft_schema_status','validator_coverage','call_id','request_snapshot_id']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
