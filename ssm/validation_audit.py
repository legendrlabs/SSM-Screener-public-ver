"""Observable invariant checks; measured corrections are not universal accuracy claims."""
import ast
from collections import Counter
from pathlib import Path

def compare_candidates(current,previous):
    new={c.ticker:c for c in current};old={c.ticker:c for c in previous}
    matched=sorted(new.keys()&old.keys());changes=[]
    for ticker in matched:
        a,b=old[ticker],new[ticker]
        fields={key:{'before':getattr(a,key),'after':getattr(b,key)} for key in ('event_type','event_status','gate_status')
                if getattr(a,key)!=getattr(b,key)}
        if a.dilution.confidence!=b.dilution.confidence:fields['confidence']={'before':a.dilution.confidence,'after':b.dilution.confidence}
        for key in ('cash_per_share_usd','stock_exchange_ratio','cash_adjustment_direction'):
            if a.event_terms.get(key)!=b.event_terms.get(key):fields[key]={'before':a.event_terms.get(key),'after':b.event_terms.get(key)}
        if fields:changes.append({'ticker':ticker,'changes':fields,'sources':b.event_sources,
                                 'closing_evidence':b.event_terms.get('closing_evidence'),
                                 'economics_provenance':b.event_terms.get('economics_provenance',{}),
                                 'financial_capital_classifications':[r['context'].get('classification') for r in b.event_terms.get('financial_capital_context_history',[])]})
    return {'matched_candidate_count':len(matched),'new_only':sorted(new.keys()-old.keys()),'old_only':sorted(old.keys()-new.keys()),
            'confidence_low_to_resolved':sum(old[t].dilution.confidence=='low' and new[t].dilution.confidence!='low' for t in matched),
            'confidence_resolved_to_low':sum(old[t].dilution.confidence!='low' and new[t].dilution.confidence=='low' for t in matched),
            'data_hold_released':sum(old[t].gate_status=='DATA_HOLD' and new[t].gate_status!='DATA_HOLD' for t in matched),
            'data_hold_added':sum(old[t].gate_status!='DATA_HOLD' and new[t].gate_status=='DATA_HOLD' for t in matched),
            'stale_active_to_completed':sum(old[t].event_status in {'SIGNED','PRELIMINARY','UNKNOWN','PENDING_CLOSE','APPROVED'} and new[t].event_status in {'COMPLETED','TERMINAL'} for t in matched),
            'old_gate_counts':dict(Counter(c.gate_status for c in previous)),
            'new_gate_counts':dict(Counter(c.gate_status for c in current)),'changes':changes,
            'interpretation':'Same-input output differences. Source-validated false-positive counts require reviewing the attached evidence; these totals are not estimates of unknown errors.'}

def forbidden_override_conditions(root=None):
    root=Path(root or Path(__file__).parent);found=[]
    for path in root.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node,ast.Compare):continue
            values=[node.left]+node.comparators
            identifiers=[getattr(v,'id',getattr(v,'attr','')) for v in values]
            if any(name in {'ticker','issuer','accession','company_name'} for name in identifiers) and any(isinstance(v,ast.Constant) and isinstance(v.value,str) and v.value for v in values):
                found.append({'file':path.name,'line':node.lineno})
    return found

def summarize_invariants(candidates):
    rules={key:{'observed':0,'violations':0,'tickers':[]} for key in (
        'latest_transaction_lifecycle','consideration_retained','reverse_requires_structure',
        'historical_not_incremental','historical_confidence_not_downgraded',
        'unresolved_current_capital_held','recapitalization_does_not_waive_risk',
        'duplicate_sources_not_summed','no_security_specific_overrides')}
    def observe(key,c,violated=False,count=1):
        r=rules[key];r['observed']+=count;r['violations']+=int(violated)
        if c.ticker not in r['tickers']:r['tickers'].append(c.ticker)
    historical_auto_downgrades_avoided=0
    for c in candidates:
        terms=c.event_terms;stage=getattr(c,'validation_audit',{})
        filings=terms.get('transaction_filings',[])
        if terms.get('closing_evidence'):
            observe('latest_transaction_lifecycle',c,c.event_status not in {'COMPLETED','TERMINAL'})
        if terms.get('merger_terms_source_accession'):
            payout={k:v for k,v in terms.get('economics_provenance',{}).items() if k in {'cash_per_share_usd','stock_exchange_ratio','legacy_holder_ownership_pct','cvr_conditional'}}
            observe('consideration_retained',c,not payout)
        if c.event_type in {'REVERSE_MERGER','REVERSE_MERGER_CVR'}:
            observe('reverse_requires_structure',c,not terms.get('reverse_structure_evidence'))
        records=terms.get('financial_capital_context_history',[])
        for row in records:
            cap=row['context']
            if cap.get('classification')=='HISTORICAL_INCLUDED':
                observe('historical_not_incremental',c,not cap.get('read_only') or cap.get('current_fd_impact')!='NONE')
            if cap.get('classification')=='CURRENT_RECONCILIATION_REQUIRED':
                observe('unresolved_current_capital_held',c,c.gate_status not in {'DATA_HOLD','EXCLUDED','REJECT'})
            if cap.get('assessment','').startswith('RECAPITALIZATION_') and cap.get('reconciliation_required'):
                observe('recapitalization_does_not_waive_risk',c,c.gate_status in {'PASS','WATCH'})
            if row.get('duplicate_event_accessions'):
                observe('duplicate_sources_not_summed',c,stage.get('history_common_before')!=stage.get('history_common_after'))
        if records and all(r['context'].get('classification')=='HISTORICAL_INCLUDED' for r in records):
            before=stage.get('history_confidence_before');after=stage.get('history_confidence_after')
            observe('historical_confidence_not_downgraded',c,before in {'medium','high'} and after=='low')
            historical_auto_downgrades_avoided+=int(before in {'medium','high'} and after in {'medium','high'})
        ids=[r.get('capital_event_id') for r in records if r.get('capital_event_id')]
        if len(ids)!=len(set(ids)):observe('duplicate_sources_not_summed',c,True)
    overrides=forbidden_override_conditions()
    rules['no_security_specific_overrides'].update(observed=len(list(Path(__file__).parent.glob('*.py'))),violations=len(overrides))
    return {'candidate_count':len(candidates),'invariants':rules,
            'historical_only_automatic_downgrades_avoided':historical_auto_downgrades_avoided,
            'forbidden_override_conditions':overrides,
            'scope':'Observable output and stage invariants only. Zero observed violations does not certify every SEC transaction was detected. Regression fixtures exercise negative/ambiguous cases independently.'}
