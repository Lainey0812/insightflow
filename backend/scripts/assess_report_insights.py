"""Layer-specific objective diagnostics. Not an automated semantic-quality certificate."""
import argparse
import json
from pathlib import Path


def families(e):
    kind=e['value'].get('comparison_kind')
    if kind:
        return {kind,'difference'} if kind=='relative_lead' else {kind}
    result={e['evidence_type']}
    # Explicit legacy presentation provenance. Never count this as model evidence use.
    if e['evidence_id'].startswith('V'):
        formula=e['calculation']
        if '第一名 - 第二名' in formula:result.add('relative_lead')
        if '末名已返回值 / 首名已返回值' in formula:result.add('relative_ratio')
        if '第一名 + 第二名' in formula:result.add('returned_concentration')
    return result


def assess(run,cases):
    gold={c['case_id']:c for c in cases};records=[]
    for r in run['records']:
        g=gold[r['case_id']];last=r['calls'][-1] if r['calls'] else None
        sent=last['input']['evidence'] if last else []
        try:raw=json.loads(last['raw_output'])['insights'] if last and 'raw_output' in last else []
        except (KeyError,ValueError,TypeError):raw=[]
        report=r['analysis_report'];view=r['presentation'];base={e['evidence_id']:e for e in sent}
        layers={}
        for layer,items,by_id in [
            ('raw_candidates',raw,base),
            ('analysis_report',report['insights'] if report else [],{e['evidence_id']:e for e in report['evidence']} if report else base),
            ('presentation',view['findings'] if view else [],{e['evidence_id']:e for e in [*(report['evidence'] if report else []),*(view['evidence'] if view else [])]})]:
            refs={ref for i in items for ref in i['evidence_refs']}
            used=set().union(*(families(by_id[ref]) for ref in refs if ref in by_id)) if refs else set()
            available=set().union(*(families(e) for e in by_id.values())) if by_id else set()
            expected=set(g['expected']['important_families'])
            layers[layer]={'available':bool(items),'item_count':len(items),'unknown_refs':sorted(refs-by_id.keys()),
                'important_families_used':sorted(used&expected),'important_families_expected':sorted(expected),
                'expected_family_hits':len(used&expected),'expected_family_count':len(expected),
                'available_expected_family_count':len(expected&available),
                'multi_reference_items':sum(len(set(i['evidence_refs']))>=2 for i in items),
                'semantic_review_required':True}
        records.append({'case_id':r['case_id'],'split':r['split'],'error':r['error'],'layers':layers,
            'report_available':bool(report and report['insights']),
            'no_evidence_expected':g['expected']['no_valid_evidence'],
            'presentation_uses_rule_evidence':bool(view and view['evidence'])})
    summary={}
    for split in ['development','holdout']:
        rows=[r for r in records if r['split']==split]
        summary[split]={'cases':len(rows),'expected_generatable':sum(not r['no_evidence_expected'] for r in rows),
            'reports_with_insights':sum(r['report_available'] for r in rows),
            'no_evidence_cases':sum(r['no_evidence_expected'] for r in rows),'errors':[r['case_id'] for r in rows if r['error']],
            'layers':{}}
        for layer in ['raw_candidates','analysis_report','presentation']:
            parts=[r['layers'][layer] for r in rows if not r['no_evidence_expected']]
            summary[split]['layers'][layer]={'expected_family_hits':sum(p['expected_family_hits'] for p in parts),
                'expected_family_count':sum(p['expected_family_count'] for p in parts),
                'available_expected_family_count':sum(p['available_expected_family_count'] for p in parts),
                'items':sum(p['item_count'] for p in parts),'multi_reference_items':sum(p['multi_reference_items'] for p in parts),
                'unknown_reference_count':sum(len(p['unknown_refs']) for p in parts)}
    return {'protocol':'insight-quality-v1.1-frozen-2026-10-28','notice':'Objective citation diagnostics only; A–G semantic review is separate. Missing/failed outputs remain in denominators.',
            'prompt_version':run['prompt_version'],'summary':summary,'records':records}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Refusing to overwrite scoring history')
    data=assess(json.loads(a.run.read_text()),json.loads(a.cases.read_text()))
    a.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');print(json.dumps(data['summary'],ensure_ascii=False,indent=2))
