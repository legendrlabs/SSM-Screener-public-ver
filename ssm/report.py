from __future__ import annotations
import csv,json
from pathlib import Path

def _m(x):
    if x is None:return ""
    if abs(x)>=1e9:return f"${x/1e9:.2f}B"
    if abs(x)>=1e6:return f"${x/1e6:.1f}M"
    if abs(x)>=1e3:return f"${x/1e3:.1f}K"
    return f"${x:.2f}"

def _active_common(c):
    return c.security_type == 'COMMON_EQUITY' and c.gate_status != 'EXCLUDED' and c.event_status not in {'TERMINAL','CANCELLED'}

def _currency_m(amount, currency):
    prefix = {'CAD':'C$', 'USD':'US$', 'AUD':'A$', 'HKD':'HK$', 'NZD':'NZ$', 'SGD':'S$', 'EUR':'€', 'GBP':'£'}.get(currency, currency + ' ')
    return prefix + _m(amount).removeprefix('$')

def _capital_terms(cap):
    parts=[]
    if cap:
        parts.append('Capital context: ' + cap['assessment'])
        if 'authorized_capacity_increase' in cap: parts.append(f"Authorized capacity +{cap['authorized_capacity_increase']:,.0f}; capacity alone is not issued shares")
        if cap['actual_common_issued'] is not None: parts.append(f"Actual common issued in this event: {cap['actual_common_issued']:,.0f}")
        if cap.get('actual_common_equivalent_shares') is not None: parts.append(f"Completed common or pre-funded warrant equivalents: {cap['actual_common_equivalent_shares']:,.0f}; common/warrant split unresolved")
        if cap.get('planned_common_equivalent_shares') is not None: parts.append(f"Planned common or equivalent total: {cap['planned_common_equivalent_shares']:,.0f}; not issued yet")
        if cap['issuance_increase_pct'] is not None: parts.append(f"Issued/pre-common: {cap['issuance_increase_pct']:.2f}%; existing-holder ownership reduction: {cap['existing_holder_ownership_reduction_pct']:.2f}%")
        elif cap['actual_common_issued']: parts.append('Pre-transaction common shares unresolved; dilution percentage unavailable')
        parts.append('Use of proceeds: ' + ', '.join(cap['use_of_proceeds']))
        if cap.get('reissued_instrument_identities'):parts.append('Issued/reissued senior instruments require matching: '+', '.join(cap['reissued_instrument_identities']))
        for claim in cap['retirements']:
            amount=_currency_m(claim['claim_amount'],claim['currency']) if claim['claim_amount'] is not None else 'amount unresolved'
            date=' / '+claim['transaction_date'] if claim.get('transaction_date') else ' / action date unresolved'
            link='' if claim.get('funding_link_confirmed') else ' / financing-use link unresolved'
            parts.append(f"{claim['identity'] or claim['instrument_type']}: {amount} / {claim['status']}"+date+link)
        if cap.get('annual_fixed_charge_reduction_usd') is not None: parts.append(f"Source-reported annual fixed-charge reduction: {_currency_m(cap['annual_fixed_charge_reduction_usd'], 'USD')}")
        if cap.get('removed_fd_equivalents'): parts.append(f"Retired instrument FD equivalents removed after matching: {cap['removed_fd_equivalents']:,.0f}")
        if cap['reconciliation_required']: parts.append('FD reconciliation pending; context does not waive dilution risk or promote PASS')
    return parts

