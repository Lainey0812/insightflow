"""Read-only historical comparison. Equality is exact; it never implies causation."""
from collections import defaultdict
from app.observability.provenance import digest
from app.observability.snapshots import evidence_projection, report_projection

INPUTS=('dataset','profile','user_goal','intent','approved_plan','execution')
VERSIONS=('prompt_version','generation_version','schema_version','validation_version','registry_version','prompt_sha256','fact_validator_sha256')


def equality(left, right):
    if left is None or right is None or left == {} or right == {}: return 'unknown'
    return 'same' if left == right else 'different'


def align_spans(left, right):
    """No position fallback. Ambiguous ancestry/retry identity is deliberately unmatched."""
    def index(spans):
        by_id={s.span_id:s for s in spans}; groups=defaultdict(list); unkeyed=[]
        def path(span, seen):
            if span.span_id in seen: return None
            if not span.parent_span_id: return [span.name]
            parent=by_id.get(span.parent_span_id)
            if not parent: return None
            prefix=path(parent, seen|{span.span_id})
            return prefix+[span.name] if prefix else None
        legacy_paths={s.span_id:path(s,set()) for s in spans}
        path_counts=defaultdict(int)
        for ancestry in legacy_paths.values():
            if ancestry: path_counts[tuple(ancestry)]+=1
        eligible=set()
        for s in spans:
            ancestry=legacy_paths[s.span_id]
            if ancestry and all(path_counts[tuple(ancestry[:i])]==1 for i in range(1,len(ancestry)+1)):
                eligible.add(s.span_id)
            if s.node_key is not None and s.node_attempt is not None:
                key=('stable',s.node_key,s.node_attempt)
            else:
                ancestry=legacy_paths[s.span_id]
                if ancestry and any(path_counts[tuple(ancestry[:i])]>1 for i in range(1,len(ancestry))):
                    ancestry=None
                key=('legacy_unique_path',tuple(ancestry),None) if ancestry else None
            if key: groups[key].append(s)
            else: unkeyed.append(s)
        return groups,unkeyed,eligible
    a,ua,ea=index(left);b,ub,eb=index(right);rows=[]
    # For mixed generations only a unique, complete legacy ancestry can match a stable key.
    def mixed_matches():
        for source,target,eligible in ((a,b,eb),(b,a,ea)):
            for key in list(source):
                if key[0]!='legacy_unique_path' or len(source[key])!=1: continue
                stable=('stable','/'.join([p+'#1' for p in key[1][:-1]]+[key[1][-1]]),1)
                siblings=[k for k in target if k[0]=='stable' and k[1]==stable[1]]
                if siblings==[stable] and len(target[stable])==1 and target[stable][0].span_id in eligible and stable not in source:
                    target[key]=target.pop(stable)
    mixed_matches()
    for key in sorted(set(a)|set(b),key=str):
        aa,bb=a.get(key,[]),b.get(key,[])
        if len(aa)>1 or len(bb)>1:
            ua.extend(aa);ub.extend(bb);continue
        rows.append({'node_key':'/'.join(key[1]) if isinstance(key[1],tuple) else key[1],
            'node_attempt':key[2], 'match_basis':key[0],
            'left':aa[0] if aa else None,'right':bb[0] if bb else None})
    rows.extend({'node_key':s.node_key or s.name,'node_attempt':s.node_attempt,'match_basis':'ambiguous_or_missing',
                 'left':s if side=='left' else None,'right':s if side=='right' else None}
                for side,spans in (('left',ua),('right',ub)) for s in sorted(spans,key=lambda s:s.span_id))
    return rows


def artifacts(repo, reports, run):
    saved={s.kind:{'availability':'available','source':'runtime_controlled_snapshot',
                  'snapshot_id':s.snapshot_id,'content_sha256':s.content_sha256,
                  'captured_at':s.captured_at,'projection':s.projection} for s in repo.snapshots(run.run_id)}
    if run.report_id and ('report' not in saved or 'evidence' not in saved):
        try:
            report=reports.get(run.report_id)
            bound=(report.execution_id==run.execution_id and report.report_id==run.report_id and
                   report.dataset_id==run.manifest.bindings.get('dataset_id') and
                   report.dataset_version==run.manifest.bindings.get('dataset_version') and
                   report.plan_version==run.manifest.bindings.get('plan_version'))
            if bound:
                for kind,content,project in [('report',report,lambda:report_projection(report)),
                                             ('evidence',[e.model_dump(mode='json') for e in report.evidence],lambda:evidence_projection(report.evidence))]:
                    if kind not in saved:
                        saved[kind]={'availability':'available','source':'immutable_saved_report_projection',
                                     'content_sha256':digest(content),'projection':project()}
        except Exception:
            pass  # Missing business artifact is explicit unknown, never reconstructed from newer attempts.
    return {kind:saved.get(kind,{'availability':'unknown','source':None,'projection':None,
            'reason':'本次运行未保存可读取的受控快照，未使用当前配置或重试结果补齐。'})
            for kind in ('evidence','llm_output','report')}


