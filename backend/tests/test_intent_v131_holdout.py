import json,hashlib
from pathlib import Path
from app.intent.prompt import SYSTEM_PROMPT
ROOT=Path(__file__).parents[2]


def test_final_holdout_is_grounded_disjoint_and_schema_unchanged():
    s=json.loads((ROOT/'backend/evaluation/intent_final_unseen_v131.json').read_text())
    prior=[json.loads(p.read_text()) for p in (ROOT/'backend/evaluation').glob('intent_*_v13.json')]
    known={c['query'] for p in prior for c in p['cases']}
    assert len(s['cases'])==20 and not {c['query'] for c in s['cases']} & known
    assert not s['human_reviewed']
    for c in s['cases']:
        assert c['query'] not in SYSTEM_PROMPT
        assert all(u['text'] in c['query'] for u in c['focused_units'])


def test_original_v13_scorer_unchanged_and_first_pass_sources_preserved():
    folder=ROOT/'docs/evaluations/intent-v1.3'
    m=json.loads((folder/'freeze-manifest.json').read_text())
    for path,digest in m['sha256'].items():
        assert hashlib.sha256((folder/'frozen-source'/path).read_bytes()).hexdigest()==digest
    path='backend/app/intent/reliable_evaluation.py'
    assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==m['sha256'][path]