def _terms(c):
    t=c.event_terms; parts=_capital_terms(t.get('capital_context', {}))
    seen={json.dumps(t.get('capital_context', {}),sort_keys=True)}
    for record in t.get('capital_context_history', []):
        cap=record['context'];key=json.dumps(cap,sort_keys=True)
        if key in seen:continue
        seen.add(key)
        parts.append('Capital filing '+str(record.get('filed') or record.get('accession') or 'date unresolved'))
        parts.extend(_capital_terms(cap))
        if record.get('sources'):parts.append('Capital source: '+', '.join(record['sources']))
    if t.get('capital_structure_action') == 'DEBT_EQUITY_EXCHANGE': parts.append('Debt exchanged for common stock; incremental shares require reconciliation')
    if t.get('consideration_type') == 'STOCK':
        parts.append('Stock consideration')
        if 'legacy_holder_ownership_pct' in t: parts.append(f"Legacy holders: approximately {t['legacy_holder_ownership_pct']:g}%")
        if 'target_and_financing_ownership_pct' in t: parts.append(f"Target and financing holders: approximately {t['target_and_financing_ownership_pct']:g}%")
        if t.get('ownership_subject_to_closing_adjustments'): parts.append('Pro forma ownership subject to closing adjustments; not a current FD share count')
    if t.get('cvr_basis'): parts.append(t['cvr_basis'] + '; payment may be zero')
    if t.get('cvr_distribution_status') == 'CONTEMPLATED': parts.append('CVR distribution contemplated, subject to declaration and closing')
    if 'cash_per_share_usd' in t: parts.append(f"Cash at closing: ${t['cash_per_share_usd']:.2f}/share")
    if 'stock_exchange_ratio' in t:
        security = t.get('stock_consideration_ticker') or t.get('stock_consideration_security', 'consideration security')
        parts.append(f"Stock at closing: {t['stock_exchange_ratio']:g} shares of {security} per existing common share")
    if t.get('cash_adjustment_direction') == 'DOWNWARD': parts.append('Cash is subject to downward adjustment for a net working capital shortfall; the stated amount is not a guaranteed floor')
    if 'rights_offering_shares' in t: parts.append(f"Rights offering: {t['rights_offering_shares']:,} common shares at ${t['rights_subscription_price_usd']:.2f}; gross proceeds {_m(t['rights_gross_proceeds_usd'])}")
    if 'backstop_exchange_common_shares' in t: parts.append(f"Backstop exchange: {t['backstop_exchange_common_shares']:,} common shares to be issued")
    if 'combined_notes_principal_reduction_usd' in t: parts.append(f"Expected notes principal reduction: {_m(t['combined_notes_principal_reduction_usd'])}, combining exchange and par redemptions")
    if 'expected_post_transaction_common_shares' in t: parts.append(f"Expected post-transaction issued common shares: {t['expected_post_transaction_common_shares']:,}; requires reconciliation and is not the current FD share count")
    for key, label in [('new_common_shares_issued_reported', 'New common shares issued'), ('replacement_options_reported', 'Replacement options'), ('replacement_warrants_reported', 'Replacement warrants'), ('source_reported_post_merger_common_shares', 'Post-merger common shares'), ('source_reported_post_merger_fd_shares', 'Post-merger fully diluted shares')]:
        if key in t: parts.append(f"{label}, as reported: {t[key]:,}")
    if t.get('reported_share_units') == 'POST_REVERSE_SPLIT': parts.append('Reported share quantities reflect the reverse split')
    if t.get('capital_counts_require_reconciliation'): parts.append('Reported capital counts require reconciliation; computed FD economics remain unavailable')
    if 'post_transaction_ticker' in t: parts.append(f"Post-merger ticker: {t['post_transaction_ticker']}")
    if 'merger_terms_source_date' in t: parts.append(f"Consideration retained from the {t['merger_terms_source_date']} same-counterparty agreement; latest regulatory update retained")
    if t.get('cvr_conditional'):
        parts.append('CVR: contingent; ' + ('non-tradable' if t.get('cvr_transferable') is False else 'transfer terms require review'))
    if 'illustrative_total_per_share_usd' in t: parts.append(f"Full-performance illustration: ${t['illustrative_total_per_share_usd']:.2f}; per-share CVR varies, not a fixed guaranteed payout")
    if 'distribution_per_share_usd' in t: parts.append(f"Distribution: ${t['distribution_per_share_usd']:.2f}/share ({t.get('distribution_status','UNKNOWN')})")
    for key in ('record_date','payment_date','ex_dividend_date','last_trading_date','dissolution_date'):
        if key in t: parts.append(f"{key}: {t[key]}" + (' (planned)' if key in {'last_trading_date','dissolution_date'} else ''))
    if t.get('due_bills'): parts.append('Due bills apply; record date alone does not establish distribution entitlement')
    if 'new_warrant_shares' in t: parts.append(f"New warrants: {t['new_warrant_shares']:,} shares at ${t['new_warrant_exercise_price_usd']:.2f}; reconcile with outstanding baseline")
    if 'sale_price_amount' in t:
        price = _currency_m(t['sale_price_amount'], t['sale_price_currency'])
        if t.get('sale_payment_type') == 'CASH': price += ' cash'
        if t.get('usd_equivalent_source') == 'ISSUER_DISCLOSED': price += f" (~{_currency_m(t['sale_price_estimate_usd'], 'USD')}, issuer disclosed)"
        parts.append('Purchase price: ' + price)
    elif 'sale_price_estimate_usd' in t: parts.append(f"Sale price estimate: {_m(t['sale_price_estimate_usd'])}")
    if 'earnout_max_amount' in t: parts.append(f"Earnout: up to {_currency_m(t['earnout_max_amount'], t['earnout_currency'])} (contingent)")
    if 'repurchase_total_usd' in t: parts.append(f"Repurchase cap: {_m(t['repurchase_total_usd'])} total, increase {_m(t['repurchase_increment_usd'])}" + (' (conditional on closing)' if t.get('repurchase_conditional') else ''))
    if c.dilution.pending_stock_consideration_usd is not None: parts.append(f"Pending stock consideration: ${c.dilution.pending_stock_consideration_usd/1e6:.3f}M; incremental share count unresolved")
    return '; '.join(parts) or c.event_summary

