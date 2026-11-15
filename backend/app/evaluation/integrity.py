"""Evidence integrity of a recorded run directory, checked against its final manifest. Read-only.

Rules:
- No config snapshot and no manifest (legacy formats): UNVERIFIED.
- Config snapshot without a final manifest: INCOMPLETE. Nothing can be checked yet.
- Manifest present: every file it names must be the canonical path for its role, stay inside
  the run directory, exist, and hash as recorded. The manifest must cover exactly the config's
  case ids. Any failure makes the run INVALID; a missing file is INVALID because the manifest
  claims the run was complete.
A case is VERIFIED only if the config and both of its files are verified.
Nothing is repaired or rewritten; the report only states what was found.
"""
import json
from pathlib import Path, PurePosixPath

from .contracts import FileCheck, IntegrityReport
from .manifest import CONFIG_FILE, MANIFEST_FILE, MANIFEST_SCHEMA, sha256_file

SUMMARY_FILE = 'summary.json'


def contained_path(run_dir: Path, ref) -> Path | None:
    """The path for ref if it is relative and resolves inside run_dir, else None."""
    if not isinstance(ref, str) or not ref or '\\' in ref or '\x00' in ref:
        return None
    relative = PurePosixPath(ref)
    if relative.is_absolute() or '..' in relative.parts:
        return None
    root = run_dir.resolve()
    target = (run_dir / relative).resolve()
    return run_dir / relative if target != root and root in target.parents else None


def check_file(run_dir: Path, ref, expected, role, case_id=None, canonical=None) -> FileCheck:
    def result(status, actual=None):
        return FileCheck(ref=ref if isinstance(ref, str) else None, role=role, case_id=case_id,
                         expected_sha256=expected if isinstance(expected, str) else None, actual_sha256=actual, status=status)
    path = contained_path(run_dir, ref)
    if path is None:
        return result('outside_run')
    if canonical is not None and ref != canonical:
        return result('unexpected_ref')
    if not path.is_file():
        return result('missing')
    actual = sha256_file(path)
    return result('ok' if isinstance(expected, str) and actual == expected else 'mismatch', actual)


def verify_recorded(run_dir: Path, config: dict) -> IntegrityReport:
    case_ids = list(config.get('case_ids') or [])
    manifest_path = run_dir / MANIFEST_FILE
    if not manifest_path.is_file():
        return IntegrityReport(status='INCOMPLETE', reasons=['final_manifest_missing'],
                               case_status={case_id: 'INCOMPLETE' for case_id in case_ids},
                               basis='run-config.json exists but run-manifest.json does not; the run did not finish.')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = None
    if not isinstance(manifest, dict):
        return IntegrityReport(status='INVALID', reasons=['manifest_unreadable'],
                               case_status={case_id: 'INVALID' for case_id in case_ids},
                               basis='run-manifest.json is not a readable JSON object.')
    reasons = []
    if manifest.get('schema_version') != MANIFEST_SCHEMA:
        reasons.append('manifest_schema_unexpected')
    if manifest.get('run_id') != config.get('run_id'):
        reasons.append('manifest_run_id_mismatch')
    files = [check_file(run_dir, manifest.get('config_ref'), manifest.get('config_sha256'), 'config', canonical=CONFIG_FILE),
             check_file(run_dir, manifest.get('summary_ref'), manifest.get('summary_sha256'), 'summary', canonical=SUMMARY_FILE)]
    entries = manifest.get('cases') if isinstance(manifest.get('cases'), list) else []
    if not isinstance(manifest.get('cases'), list):
        reasons.append('manifest_cases_missing')
    listed = []
    for entry in entries:
        case_id = entry.get('case_id') if isinstance(entry, dict) else None
        if not isinstance(case_id, str):
            reasons.append('manifest_case_entry_malformed')
            continue
        listed.append(case_id)
        files.append(check_file(run_dir, entry.get('result_ref'), entry.get('result_sha256'), 'case_result', case_id,
                                canonical=f'{case_id}/result.json'))
        files.append(check_file(run_dir, entry.get('trace_ref'), entry.get('trace_sha256'), 'case_trace', case_id,
                                canonical=f'{case_id}/trace.json'))
    for artifact in manifest.get('artifacts') or []:
        artifact = artifact if isinstance(artifact, dict) else {}
        files.append(check_file(run_dir, artifact.get('ref'), artifact.get('sha256'), 'artifact'))
    duplicated = sorted({c for c in listed if listed.count(c) > 1})
    reasons += [f'manifest_case_duplicated:{c}' for c in duplicated]
    reasons += [f'case_not_in_manifest:{c}' for c in case_ids if c not in listed]
    reasons += [f'case_not_in_config:{c}' for c in dict.fromkeys(listed) if c not in case_ids]
    reasons += [f'{f.status}:{f.ref}' for f in files if f.status != 'ok']
    run_level_ok = all(f.status == 'ok' for f in files if f.role in ('config', 'artifact')) and not any(
        r.startswith(('manifest_', 'case_not_in_config')) for r in reasons)
    case_status = {}
    for case_id in case_ids:
        mine = [f for f in files if f.case_id == case_id]
        ok = run_level_ok and case_id not in duplicated and len(mine) == 2 and all(f.status == 'ok' for f in mine)
        case_status[case_id] = 'VERIFIED' if ok else 'INVALID'
    return IntegrityReport(status='INVALID' if reasons else 'VERIFIED', reasons=reasons, files=files, case_status=case_status,
                           basis='SHA-256 of each file named in run-manifest.json, confined to the run directory, '
                                 'against the recorded value; manifest cases must equal the config case ids.')


def unverified(reason: str, basis: str) -> IntegrityReport:
    return IntegrityReport(status='UNVERIFIED', reasons=[reason], basis=basis)
