"""Correct the oracle only; preserve the initial runner error and actual model output."""
from pathlib import Path
import json,pandas as pd
out=Path(__file__).parent/'fixed-nine-real01'
report=json.loads((out/'report.json').read_text())
frame=pd.DataFrame({'sales':[100,200,300],'cost':[30,70,100]})
# The frozen inputs(9) fixture has six sales metrics and two cost metrics,
# plus row count, not four metrics for each numeric column.
expected={'rows':3,'field_0002_sum':int(frame.sales.sum()),'field_0002_avg':float(frame.sales.mean()),
 'field_0002_min':int(frame.sales.min()),'field_0002_max':int(frame.sales.max()),
 'field_0002_median':float(frame.sales.median()),'field_0002_distinct_count':int(frame.sales.nunique()),
 'field_0003_sum':int(frame.cost.sum()),'field_0003_avg':float(frame.cost.mean())}
actual=report['result_data']['R001']['rows'][0]
ids={e['evidence_id']:e for e in report['evidence']}
covered={ids[ref]['result_field'] for i in report['insights'] for ref in i['evidence_refs']}
result={'verification_kind':'corrected read-only oracle, no new LLM call','prior_runner_error':'KeyError field_0003_min; erroneous four-functions-per-column assumption',
 'http_calls':len(list(out.glob('http-*-request.json'))),'report_status':report['report_status'],'goal_coverage':report['goal_coverage'],
 'expected':expected,'actual':actual,'matches_pandas':set(expected)==set(actual) and all(abs(float(actual[k])-float(v))<1e-9 for k,v in expected.items()),
 'covered_all_nine':set(expected)<=covered,'batch_count':len(report['execution_metadata']['A01']['report_batches'])}
with (out/'verification-corrected01.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print(result['report_status'],result['matches_pandas'],result['covered_all_nine'])
