"""Offline integrity and independent numeric oracles. Does not test LLM/product success."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parent


def rows(name, header=1):
    with (ROOT/'data'/name).open(encoding='utf-8-sig', newline='') as f:
        for _ in range(header-1):
            next(f)
        return list(csv.DictReader(f))


def main():
    suite=json.loads((ROOT/'cases.json').read_text())
    cases={c['case_id']:c for c in suite['cases']}
    assert list(cases)==[f'TC{i:02d}' for i in range(1,16)]
    assert len(suite['cases'])==15
    for c in cases.values():
        assert (ROOT/c['dataset']).is_file()
        assert c['execution_status']=='not_run'
    expected=lambda i:cases[f'TC{i:02d}']['expected']
    sales=rows('sales.csv')
    chosen=[r for r in sales if r['订单日期'][:4]=='2026' and r['地区']=='华东' and r['订单状态']=='已完成']
    totals=defaultdict(Decimal)
    monthly=defaultdict(Decimal)
    for r in chosen:
        totals[r['城市']]+=Decimal(r['销售额'])
        monthly[int(r['订单日期'][5:7])]+=Decimal(r['销售额'])
    ranked=sorted(totals.items(),key=lambda p:-p[1])
    assert len(chosen)==expected(1)['target_rows']==6
    assert [[k,int(v)] for k,v in ranked[:3]]==expected(1)['result']
    assert sum(v for _,v in ranked[:3])==expected(1)['top3_total']
    assert sum(totals.values())==expected(1)['full_filtered_total']==50000
    assert [[k,int(v)] for k,v in ranked if k!='上海']==expected(2)['result']
    assert sum(v for k,v in ranked if k!='上海')==expected(2)['total']
    assert [[k,int(v)] for k,v in sorted(monthly.items())]==expected(3)['result']
    assert not any(r['订单日期'].startswith('2024') for r in sales)
    assert [[k,int(v)] for k,v in ranked[:2]]==expected(13)['edited_result']
    assert sum(v for _,v in ranked[:2])==41500
    quality=rows('sales_quality.csv')
    assert len(quality)==6
    assert sum(v=='' for r in quality for v in r.values())==1
    assert len(quality)-len({tuple(r.values()) for r in quality})==1
    assert sum(bool(r['销售额']) for r in quality)==5
    assert sum(Decimal(r['销售额']) for r in quality if r['销售额'])==expected(4)['total']
    jobs=rows('recruitment.csv')
    assert jobs==rows('recruitment_header6.csv',6)
    norm=lambda s:''.join(c for c in unicodedata.normalize('NFKC',s).casefold() if not c.isspace())
    selected=[r for r in jobs if norm('AI产品经理') in norm(r['岗位名称'])]
    assert sum(r['岗位名称']=='AI产品经理' for r in jobs)==expected(7)['exact_rows']
    assert len(selected)==expected(7)['normalized_contains_rows']
    assert len({r['岗位名称'] for r in selected})==expected(7)['distinct_matched_names']
    assert dict(Counter(r['城市'] for r in selected))==expected(7)['variant_result']
    assert dict(Counter(r['城市'] for r in jobs))==expected(6)['reference_city_counts']
    tickets=rows('tickets.csv')
    for category,average in expected(10)['result']:
        group=[Decimal(r['响应分钟']) for r in tickets if r['类别']==category]
        assert sum(group)/len(group)==average
    projects=[r for r in rows('projects.csv') if r['状态']=='已完成']
    assert dict(Counter(r['团队'] for r in projects))==expected(15)['result']==expected(9)['after_reply']
    for result in expected(12)['result']:
        group=[r for r in projects if r['团队']==result['团队']]
        assert len(group)==result['任务数量']
        assert sum(Decimal(r['实际工时']) for r in group)==result['工时总和']
    manifest=json.loads((ROOT/'manifest.json').read_text())
    for name,sha in manifest['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
    print('15 case definitions and 6 synthetic datasets verified; independent numeric baselines and SHA256 passed.')
    print('Product/LLM execution: not_run. Fault cases TC14/TC15 require isolated environment.')


if __name__=='__main__':
    main()
