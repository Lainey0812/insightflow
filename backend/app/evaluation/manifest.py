"""Write-once run files. The config snapshot precedes execution; the final manifest is written once at the end.

A run directory with a config snapshot and no final manifest is an incomplete run.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path

CONFIG_FILE = 'run-config.json'
MANIFEST_FILE = 'run-manifest.json'
CONFIG_SCHEMA = 'evaluation-run-config-v1'
MANIFEST_SCHEMA = 'evaluation-final-manifest-v1'


def encode(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + '\n').encode('utf-8')


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path: Path, value) -> str:
    """Atomically create path. An existing file is never replaced; FileExistsError is raised instead."""
    data = encode(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)
    return hashlib.sha256(data).hexdigest()