def compare(repo, reports, left, right):
    events={r.run_id:repo.run_events(r.run_id) for r in (left,right)}
    def verified(r):
        values=[e.payload.get('inputs_match') for e in events[r.run_id] if e.event_type=='inputs.verified']
        return bool(values) and all(value is True for value in values)
    checks=[]
    for key in INPUTS:
        a,b=left.manifest.input_sha256.get(key),right.manifest.input_sha256.get(key)
        state=equality(a,b)
        # Fingerprints captured at queue must be verified against inputs actually consumed.
        if not (verified(left) and verified(right)): state='unknown'
        checks.append({'key':key,'left':a,'right':b,'status':state,
                      'basis':'exact_runtime_sha256' if state!='unknown' else 'missing_fingerprint_or_consumption_verification'})
    scope=equality(left.manifest.capture_scope,right.manifest.capture_scope)
    checks.append({'key':'comparison_scope','left':left.manifest.capture_scope,'right':right.manifest.capture_scope,
                   'status':scope,'basis':'captured_scope'})
    # Config equality must not treat null sampling settings as known provider defaults.
    versions=[{'key':key,'left':left.manifest.versions.get(key),'right':right.manifest.versions.get(key),
               'status':equality(left.manifest.versions.get(key),right.manifest.versions.get(key))} for key in VERSIONS]
    model_keys=('provider','model','timeout_seconds','enable_thinking','temperature','top_p','endpoint_sha256')
    models=[{'key':key,'left':left.manifest.model_config_snapshot.get(key),'right':right.manifest.model_config_snapshot.get(key),
             'status':equality(left.manifest.model_config_snapshot.get(key),right.manifest.model_config_snapshot.get(key))}
            for key in model_keys]
    git={'key':'git_commit','left':left.manifest.git.get('commit'),'right':right.manifest.git.get('commit'),
         'status':equality(left.manifest.git.get('commit'),right.manifest.git.get('commit'))}
    bindings=[]
    for key in ('dataset_id','dataset_version','approval_id','plan_id','plan_version','execution_id'):
        a,b=left.manifest.bindings.get(key),right.manifest.bindings.get(key)
        bindings.append({'key':key,'left':a,'right':b,'status':equality(a,b),'basis':'saved_reference_only'})
    states=[c['status'] for c in checks]
    # Historical identical bindings provide partial evidence only, never verified input equality.
    same_ref=any(c['status']=='same' for c in bindings)
    has_info=any(s!='unknown' for s in states[:-1]) or same_ref
    if all(s=='same' for s in states) and all(v['status']!='unknown' for v in versions) and all(
            v['status']!='unknown' for v in models[:4]) and left.integrity==right.integrity=='observed':
        verdict='comparable'
    elif has_info: verdict='partially_comparable'
    else: verdict='unknown'
    def diagnostics(run):
        return [{'span_id':e.span_id,'event_type':e.event_type,'sequence':e.sequence,
                 'payload':e.payload} for e in events[run.run_id]
                if e.event_type in {'candidate.validated','candidates.summarized','llm.returned','inputs.verified'}]
    return {'left':left,'right':right,'scope':'report_generation',
        'comparability':{'status':verdict,'checks':checks,'bindings':bindings,'versions':versions,'models':models,'git':git,
            'notice':'仅比较保存的本次报告生成记录。关键输入为 different 时不能视为同输入实验；unknown 不等于相同。运行差异不能直接归因于 Prompt 或模型变更。采样默认值与 Token 用量未采集。'},
        'source_files':[{'key':key,'left':left.manifest.source_sha256.get(key),'right':right.manifest.source_sha256.get(key),
                        'status':equality(left.manifest.source_sha256.get(key),right.manifest.source_sha256.get(key))}
                       for key in sorted(set(left.manifest.source_sha256)|set(right.manifest.source_sha256))],
        'spans':align_spans(repo.spans(left.run_id),repo.spans(right.run_id)),
        'artifacts':{'left':artifacts(repo,reports,left),'right':artifacts(repo,reports,right)},
        'diagnostics':{'left':diagnostics(left),'right':diagnostics(right)},
        'live':left.status in {'queued','running'} or right.status in {'queued','running'}}
