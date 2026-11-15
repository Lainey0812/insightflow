"""Runtime provenance: exact fingerprints, never reconstructed historical settings."""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def git_snapshot(root: Path):
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                              text=True, timeout=1, check=True).stdout.strip()
    try:
        commit = git('rev-parse', '--verify', 'HEAD')
        if not re.fullmatch(r'[a-f0-9]{40,64}', commit):
            return {}
        # Capture dirty state, without retaining filenames, remote URLs or user configuration.
        return {'commit': commit, 'dirty': bool(git('status', '--porcelain', '--untracked-files=normal'))}
    except (OSError, subprocess.SubprocessError):
        return {}


def input_fingerprints(execution, approval, profile, goal):
    return {'dataset': digest({'version': profile.dataset_version, 'content': profile.content_sha256,
                              'options': profile.options.model_dump(mode='json')}),
            'profile': digest(profile), 'user_goal': digest(goal), 'intent': digest(approval.intent),
            'approved_plan': digest(approval), 'execution': digest(execution)}
