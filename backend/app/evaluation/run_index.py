"""Read-only discovery of Golden (gf_*) and TC regression (rg_*) run directories.

Only the immediate children of explicitly configured roots are considered. The index keeps
locations and discovery findings; run content always comes from ``runs.read_run``.

Rules:
- A directory is a run candidate only if its name matches RUN_ID and its prefix is allowed by the root.
- Symlinked run directories are skipped. A run directory containing a symlink that resolves
  outside the run directory is skipped before any of its files are read.
- The run_id recorded inside the run must equal the directory name.
- A run_id found in more than one root is a conflict: every copy is excluded and the conflict is
  reported. No copy is chosen.
- A failure in one directory becomes a warning; it never fails the scan.
Nothing here writes, and no SQLite file is opened.
"""
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .runs import RunNotReadable, RunView, read_run

RUN_ID = re.compile(r'^(gf|rg)_\d{8}-\d{6}_[0-9a-f]{6}$')
PREFIX_KIND = {'gf': 'golden', 'rg': 'tc_regression'}
MAX_ENTRIES_PER_RUN = 20000
ENTRY_LABEL_LIMIT = 80

RunType = Literal['golden', 'tc_regression']


@dataclass(frozen=True)
class EvaluationRoot:
    root_id: str
    path: Path
    run_type: RunType


@dataclass(frozen=True)
class DiscoveryWarning:
    code: str
    root_id: str | None = None
    entry: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class IndexedRun:
    run_id: str
    run_type: RunType
    root_id: str
    path: Path
    view: RunView


@dataclass(frozen=True)
class ScanResult:
    runs: dict[str, IndexedRun]
    warnings: list[DiscoveryWarning]
    scanned_root_ids: tuple[str, ...] = ()


def _label(name: str) -> str:
    printable = ''.join(ch if ch.isprintable() else '?' for ch in name)
    return printable[:ENTRY_LABEL_LIMIT]


def _inspect_tree(run_dir: Path):
    """(problem, signature). problem is None when every symlink stays inside run_dir.

    signature lists (relative path, size, mtime_ns) of the JSON files; it keys the view cache.
    Entries are examined with lstat only; nothing is opened."""
    root = run_dir.resolve()
    count, signature = 0, []
    for dirpath, dirnames, filenames in os.walk(run_dir, followlinks=False):
        for name in dirnames + filenames:
            count += 1
            if count > MAX_ENTRIES_PER_RUN:
                return 'run_dir_too_many_entries', None
            path = Path(dirpath) / name
            stat = os.lstat(path)
            if path.is_symlink():
                target = path.resolve()
                if target != root and root not in target.parents:
                    return 'symlink_outside_run', None
            elif name in filenames and name.endswith('.json'):
                signature.append((path.relative_to(run_dir).as_posix(), stat.st_size, stat.st_mtime_ns))
    return None, tuple(sorted(signature))


