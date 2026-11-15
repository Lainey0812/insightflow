import json,hashlib
from pathlib import Path
from app.intent.prompt import SYSTEM_PROMPT
ROOT=Path(__file__).parents[2]


def test_last_independent_queries_are_grounded_disjoint_and_not_fewshots():
    s=json.loads((ROOT/'backend/evaluation/intent_final_unseen_v133.json').read_text())
    prior=[]
    for p in (ROOT/'backend/evaluation').glob('intent_*v13*.json'):
        if p.name!='intent_final_unseen_v133.json':prior.extend(json.loads(p.read_text())['cases'])
    assert len(s['cases'])==20
    assert not {c['query'] for c in s['cases']} & {c['query'] for c in prior}
    for c in s['cases']:
        assert c['query'] not in SYSTEM_PROMPT
        assert all(u['text'] in c['query'] for u in c['focused_units'])


def test_rejected_candidate_source_and_results_remain_verifiable():
    d=ROOT/'docs/evaluations/intent-v1.3.2'
    for path,digest in json.loads((d/'freeze-manifest.json').read_text())['sha256'].items():
        assert hashlib.sha256((d/'frozen-source'/path).read_bytes()).hexdigest()==digest
