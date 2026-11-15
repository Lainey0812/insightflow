"""Read a Bad Case's original session and file without writing the daily database."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from app.observability.provenance import digest

CASE_ID = re.compile(r'^bc_[0-9a-f]{32}$')
FILE_ID = re.compile(r'^[a-f0-9]{32}$')
SKIPPED = {'fixed': '已标为已修复，默认不回放。', 'wont_fix': '已标为不处理，默认不回放。', 'invalid': '已标为误报，默认不回放。'}
REPLAYABLE = {'open', 'confirmed', 'in_progress', 'pending_verification'}


def connect(path: Path):
    conn = sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn


def load_cases(data_dir: Path):
    path = data_dir / 'bad_cases' / 'bad_cases.sqlite3'
    if not path.is_file():
        return []
    with closing(connect(path)) as conn:
        rows = conn.execute(
            'SELECT c.record, e.record AS latest FROM bad_cases c JOIN bad_case_events e ON e.case_id=c.id '
            'AND e.sequence=(SELECT max(sequence) FROM bad_case_events WHERE case_id=c.id) '
            'ORDER BY c.created_at ASC, c.id ASC').fetchall()
    return [(json.loads(row['record']), json.loads(row['latest'])) for row in rows]


def _session(data_dir: Path, session_id: str):
    path = data_dir / 'insightflow.sqlite3'
    if not path.is_file() or not session_id:
        return None
    with closing(connect(path)) as conn:
        row = conn.execute('SELECT state FROM sessions WHERE id=?', (session_id,)).fetchone()
    return json.loads(row['state']) if row else None


def _file_bytes(data_dir: Path, info: dict):
    file_id, extension = info.get('id') or '', info.get('extension') or ''
    if not FILE_ID.fullmatch(file_id) or extension not in {'.csv', '.xlsx'}:
        return None, '会话里的文件引用无效。'
    path = data_dir / 'uploads' / f'{file_id}{extension}'
    try:
        content = path.read_bytes()
    except OSError:
        return None, '数据集源文件不存在。'
    digest_hex = hashlib.sha256(content).hexdigest()
    if info.get('content_sha256') and digest_hex != info['content_sha256']:
        return None, '源文件内容已改变，不能按保存时的数据回放。'
    if info.get('size') not in (None, len(content)):
        return None, '源文件大小与会话记录不一致。'
    return content, None


def prepare(data_dir: Path, case: dict, latest: dict, *, forced: bool):
    """One replay input. Source bytes stay here and are not copied into the returned public record."""
    status = latest.get('status')
    public = {'case_id': case['case_id'], 'title': case.get('title'), 'category': case.get('category'),
              'severity': case.get('severity'), 'annotation_status': status, 'observed': case.get('observed') or '',
              'expected': case.get('expected') or '', 'original_workflow_id': case.get('workflow_id')}
    if not forced and status in SKIPPED:
        return {**public, 'outcome': 'not_run', 'reason': SKIPPED[status], 'source': None}
    if not forced and status not in REPLAYABLE:
        return {**public, 'outcome': 'not_run', 'reason': '状态不在待确认或已确认，默认不回放。', 'source': None}
    evidence = case.get('evidence') or {}
    if digest(evidence) != case.get('evidence_sha256'):
        return {**public, 'outcome': 'source_missing', 'reason': '冻结证据与保存时的哈希不一致，不回放。', 'source': None}
    refs = evidence.get('replay_refs') or {}
    state = _session(data_dir, refs.get('session_id'))
    if state is None:
        return {**public, 'outcome': 'source_missing', 'reason': '原会话不在日常库，没有用户原文和上传文件，不能回放。', 'source': None}
    if state.get('data_source') != 'uploaded' or state.get('workflow_kind') != 'real_v1':
        return {**public, 'outcome': 'source_missing', 'reason': '原会话不是真实上传流程，不能回放。', 'source': None}
    info = state.get('file') or {}
    if refs.get('dataset_id') and refs['dataset_id'] != info.get('id'):
        return {**public, 'outcome': 'source_missing', 'reason': '会话当前文件与保存时的数据集不是同一份。', 'source': None}
    content, error = _file_bytes(data_dir, info)
    if error:
        return {**public, 'outcome': 'source_missing', 'reason': error, 'source': None}
    goal = state.get('user_goal') or ''
    if not goal.strip():
        return {**public, 'outcome': 'source_missing', 'reason': '原会话没有分析目标。', 'source': None}
    header = ((state.get('profile_options') or {}).get('header_row')) or 1
    answers = [a for a in (state.get('clarification_answers') or []) if isinstance(a, str) and a.strip()]
    return {**public, 'outcome': None, 'reason': None, 'case': case, 'source': {
        'goal': goal, 'header_row': int(header), 'filename': Path(info.get('name') or 'upload.csv').name,
        'extension': info['extension'], 'content': content, 'answers': answers,
        'session_id': refs.get('session_id'), 'dataset_id': info.get('id'),
        'dataset_version': refs.get('dataset_version'),
        'file_sha256': hashlib.sha256(content).hexdigest()}}