class RunIndex:
    def __init__(self, roots: list[EvaluationRoot], *, reader=read_run):
        self.roots = list(roots)
        self.reader = reader
        self._cache: dict[tuple, RunView] = {}
        self._cache_salt: tuple = ()

    def _roots(self, warnings):
        seen, usable = {}, []
        for root in self.roots:
            try:
                resolved = root.path.resolve()
                available = resolved.is_dir()
            except OSError:
                available = False
            if not available:
                warnings.append(DiscoveryWarning('root_unavailable', root.root_id, detail='Configured root is missing or not a directory.'))
                continue
            if resolved in seen:
                warnings.append(DiscoveryWarning('root_duplicated', root.root_id, detail=f'Same directory as root {seen[resolved]}; scanned once.'))
                continue
            seen[resolved] = root.root_id
            usable.append((root, resolved))
        return usable

    def _candidates(self, root: EvaluationRoot, resolved: Path, warnings):
        try:
            entries = sorted(os.scandir(resolved), key=lambda e: e.name)
        except OSError:
            warnings.append(DiscoveryWarning('root_unreadable', root.root_id, detail='Root directory could not be listed.'))
            return []
        found = []
        for entry in entries:
            if entry.name.startswith('.'):
                continue
            match = RUN_ID.match(entry.name)
            if not match:
                if entry.is_symlink() or entry.is_dir(follow_symlinks=False):
                    warnings.append(DiscoveryWarning('invalid_run_dir_name', root.root_id, _label(entry.name),
                                            'Directory name is not a gf_/rg_ run id.'))
                continue
            if PREFIX_KIND[match.group(1)] != root.run_type:
                warnings.append(DiscoveryWarning('run_type_not_allowed_in_root', root.root_id, entry.name,
                                        f'Root accepts {root.run_type} runs only.'))
                continue
            path = resolved / entry.name
            if entry.is_symlink():
                target = path.resolve()
                inside = target != resolved and resolved in target.parents
                warnings.append(DiscoveryWarning('symlink_run_dir_skipped' if inside else 'symlink_outside_root', root.root_id, entry.name,
                                        'Symlinked run directories are not followed.'))
                continue
            if not entry.is_dir(follow_symlinks=False):
                warnings.append(DiscoveryWarning('run_entry_not_directory', root.root_id, entry.name, 'Run entry is not a directory.'))
                continue
            found.append((entry.name, path))
        return found

    def _read(self, run_id: str, path: Path, root: EvaluationRoot, warnings) -> RunView | None:
        def warn(code, detail):
            warnings.append(DiscoveryWarning(code, root.root_id, run_id, detail))
        try:
            problem, signature = _inspect_tree(path)
        except OSError:
            warn('run_dir_unreadable', 'Run directory could not be listed.')
            return None
        if problem:
            warn(problem, 'Run skipped before reading any file.')
            return None
        key = (str(path), signature, self._cache_salt)
        if key in self._cache:
            return self._cache[key]
        try:
            view = self.reader(path)
        except RunNotReadable:
            warn('run_required_file_missing', 'Neither the current nor the legacy run file set is present.')
            return None
        except json.JSONDecodeError:
            warn('run_json_corrupt', 'A required JSON file is not valid JSON.')
            return None
        except (KeyError, TypeError, AttributeError, ValidationError, ValueError):
            warn('run_record_malformed', 'A required JSON file lacks expected fields.')
            return None
        except OSError:
            warn('run_dir_unreadable', 'A required file could not be read.')
            return None
        except Exception:
            warn('run_read_error', 'Unexpected error while reading the run.')
            return None
        if view.run.run_id != run_id:
            warn('run_id_mismatch', 'The run_id recorded in the run differs from the directory name.')
            return None
        self._cache = {k: v for k, v in self._cache.items() if k[0] != str(path)}
        self._cache[key] = view
        return view

    def scan(self, cache_salt: tuple = ()) -> ScanResult:
        """cache_salt is part of the view cache key. Callers pass the dataset files' size and mtime
        so a legacy dataset_id, which depends on the current dataset bytes, is not served stale."""
        self._cache_salt = cache_salt
        warnings: list[DiscoveryWarning] = []
        located: dict[str, list[tuple[EvaluationRoot, Path]]] = {}
        usable = self._roots(warnings)
        for root, resolved in usable:
            for run_id, path in self._candidates(root, resolved, warnings):
                located.setdefault(run_id, []).append((root, path))
        scanned_root_ids = tuple(root.root_id for root, _resolved in usable)
        runs = {}
        for run_id in sorted(located):
            copies = located[run_id]
            if len(copies) > 1:
                roots = sorted(root.root_id for root, _ in copies)
                warnings.append(DiscoveryWarning('duplicate_run_id', None, run_id,
                                        'Found in roots ' + ', '.join(roots) + '; every copy is excluded.'))
                continue
            root, path = copies[0]
            view = self._read(run_id, path, root, warnings)
            if view is not None:
                runs[run_id] = IndexedRun(run_id, root.run_type, root.root_id, path, view)
        return ScanResult(runs, warnings, scanned_root_ids)
