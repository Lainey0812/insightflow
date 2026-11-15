"""Versioned Golden management; never overwrites the historical evaluation source.

Immutable versions and every saved draft revision share one SQLite transaction
with the current pointers. Publishing is not an evaluation run or quality approval.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.domain.errors import AppError


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class Control(Record):
    code: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=500)
    result: dict[str, int | float] = Field(min_length=1)


class GoldenCase(Record):
    case_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    user_input: str = Field(min_length=1, max_length=4000)
    oracle: dict[str, int | float] = Field(min_length=1)
    error_controls: list[Control] = Field(default_factory=list, max_length=100)
    must_execute: list[str] = Field(default_factory=list, max_length=100)
    must_forbid: list[str] = Field(default_factory=list, max_length=100)
    pass_rule: str = Field(min_length=1, max_length=4000)
    fail_classes: list[str] = Field(default_factory=list, max_length=100)
    non_shanghai_policy: str | None = None


class GoldenDocument(Record):
    set_id: str = Field(min_length=1, max_length=120)
    case_count: int = Field(ge=0, le=500)
    columns: list[str] = Field(min_length=1, max_length=50)
    rows: list[dict[str, str | int | float | bool | None]] = Field(max_length=5000)
    cases: list[GoldenCase] = Field(max_length=500)

    @model_validator(mode='after')
    def integrity(self):
        if self.case_count != len(self.cases) or len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError('用例数量不一致或case_id重复。')
        if any(not c.strip() for c in self.columns) or len(set(self.columns)) != len(self.columns):
            raise ValueError('字段名称不能为空或重复。')
        if any(set(row) != set(self.columns) for row in self.rows):
            raise ValueError('每条源数据记录必须与字段列表完全对应。')
        if len(self.model_dump_json().encode()) > 2_000_000:
            raise ValueError('数据集不能超过2MB。')
        return self


class SaveDraft(Record):
    document: GoldenDocument
    expected_revision: int = Field(ge=1)
    annotator: str = Field(min_length=1, max_length=40)


class PublishDraft(Record):
    expected_revision: int = Field(ge=1)
    base_version: int = Field(ge=1)
    annotator: str = Field(min_length=1, max_length=40)
    change_summary: str = Field(min_length=1, max_length=2000)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encode(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class GoldenWorkspace:
    def __init__(self, directory: Path, source: Path):
        self.path = directory / 'golden.sqlite3'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        self.source = source
        with closing(self.connect()) as conn, conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS golden_workspace_migrations(version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS golden_versions(version INTEGER PRIMARY KEY, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS golden_draft_history(revision INTEGER PRIMARY KEY, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS golden_head(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL REFERENCES golden_versions(version), revision INTEGER NOT NULL REFERENCES golden_draft_history(revision));
            ''')
            if any(r[0] != 1 for r in conn.execute('SELECT version FROM golden_workspace_migrations')):
                raise ValueError('Unsupported golden workspace schema')
            for table in ('golden_versions', 'golden_draft_history'):
                for action in ('UPDATE','DELETE'):
                    conn.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table}
                        BEGIN SELECT RAISE(ABORT,'Golden snapshots are immutable'); END''')
            conn.execute('INSERT OR IGNORE INTO golden_workspace_migrations VALUES (1)')
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            self._bootstrap(conn)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def _bootstrap(self, conn):
        if conn.execute('SELECT 1 FROM golden_head').fetchone():
            return
        try:
            raw = self.source.read_bytes()
            document = GoldenDocument.model_validate_json(raw).model_dump(mode='json', exclude_none=True)
        except Exception:
            raise AppError('GOLDEN_SOURCE_UNAVAILABLE','黄金数据集来源缺失或结构不合法；未创建空数据集。',503) from None
        date = stamp()
        version = self._version(document,1,date,'bootstrap','从真实来源首次登记冻结；不声称历史已冻结。')
        version['source_sha256'] = hashlib.sha256(raw).hexdigest()
        conn.execute('INSERT INTO golden_versions VALUES (?,?)',(1,encode(version)))
        draft = self._draft(document,1,1,date,'bootstrap')
        conn.execute('INSERT INTO golden_draft_history VALUES (?,?)',(1,encode(draft)))
        conn.execute('INSERT INTO golden_head VALUES (1,1,1)')

    @staticmethod
    def _version(document, version, date, actor, summary):
        return {'version':version,'set_id':document['set_id'],'case_count':len(document['cases']),
            'row_count':len(document['rows']),'content_hash':sha(encode(document)), 'document':document,
            'created_at':date,'created_by':actor,'change_summary':summary,'frozen':True}

    @staticmethod
    def _draft(document, base, revision, date, actor):
        return {'document':document,'base_version':base,'revision':revision,'updated_at':date,'updated_by':actor}

    @staticmethod
    def _read(conn, table, key, value):
        row = conn.execute(f'SELECT record FROM {table} WHERE {key}=?',(value,)).fetchone()
        if not row:raise AppError('GOLDEN_VERSION_NOT_FOUND','该黄金集版本不存在。',404)
        return json.loads(row[0])

    def view(self, version=None):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN')
            head = conn.execute('SELECT * FROM golden_head').fetchone()
            selected = self._read(conn,'golden_versions','version',version or head['version'])
            if sha(encode(selected['document'])) != selected['content_hash']:
                raise AppError('GOLDEN_CONTENT_MISMATCH','已冻结版本内容哈希不一致。',409)
            versions = [json.loads(r[0]) for r in conn.execute('SELECT record FROM golden_versions ORDER BY version DESC')]
            return {'current_version':head['version'],'selected':selected,
                'versions':[{k:v for k,v in item.items() if k!='document'} for item in versions],
                'notice':'此处为版本化黄金集工作区。旧评测器仍绑定原始基线，不自动改写历史或启动评测。'}

    def draft(self):
        self.view()
        with closing(self.connect()) as conn:
            row=conn.execute('SELECT revision FROM golden_head').fetchone()
            return self._read(conn,'golden_draft_history','revision',row[0])

    def save(self, body:SaveDraft):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE');self._bootstrap(conn)
            head=conn.execute('SELECT * FROM golden_head').fetchone()
            if head['revision']!=body.expected_revision:
                raise AppError('GOLDEN_DRAFT_STALE','Draft已被修改，请重新载入后再保存。',409)
            current=self._read(conn,'golden_versions','version',head['version'])
            document=body.document.model_dump(mode='json',exclude_none=True)
            if document['set_id']!=current['set_id']:
                raise AppError('GOLDEN_SET_MISMATCH','不能在当前Draft更换Set ID。',422)
            draft=self._draft(document,head['version'],head['revision']+1,stamp(),body.annotator)
            conn.execute('INSERT INTO golden_draft_history VALUES (?,?)',(draft['revision'],encode(draft)))
            conn.execute('UPDATE golden_head SET revision=? WHERE id=1',(draft['revision'],))
            return draft

    def publish(self, body:PublishDraft):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE');self._bootstrap(conn)
            head=conn.execute('SELECT * FROM golden_head').fetchone()
            if head['revision']!=body.expected_revision or head['version']!=body.base_version:
                raise AppError('GOLDEN_DRAFT_STALE','当前版本或Draft已变化，未发布。',409)
            draft=self._read(conn,'golden_draft_history','revision',head['revision'])
            if draft['base_version']!=head['version']:
                raise AppError('GOLDEN_DRAFT_STALE','Draft基准已变化。',409)
            document=GoldenDocument.model_validate(draft['document']).model_dump(mode='json',exclude_none=True)
            if not document['cases'] or not document['rows']:
                raise AppError('GOLDEN_EMPTY','冻结版本必须至少有一条用例和一条源数据。',422)
            current=self._read(conn,'golden_versions','version',head['version'])
            if sha(encode(document))==current['content_hash']:
                raise AppError('GOLDEN_NO_CHANGE','Draft与当前冻结版本一致，无需发布新版本。',422)
            date=stamp();number=head['version']+1;revision=head['revision']+1
            version=self._version(document,number,date,body.annotator,body.change_summary)
            conn.execute('INSERT INTO golden_versions VALUES (?,?)',(number,encode(version)))
            next_draft=self._draft(document,number,revision,date,body.annotator)
            conn.execute('INSERT INTO golden_draft_history VALUES (?,?)',(revision,encode(next_draft)))
            conn.execute('UPDATE golden_head SET version=?,revision=? WHERE id=1',(number,revision))
            return version