def write_outputs(candidates,cfg,out_dir):
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    flat=[]
    for c in candidates:
        d=c.to_dict(); dil=d.pop("dilution")
        if not _active_common(c):
            d['fd_ratio']=None
            for key in dil: dil[key]=None
        d.update({f"dilution_{k}":v for k,v in dil.items()})
        for key in ('event_terms','event_sources','event_history'): d[key]=json.dumps(d[key],ensure_ascii=False,sort_keys=True)
        d["data_warnings"]=" | ".join(d.get("data_warnings") or []); flat.append(d)
    if flat:
        with (out/"candidates.csv").open("w",newline="",encoding="utf-8-sig") as f: w=csv.DictWriter(f,fieldnames=list(flat[0].keys()));w.writeheader();w.writerows(flat)
    else:(out/"candidates.csv").write_text("",encoding="utf-8")
    with (out/"dilution_check.csv").open("w",newline="",encoding="utf-8-sig") as f:
        fields=["ticker","common_shares","near_fd_shares","strict_fd_shares","fd_ratio","pre_funded_warrants_outstanding","ordinary_warrants_outstanding","warrant_units_as_of","atm_remaining_usd","atm_ratio","confidence","source"];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for c in candidates:
            if not _active_common(c):
                w.writerow({'ticker':c.ticker,'source':'Excluded: capital metrics are not applicable'})
                continue
            w.writerow({"ticker":c.ticker,"common_shares":c.dilution.common_shares,"near_fd_shares":c.dilution.near_fd_shares if c.dilution.confidence != 'low' else None,"strict_fd_shares":c.dilution.strict_fd_shares if c.dilution.confidence != 'low' else None,"fd_ratio":c.dilution.fd_ratio,"pre_funded_warrants_outstanding":c.dilution.pre_funded_warrants_outstanding,"ordinary_warrants_outstanding":c.dilution.ordinary_warrants_outstanding,"warrant_units_as_of":c.dilution.warrant_units_as_of,"atm_remaining_usd":c.dilution.atm_remaining_usd,"atm_ratio":c.atm_ratio(),"confidence":c.dilution.confidence,"source":c.dilution.source})
    with (out/"event_ledger.csv").open("w",newline="",encoding="utf-8-sig") as f:
        fields=["ticker","security_type","event_date","most_recent_filing_date","form","event_type","event_status","event_proof","accession","summary","event_terms","event_sources","event_history","event_selection_reason","gate_status","bucket"];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for c in candidates:w.writerow({"ticker":c.ticker,"security_type":c.security_type,"event_date":c.latest_event_date,"most_recent_filing_date":c.most_recent_filing_date,"form":c.latest_event_form,"event_type":c.event_type,"event_status":c.event_status,"event_proof":c.event_proof,"accession":c.latest_event_accession,"summary":c.event_summary,"event_terms":json.dumps(c.event_terms,sort_keys=True),"event_sources":json.dumps(c.event_sources),"event_history":json.dumps(c.event_history,sort_keys=True),"event_selection_reason":c.event_selection_reason,"gate_status":c.gate_status,"bucket":c.bucket})
    action_candidates=[c for c in candidates if c.bucket=="A_RESEARCH_NOW"]
    safe=bool(action_candidates) and all(_active_common(c) and c.gate_status=="PASS" and c.financial_review_complete and c.event_review_complete for c in action_candidates)
    q={"SAFE_TO_ACT":safe,"sec_discovery_mode":cfg.get("_sec_discovery_mode","unknown"),"candidate_count":len(candidates),"financial_review_incomplete_count":sum(not c.financial_review_complete for c in candidates),"data_hold_count":sum(c.gate_status=="DATA_HOLD" for c in candidates),"pass_count":sum(c.gate_status=="PASS" for c in candidates),"watch_count":sum(c.gate_status=="WATCH" for c in candidates),"reject_count":sum(c.gate_status=="REJECT" for c in candidates)}
    q['excluded_count']=sum(c.gate_status=='EXCLUDED' for c in candidates)
    q['active_common_count']=sum(_active_common(c) for c in candidates)
    q['financial_review_incomplete_count']=sum(_active_common(c) and not c.financial_review_complete for c in candidates)
    (out/"quality.json").write_text(json.dumps(q,indent=2),encoding="utf-8")
    top=[c for c in candidates if c.bucket=="A_RESEARCH_NOW"][:cfg["max_candidates"]]; watch=[c for c in candidates if c.bucket in ("B_WATCH","C_SPECULATIVE")][:10]; reject=[c for c in candidates if c.bucket=="REJECT"][:10]; hold=[c for c in candidates if c.bucket=="DATA_HOLD"][:10]
    md=["# Special Situation Microcap — latest","",f"**SAFE_TO_ACT: {'TRUE' if safe else 'FALSE'}**",""]
    material=[c for c in candidates if _active_common(c) and (
        c.event_type in {'MERGER_CASH_CVR','MERGER_CASH_STOCK','MERGER_STOCK','REVERSE_MERGER_CVR','MERGER_REVERSE_MERGER','LIQUIDATION_DISTRIBUTION'} or
        (c.event_type == 'DEBT_RESTRUCTURING' and c.event_terms.get('materiality') == 'STRUCTURAL') or
        c.dilution.pending_stock_consideration_usd is not None or
        any(k in c.event_terms for k in ('capital_context','capital_context_history','new_warrant_shares','sale_price_amount','sale_price_estimate_usd','repurchase_total_usd')))]
    if material:
        md += ['## Material special situations — source review required','']
        for c in material:
            md += [f"- **{c.ticker}** — {c.event_type} / {c.event_status} / {c.gate_status}. {_terms(c)}.",
                   '  Sources: ' + ', '.join(f'[SEC {i+1}]({url})' for i,url in enumerate(c.event_sources))]
    if not top:md += ["## NO CANDIDATE",""]
    else:
        md += ["## A — RESEARCH NOW","","|Ticker|Price|Basic MC|Near-FD MC|Strict FD MC|Event|Proof|10-Q/K|Score|","|---|---:|---:|---:|---:|---|---:|---|---:|"]
        for c in top:md.append(f"|{c.ticker}|{_m(c.price)}|{_m(c.basic_market_cap())}|{_m(c.near_fd_market_cap())}|{_m(c.strict_fd_market_cap())}|{c.event_type}|{c.event_proof}|{c.latest_financial_form or ''} {c.latest_financial_filing_date or ''}|{c.priority_score}|")
    for title,arr in [("B/C — WATCH",watch),("DATA HOLD",hold),("REJECT",reject)]:
        md += ["",f"## {title}",""]
        if not arr:md.append("- None")
        for c in arr:md.append(f"- **{c.ticker}** — {c.bucket}, {c.event_type} / {c.event_status}, score {c.priority_score}. {'; '.join(c.data_warnings[:3])}")
    excluded=[c for c in candidates if c.gate_status=='EXCLUDED']
    md += ['',f'## EXCLUDED — {len(excluded)} securities','']
    for c in excluded[:20]: md.append(f"- **{c.ticker}** — {c.security_type} / {c.event_status}. {'; '.join(c.data_warnings[:2])}")
    (out/"latest.md").write_text("\n".join(md),encoding="utf-8")
