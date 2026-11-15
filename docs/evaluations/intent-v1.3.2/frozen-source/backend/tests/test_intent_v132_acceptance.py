import json,hashlib
from pathlib import Path
from app.intent.prompt import SYSTEM_PROMPT
ROOT=Path(__file__).parents[2]


def test_new_acceptance_queries_are_disjoint_grounded_and_not_prompt_examples():
    s=json.loads((ROOT/'backend/evaluation/intent_acceptance_unseen_v132.json').read_text())
    prior=[]
    for p in (ROOT/'backend/evaluation').glob('intent_*v13*.json'):
        if p.name!='intent_acceptance_unseen_v132.json':prior.extend(json.loads(p.read_text())['cases'])
    assert len(s['cases'])==20
    assert not {c['query'] for c in s['cases']} & {c['query'] for c in prior}
    for c in s['cases']:
        assert c['query'] not in SYSTEM_PROMPT
        assert all(u['text'] in c['query'] for u in c['focused_units'])


def test_patch_does_not_change_scorer_and_all_prior_frozen_sources_preserved():
    for version in ['intent-v1.3','intent-v1.3.1']:
        d=ROOT/'docs/evaluations'/version
        for path,digest in json.loads((d/'freeze-manifest.json').read_text())['sha256'].items():
            assert hashlib.sha256((d/'frozen-source'/path).read_bytes()).hexdigest()==digest
    d=ROOT/'docs/evaluations/intent-v1.3'
    path='backend/app/intent/reliable_evaluation.py'
    assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==json.loads((d/'freeze-manifest.json').read_text())['sha256'][path]


def test_prompt_has_only_positive_examples_for_critical_boundary():
    assert '不限制仅查看' not in SYSTEM_PROMPT
    assert 'analysis_limits也必须保留用户明确禁止的原话' in SYSTEM_PROMPT
