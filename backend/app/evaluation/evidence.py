"""Read-only evidence for one case of an indexed run.

Callers pass the run directory found by the run index and a kind from a fixed list. Each kind maps
to a fixed relative file inside the run, resolved through integrity.contained_path. Request values
never form a path. Only JSON files are read; SQLite is never opened. Nothing is written.

Redaction runs on every returned value:
- Keys that name a secret or connection credential are replaced.
- Keys that hold an endpoint or URL are removed, and any http(s) URL inside a string is replaced.
- Raw user text keys keep only their length and SHA-256.
- Absolute local paths inside strings are replaced.
Limits: raw file size, total JSON values, and nesting depth. Depth is cut with a marker; the other
two raise EvidenceTooLarge.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .integrity import contained_path
from .runs import RunView

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_VALUES = 50000
MAX_DEPTH = 24

EVIDENCE_KINDS = ('trace', 'plan', 'profile', 'engine', 'result_tables', 'evaluator_refs')
OBSERVED_FIELD = {'plan': 'plan', 'profile': 'profile', 'engine': 'execution_steps', 'result_tables': 'result_tables'}

SECRET_KEY = re.compile(r'(?i)^(?:.*[_-])?(api[_-]?key|apikey|authorization|secret|client[_-]?secret|password|passwd|'
                        r'token|access[_-]?token|refresh[_-]?token|id[_-]?token|session[_-]?token|cookie|set[_-]?cookie|'
                        r'credential|credentials|private[_-]?key|dsn|connection[_-]?string|database[_-]?url)$')
ENDPOINT_KEY = re.compile(r'(?i)^(endpoint|base[_-]?url|api[_-]?base|url|uri|host|.*[_-]url)$')
USER_TEXT_KEY = re.compile(r'(?i)^(user_query|user_input|raw_query|original_query|query_text|messages|prompt|prompt_text|'
                           r'completion|raw_request|raw_response|request_body|response_body)$')
URL = re.compile(r'(?i)\b(?:https?|wss?)://[^\s"\'<>]+')
BEARER = re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}')
KEY_LIKE = re.compile(r'\b(?:sk|pk|ak)-[A-Za-z0-9_-]{16,}\b')
LOCAL_PATH = re.compile(r'(?<![\w.])/(?:Users|home|private|var/folders|tmp|opt|root|Volumes)/[^\s"\'<>]*')


class EvidenceTooLarge(Exception):
    def __init__(self, reason: str, limit: int, actual: int | None = None):
        super().__init__(reason)
        self.reason, self.limit, self.actual = reason, limit, actual


@dataclass
class Redactor:
    redactions: dict[tuple[str, str], int] = field(default_factory=dict)
    depth_cuts: list[str] = field(default_factory=list)
    values: int = 0

    def _note(self, path: str, rule: str):
        key = (re.sub(r'\[\d+\]', '[*]', path), rule)
        self.redactions[key] = self.redactions.get(key, 0) + 1

    def _text(self, value: str, path: str) -> str:
        cleaned = value
        for pattern, rule, marker in ((URL, 'url_in_text_replaced', '[redacted:url]'),
                                      (BEARER, 'bearer_replaced', '[redacted:credential]'),
                                      (KEY_LIKE, 'key_like_replaced', '[redacted:credential]'),
                                      (LOCAL_PATH, 'local_path_replaced', '[redacted:path]')):
            cleaned, count = pattern.subn(marker, cleaned)
            if count:
                self._note(path, rule)
        return cleaned

    def clean(self, value: Any, path: str = '$', depth: int = 0) -> Any:
        self.values += 1
        if self.values > MAX_VALUES:
            raise EvidenceTooLarge('too_many_values', MAX_VALUES)
        if isinstance(value, (dict, list)) and depth >= MAX_DEPTH:
            self.depth_cuts.append(re.sub(r'\[\d+\]', '[*]', path))
            return {'__truncated__': 'max_depth', 'max_depth': MAX_DEPTH}
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                key = str(key)
                child = f'{path}.{key}'
                if SECRET_KEY.match(key):
                    self._note(child, 'secret_key_replaced')
                    out[key] = '[redacted:credential]'
                elif ENDPOINT_KEY.match(key):
                    self._note(child, 'endpoint_removed')
                elif USER_TEXT_KEY.match(key) and item is not None:
                    self._note(child, 'user_text_minimized')
                    text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
                    out[key] = {'redacted': 'user_text', 'chars': len(text),
                                'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
                else:
                    out[key] = self.clean(item, child, depth + 1)
            return out
        if isinstance(value, list):
            return [self.clean(item, f'{path}[{index}]', depth + 1) for index, item in enumerate(value)]
        if isinstance(value, str):
            return self._text(value, path)
        return value

    def report(self) -> list[dict]:
        return [{'path': path, 'rule': rule, 'count': count} for (path, rule), count in sorted(self.redactions.items())]


def redact(value: Any) -> tuple[Any, Redactor]:
    redactor = Redactor()
    return redactor.clean(value), redactor


@dataclass(frozen=True)
class EvidenceRead:
    status: str
    reason: str | None = None
    ref: str | None = None
    file_ref: str | None = None
    content: Any = None
    size_bytes: int | None = None
    file_sha256: str | None = None


def read_json_file(run_dir: Path, relative: str) -> EvidenceRead:
    """Read a JSON file named by a fixed relative ref. Never follows a symlink and never reads non-JSON."""
    if not relative.endswith('.json'):
        return EvidenceRead('UNAVAILABLE', 'not_a_json_evidence_file', file_ref=relative)
    path = contained_path(run_dir, relative)
    if path is None:
        return EvidenceRead('UNAVAILABLE', 'outside_run_directory', file_ref=relative)
    try:
        if path.is_symlink():
            return EvidenceRead('UNAVAILABLE', 'symlink_not_followed', file_ref=relative)
        if not path.is_file():
            return EvidenceRead('NOT_RECORDED', 'file_missing', file_ref=relative)
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise EvidenceTooLarge('file_too_large', MAX_FILE_BYTES, size)
        data = path.read_bytes()
    except OSError:
        return EvidenceRead('UNAVAILABLE', 'file_unreadable', file_ref=relative)
    try:
        document = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return EvidenceRead('UNAVAILABLE', 'json_corrupt', file_ref=relative, size_bytes=len(data),
                            file_sha256=hashlib.sha256(data).hexdigest())
    return EvidenceRead('AVAILABLE', None, file_ref=relative, content=document, size_bytes=len(data),
                        file_sha256=hashlib.sha256(data).hexdigest())


def _tc_case(view: RunView, case_id: str, run_dir: Path) -> EvidenceRead:
    execution = next((e for e in view.executions if e.case_id == case_id), None)
    if execution is None or not execution.record_ref:
        return EvidenceRead('NOT_RECORDED', 'case_record_missing')
    file_ref = execution.record_ref.split('#', 1)[0]
    read = read_json_file(run_dir, file_ref)
    if read.status != 'AVAILABLE':
        return read
    record = read.content
    if '#' in execution.record_ref:
        cases = record.get('cases') if isinstance(record, dict) else None
        record = next((c for c in cases or [] if isinstance(c, dict) and c.get('case_id') == case_id), None)
        if record is None:
            return EvidenceRead('UNAVAILABLE', 'case_record_not_in_file', file_ref=file_ref)
    return EvidenceRead('AVAILABLE', None, ref=execution.record_ref, file_ref=file_ref, content=record,
                        size_bytes=read.size_bytes, file_sha256=read.file_sha256)


def locate(view: RunView, run_dir: Path, case_id: str, kind: str) -> EvidenceRead:
    """Unredacted evidence for kind. The caller redacts and applies the response limit."""
    run = view.run
    execution = next((e for e in view.executions if e.case_id == case_id), None)
    if kind == 'evaluator_refs':
        if execution is None:
            return EvidenceRead('NOT_RECORDED', 'case_not_executed')
        refs = [{'evaluator_id': r.evaluator_id, 'verdict': r.verdict, 'evidence_refs': list(r.evidence_refs)}
                for r in view.evaluator_results if r.case_execution_ref == execution.locator]
        return EvidenceRead('AVAILABLE', None, ref=f'{case_id}#evaluator_results', content=refs)
    if execution is None:
        return EvidenceRead('NOT_RECORDED', 'case_not_executed')
    if run.run_kind == 'tc_regression':
        if kind == 'trace':
            return EvidenceRead('UNAVAILABLE', 'trace_only_in_sqlite_not_exposed')
        record = _tc_case(view, case_id, run_dir)
        if record.status != 'AVAILABLE':
            return record
        name = OBSERVED_FIELD[kind]
        if not isinstance(record.content, dict) or record.content.get(name) is None:
            return EvidenceRead('NOT_RECORDED', f'tc_record_has_no_{name}', file_ref=record.file_ref)
        return EvidenceRead('AVAILABLE', None, ref=f'{record.ref}.{name}', file_ref=record.file_ref,
                            content=record.content[name], size_bytes=record.size_bytes, file_sha256=record.file_sha256)
    if kind == 'trace':
        if not execution.trace_ref:
            return EvidenceRead('NOT_RECORDED', 'trace_not_recorded')
        read = read_json_file(run_dir, execution.trace_ref)
        return EvidenceRead(read.status, read.reason, ref=execution.trace_ref, file_ref=read.file_ref, content=read.content,
                            size_bytes=read.size_bytes, file_sha256=read.file_sha256)
    if run.provenance != 'recorded':
        return EvidenceRead('NOT_RECORDED', 'legacy_golden_run_did_not_save_' + OBSERVED_FIELD[kind])
    read = read_json_file(run_dir, f'{case_id}/result.json')
    if read.status != 'AVAILABLE':
        return read
    observed = read.content.get('observed') if isinstance(read.content, dict) else None
    name = OBSERVED_FIELD[kind]
    value = observed.get(name) if isinstance(observed, dict) else None
    if value is None or value == {} or value == []:
        return EvidenceRead('NOT_RECORDED', f'observed_{name}_empty', file_ref=read.file_ref,
                            size_bytes=read.size_bytes, file_sha256=read.file_sha256)
    return EvidenceRead('AVAILABLE', None, ref=f'{case_id}/result.json#observed.{name}', file_ref=read.file_ref,
                        content=value, size_bytes=read.size_bytes, file_sha256=read.file_sha256)
