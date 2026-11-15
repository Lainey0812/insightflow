"""Append original requirements to a local, verifiable archive. Never overwrite records."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'docs/versions'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def verify(archive=ARCHIVE):
    ledger = archive / 'ledger.jsonl'
    previous, seen = '', set()
    for line in ledger.read_text().splitlines() if ledger.exists() else []:
        entry = json.loads(line)
        event = {k: v for k, v in entry.items() if k != 'event_sha256'}
        if event['previous_event_sha256'] != previous or digest(encoded(event)) != entry['event_sha256']:
            raise ValueError('Archive ledger chain changed')
        for rel, sha in event['files'].items():
            path = (archive / rel).resolve()
            if not path.is_relative_to(archive.resolve()) or not path.is_file() or digest(path.read_bytes()) != sha:
                raise ValueError(f'Archived file missing or changed: {rel}')
            if rel in seen:
                raise ValueError(f'Archived path registered twice: {rel}')
            seen.add(rel)
        previous = entry['event_sha256']
    actual = {str(p.relative_to(archive)) for p in (archive / 'records').rglob('*') if p.is_file()} if (archive/'records').exists() else set()
    if actual != seen:
        raise ValueError('Unregistered or missing requirement record files')
    return previous, len(actual)


def add_record(title, text, *, module='general', module_version=None, kind='requirement',
               source=None, artifacts=(), related=(), archive=ARCHIVE):
    if not title.strip() or not text.strip():
        raise ValueError('Title and original request must be nonblank')
    previous, _ = verify(archive)
    for rel in artifacts:
        path = (ROOT / rel).resolve()
        if not path.is_relative_to(ROOT) or not path.exists():
            raise ValueError(f'Artifact does not exist inside project: {rel}')
    records = archive / 'records'
    records.mkdir(parents=True, exist_ok=True)
    existing = [p for p in records.iterdir() if p.is_dir() and re.fullmatch(r'REQ-\d{4,}', p.name)]
    if source and source.get('message_id'):
        for directory in existing:
            meta = json.loads((directory/'record.json').read_text())
            if meta.get('source', {}).get('message_id') == source['message_id']:
                raise ValueError('Source message already archived; append a new real request instead of overwriting')
    seq = 1 + max((int(p.name[4:]) for p in existing), default=0)
    rid = f'REQ-{seq:04d}'
    folder = records / rid
    folder.mkdir()  # Atomic refusal if an ID already exists.
    now = datetime.now(timezone.utc).isoformat()
    request_bytes = text.encode('utf-8')
    source = source or {'type': 'current_user_request', 'message_id': None}
    metadata = {'schema_version': 1, 'record_id': rid, 'title': title, 'kind': kind,
        'module': module, 'module_version': module_version, 'archived_at': now,
        'source': {k: v for k, v in source.items() if k != 'content'},
        'request_sha256': digest(request_bytes), 'artifacts': list(artifacts),
        'related_records': list(related), 'implementation_status': 'not_inferred_from_requirement'}
    files = {'request.md': request_bytes, 'record.json': encoded(metadata), 'source.json': encoded(source)}
    hashes = {}
    for name, content in files.items():
        with (folder / name).open('xb') as stream:
            stream.write(content)
        hashes[str((folder/name).relative_to(archive))] = digest(content)
    event = {'event': 'requirement_archived', 'record_id': rid, 'at': now,
             'previous_event_sha256': previous, 'files': hashes}
    event['event_sha256'] = digest(encoded(event))
    with (archive/'ledger.jsonl').open('a') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
    return metadata


def append_version(record_id, label, notes, artifacts=(), archive=ARCHIVE):
    """Append implementation history under its original requirement; do not rewrite it."""
    previous, _ = verify(archive)
    if not re.fullmatch(r'REQ-\d{4,}', record_id) or not (archive/'records'/record_id/'record.json').is_file():
        raise ValueError('Existing requirement record ID required')
    if not label.strip() or not notes.strip():
        raise ValueError('Actual version label and implementation notes required')
    for rel in artifacts:
        path = (ROOT/rel).resolve()
        if not path.is_relative_to(ROOT) or not path.exists():
            raise ValueError(f'Artifact does not exist inside project: {rel}')
    versions = archive/'records'/record_id/'versions'
    versions.mkdir(exist_ok=True)
    seq = 1 + max((int(p.name[4:]) for p in versions.iterdir() if p.is_dir() and re.fullmatch(r'VER-\d{4,}', p.name)), default=0)
    folder = versions/f'VER-{seq:04d}'
    folder.mkdir()
    now = datetime.now(timezone.utc).isoformat()
    metadata = {'record_id':record_id,'version_record':folder.name,'version_label':label,
        'kind':'implementation_note_not_new_user_requirement','recorded_at':now,
        'artifacts':list(artifacts),'notes_sha256':digest(notes.encode())}
    files = {'version.json':encoded(metadata),'notes.md':notes.encode()}
    hashes = {}
    for name, content in files.items():
        with (folder/name).open('xb') as stream:
            stream.write(content)
        hashes[str((folder/name).relative_to(archive))] = digest(content)
    event = {'event':'implementation_version_recorded','record_id':record_id,'at':now,
        'previous_event_sha256':previous,'files':hashes}
    event['event_sha256'] = digest(encoded(event))
    with (archive/'ledger.jsonl').open('a') as stream:
        stream.write(json.dumps(event,ensure_ascii=False)+'\n')
    return metadata


def rebuild_index(archive=ARCHIVE):
    verify(archive)
    records = [json.loads(p.read_text()) for p in sorted((archive/'records').glob('REQ-*/record.json'))]
    for r in records:
        r['version_history'] = [json.loads(p.read_text()) for p in sorted(
            (archive/'records'/r['record_id']/'versions').glob('VER-*/version.json'))]
    (archive/'index.json').write_bytes(encoded({'schema_version':1, 'records':records}))
    lines = ['# InsightFlow 需求档案索引', '',
        '此文件为可重新生成的目录；原始记录在 records 中，只追加、不覆盖。编号是归档顺序，不是发布版本号。', '',
        '| 记录 | 类型 | 模块 / 版本标签 | 需求标题 | 技术子版本记录 |', '| --- | --- | --- | --- | --- |']
    for r in records:
        title = r['title'].replace('|', '／').replace('\n', ' ')
        version = r['module'] + (' / ' + r['module_version'] if r['module_version'] else '')
        history = '、'.join(f"[{v['version_label']}](records/{r['record_id']}/versions/{v['version_record']}/notes.md)" for v in r['version_history'])
        lines.append(f"| [{r['record_id']}](records/{r['record_id']}/request.md) | {r['kind']} | {version} | {title} | {history} |")
    (archive/'INDEX.md').write_text('\n'.join(lines) + '\n')
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add')
    add.add_argument('--title', required=True)
    add.add_argument('--request-file', type=Path, required=True)
    add.add_argument('--module', default='general')
    add.add_argument('--module-version')
    add.add_argument('--kind', default='requirement', choices=['requirement','clarification','confirmation','test_request','operation','question','audit','policy'])
    add.add_argument('--artifact', action='append', default=[])
    add.add_argument('--related', action='append', default=[])
    add.add_argument('--source-thread')
    add.add_argument('--source-message')
    version = commands.add_parser('version')
    version.add_argument('--requirement',required=True)
    version.add_argument('--label',required=True)
    version.add_argument('--notes-file',type=Path,required=True)
    version.add_argument('--artifact',action='append',default=[])
    commands.add_parser('verify')
    commands.add_parser('index')
    args = parser.parse_args()
    if args.command == 'add':
        if args.request_file.name == '.env':
            parser.error('Archive original requirement text, not an environment secret file')
        record = add_record(args.title, args.request_file.read_text(), module=args.module,
            module_version=args.module_version, kind=args.kind,
            source={'type':'user_request_text_file','thread_id':args.source_thread,'message_id':args.source_message},
            artifacts=args.artifact, related=args.related)
        rebuild_index()
        print(record['record_id'])
    elif args.command == 'version':
        record = append_version(args.requirement,args.label,args.notes_file.read_text(),args.artifact)
        rebuild_index()
        print(record['record_id']+'/'+record['version_record'])
    elif args.command == 'verify':
        _, count = verify()
        total = len(list((ARCHIVE/'records').glob('REQ-*/record.json')))
        print(f'Archive verified: {total} immutable requirements, {count} archived files.')
    else:
        print(f'Index rebuilt: {len(rebuild_index())} records.')
