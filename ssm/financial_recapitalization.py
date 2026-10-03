"""Read-only historical financing evidence from the latest financial filing.

No Dilution object enters this module. Neither reported issuance nor retired
claims can change the current common/FD balances or certify the cap table.
"""
import re

from .capital_evidence import capital_clauses
from .recapitalization import Q, MONEY, FX, FUTURE, _action_date, _identity, _retirement_rows, quantity

ISSUER = r'\b(?:Company|we|registrant|issuer)\b'
COMMON = r'(?P<shares>'+Q+r')\s+(?:newly issued\s+|new\s+)?shares\s+of\s+(?:(?:the\s+)?Company[’\x27]s\s+|our\s+)?common stock'
FINANCING = r'private placement|\bPIPE\b|rights offering|public offering|\bATM\b'


def _canonical(identity):
    if not identity:
        return None
    return re.sub(r'\b(?:perpetual|convertible)\s+(?=preferred)', '', identity.lower()).replace('preferred shares','preferred stock')


def _name(clause):
    names = set(m[0].lower() for m in re.finditer(FINANCING, clause, re.I))
    return next(iter(names)) if len(names)==1 else None


def _issuances(clauses):
    found={}
    for clause in clauses:
        if re.search(r'\bcustomer\b|\btarget company\b|\bthird party\b',clause,re.I):continue
        past = re.search(ISSUER+r'\s+(?:has\s+)?(?:issued|sold|exchanged)\b',clause,re.I)
        closed = re.search(ISSUER+r'\s+(?:closed|completed)\b.{0,300}?\bissuing\b',clause,re.I)
        verb = past or closed
        if not verb:continue
        common = re.search(COMMON,clause[verb.end():],re.I)
        if not common:continue
        prefix=clause[verb.end():verb.end()+common.start()]
        actual_exchange=bool(re.search(r'exchanged$',verb[0],re.I) and re.search(r'\bfor\s*$',prefix,re.I)
                             and re.search(r'newly issued',common[0],re.I))
        if re.search(r'\bwarrants?\b|\boptions?\b|\bpreferred\b|\bissuable\b|\bunderlying\b|\bconvertible\b|\bpurchase\b|\bacquire\b',prefix,re.I) and not actual_exchange:
            continue
        # Conditions in the issuance statement survive; future spending in a
        # later coordinated statement does not alter a past issued quantity.
        issue_clause=re.split(r'\s+and\s+(?=will\s+use\b)',clause,maxsplit=1,flags=re.I)[0]
        if re.search(FUTURE,issue_clause,re.I):continue
        when=_action_date(clause)
        name=_name(clause)
        if not name and re.search(r'\bexchange\b|\bexchanged\b',clause,re.I):name='common exchange'
        shares=quantity(common['shares'])
        alternative=bool(re.search(r'\bor\b.{0,40}pre[- ]?funded',clause,re.I))
        key=(when,shares,name,alternative)
        found[key]={'date':when,'shares':shares,'name':name,'alternative':alternative,'evidence':clause[:1200]}
    return list(found.values())


def _retirements(clauses):
    found={}
    for clause in clauses:
        if re.search(r'\bcustomer\b|\btarget company\b|\bthird party\b',clause,re.I):continue
        for row in _retirement_rows(clause,ISSUER):
            row=dict(row);row['identity']=_canonical(row['identity'])
            action=row['evidence']
            row['evidence']=clause[:1200]
            object_name=re.escape(_identity(action)) if _identity(action) else r'preferred (?:stock|shares)|debt|notes|loan|debentures'
            gap=r'(?:(?!\band\b|\b(?:acquired|purchased|issued|proceeds|dividend|per share)\b).)'
            cash=re.search(r'(?:'+object_name+r')'+gap+r'{0,240}?\s+for\s+an?\s+aggregate\s+(?:cash\s+)?(?:redemption price|payment)\s+of\s*'+MONEY,action,re.I)
            row['cash_paid']=quantity(cash['amount']+' '+(cash['unit'] or '')) if cash else None
            if cash:row['currency']=FX.get(cash['currency'].upper(),'UNVERIFIED')
            label=re.search(r'\(the\s+[“\x22]([^”\x22]+)[”\x22]\)',action,re.I)
            row['transaction_label']=label[1].lower() if label else None
            row['financing_name']=_name(clause)
            units=re.search(r'\b(?:redeemed|exchanged|converted)\s+('+Q+r')\s+shares of\s+(?:'+object_name+r')',action,re.I)
            row['retired_instrument_units']=quantity(units[1]) if units else None
            if not row['whole_instrument']:
                row['whole_instrument']=False if re.search(r'\bportion\b|\bpartial\w*\b',action,re.I) else None
            remaining=[]
            for other in clauses:
                if not row['identity'] or _canonical(_identity(other))!=row['identity'] or _action_date(other)!=row['transaction_date']:continue
                normalized=re.sub(r'\b(?:perpetual|convertible)\s+(?=preferred)', '', other, flags=re.I)
                normalized=re.sub(r'preferred shares','preferred stock',normalized,flags=re.I)
                rest=re.search(r'('+Q+r')\s+shares of\s+'+re.escape(row['identity'])+r'\s+remained outstanding',normalized,re.I)
                if rest:remaining.append(quantity(rest[1]))
            balances=set(remaining)
            row['remaining_instrument_units']=next(iter(balances)) if len(balances)==1 else None
            if row['remaining_instrument_units'] is not None:
                # The surviving same-class balance proves partial retirement;
                # a contradictory "all" statement cannot prove extinguishment.
                if row['remaining_instrument_units']>0:
                    row['whole_instrument']=None if row['whole_instrument'] is True else False
                elif row['whole_instrument'] is not True:
                    row['whole_instrument']=None
            if len(balances)>1:row['whole_instrument']=None
            key=tuple(row.get(k) for k in ('transaction_date','identity','status','claim_amount','cash_paid','currency','whole_instrument'))
            found[key]=row
    return list(found.values())


def _linked_financing(row, issuances, clauses):
    names=set()
    common=re.search(COMMON,row['evidence'],re.I)
    if row['status']=='COMPLETED' and common and re.search(ISSUER+r'\s+exchanged\b',row['evidence'],re.I):
        exchanges=[i for i in issuances if i['name']=='common exchange' and i['date']==row['transaction_date'] and i['shares']==quantity(common['shares'])]
        if len(exchanges)==1:return exchanges[0]
    if row['funding_link_confirmed']:
        if row['financing_name']:names.add(row['financing_name'])
    # A defined transaction reference ties MD&A liquidity discussion to the
    # specific retirement, rather than any preferred/debt elsewhere in a 10-Q.
    if row['transaction_label'] and row['transaction_date']:
        for clause in clauses:
            link=re.search(ISSUER+r'\s+(?:has\s+)?completed\s+the\s+'+re.escape(row['transaction_label'])+
                           r'\s+(?:utilizing|using)\s+(?:cash|proceeds).{0,70}?\b(?:in|from)\b',clause,re.I)
            if link and _action_date(clause)==row['transaction_date']:
                name=_name(clause[link.start():])
                if name:names.add(name)
    matches=[i for i in issuances if i['name'] in names]
    return matches[0] if len(matches)==1 else None


def _record_context(issue, retirements, confirmed):
    uses=sorted({'PREFERRED_REDEMPTION' if r['instrument_type']=='PREFERRED' else 'DEBT_REPAYMENT' for r in confirmed}) or ['UNKNOWN']
    for row in retirements:
        row['funding_link_confirmed']=row in confirmed
    return {'assessment':'RECAPITALIZATION_MIXED' if confirmed else 'UNKNOWN_USE_OF_PROCEEDS',
            'historical_context':True,'read_only':True,'financing_date':issue['date'],
            'financing_name':issue['name'],'actual_common_issued':None if issue['alternative'] else issue['shares'],
            'actual_common_equivalent_shares':issue['shares'] if issue['alternative'] else None,
            'planned_common_equivalent_shares':None,'pre_transaction_common_shares':None,
            'issuance_increase_pct':None,'existing_holder_ownership_reduction_pct':None,
            'use_of_proceeds':uses,'retirements':retirements,'confirmed_claim_reduction_usd':None,
            'annual_fixed_charge_reduction_usd':None,'reissued_instrument_identities':[],
            'common_count_reconciliation':'READ_ONLY_FINANCIAL_EVIDENCE','reconciliation_required':True,
            'link_verification':'CONFIRMED' if confirmed else 'UNKNOWN',
            'issuance_evidence':issue['evidence']}


def financial_capital_contexts(text, financial_record, events=()):
    """Keep dated historical transactions once, supplementing source links only.

    A positive recapitalization label needs completed, named and quantified
    retirement, a known whole/partial outcome, and an explicit financing link.
    Ambiguous evidence stays visible with UNKNOWN and never clears DATA_HOLD.
    """
    if financial_record.get('form') not in {'10-Q','10-K','10-Q/A','10-K/A'}:return []
    clauses=capital_clauses(text)
    issuances=_issuances(clauses)
    retired=_retirements(clauses)
    # A dated closing named in the financial filing may identify an issuance
    # whose share quantity appears only in a reviewed 8-K. A generic name or
    # the financial filing's report/filing date is never a transaction join.
    closures={(name,when) for clause in clauses
              if re.search(ISSUER+r'\s+(?:closed|completed)\s+(?:the\s+)?(?:'+FINANCING+r')\b',clause,re.I)
              for name,when in [(_name(clause),_action_date(clause))] if name and when}
    for event in events:
        event_clauses=capital_clauses(event.get('combined_text') or event.get('text') or '')
        for issue in _issuances(event_clauses):
            if (issue['name'],issue['date']) in closures and issue not in issuances:
                if not any((i['date'],i['shares'],i['name'],i['alternative'])==(issue['date'],issue['shares'],issue['name'],issue['alternative']) for i in issuances):
                    issuances.append(issue)
    if not issuances and any(r['status']=='COMPLETED' for r in retired):
        issuances=[{'date':None,'shares':None,'name':None,'alternative':False,'evidence':'Financing issuance/date is unresolved in the latest financial filing.'}]
    linked={id(row):_linked_financing(row,issuances,clauses) for row in retired}
    records=[]
    source=financial_record.get('filename','')
    if source and not source.startswith('https://'):source='https://www.sec.gov/Archives/'+source
    for issue in issuances:
        relevant=[dict(r) for r in retired if linked[id(r)] is issue]
        # Unlinked claims cannot supply this financing's purpose, but remain
        # visible when the financing itself is unique and there is no join.
        if not relevant and len(issuances)==1:relevant=[dict(r) for r in retired]
        confirmed=[]
        for row in relevant:
            amount=row.get('claim_amount') if row.get('claim_amount') is not None else row.get('cash_paid')
            if (issue['date'] and row['transaction_date'] and issue['date']<=row['transaction_date']<=financial_record.get('filed','')
                    and row['identity'] and row['status']=='COMPLETED' and amount and row['currency'] not in {None,'UNVERIFIED'}
                    and row['whole_instrument'] is not None
                    and any(linked[id(original)] is issue and original==row for original in retired)):
                confirmed.append(row)
        context=_record_context(issue,relevant,confirmed)
        sources=[source] if source else []
        duplicate_accessions=[]
        # Source corroboration does not add either filing's share/claim totals.
        for event in events:
            event_clauses=capital_clauses(event.get('combined_text') or event.get('text') or '')
            other_issues=_issuances(event_clauses);other_retirements=_retirements(event_clauses)
            match=bool(issue['date'] and issue['shares']) and any(o['date']==issue['date'] and o['shares']==issue['shares'] and o['alternative']==issue['alternative'] for o in other_issues)
            claim_match=not relevant or all(any(
                r['identity']==o['identity'] and r['transaction_date']==o['transaction_date']
                and (r['cash_paid'] or r['claim_amount'])==(o['cash_paid'] or o['claim_amount'])
                and r['currency']==o['currency']
                for o in other_retirements) for r in relevant if r['cash_paid'] or r['claim_amount'])
            conflict=False
            if match:
                for row in relevant:
                    same=[o for o in other_retirements if o['identity']==row['identity'] and o['transaction_date']==row['transaction_date']]
                    amounts={(o['cash_paid'] or o['claim_amount'],o['currency']) for o in same if o['cash_paid'] or o['claim_amount']}
                    expected=(row['cash_paid'] or row['claim_amount'],row['currency'])
                    extents={o['whole_instrument'] for o in same if o['whole_instrument'] is not None}
                    if (amounts and expected[0] and amounts!={expected}) or (extents and row['whole_instrument'] is not None and extents!={row['whole_instrument']}):
                        conflict=True
                if conflict:
                    context.update(source_conflict=True,assessment='UNKNOWN_USE_OF_PROCEEDS',link_verification='UNKNOWN',use_of_proceeds=['UNKNOWN'])
                    for row in context['retirements']:row['funding_link_confirmed']=False
                    sources.extend(event.get('sources',[]))
            dated_closure=(issue['name'],issue['date']) in closures
            if match and not conflict and (claim_match or dated_closure):
                sources.extend(event.get('sources',[]));duplicate_accessions.append(event.get('accession'))
        records.append({'accession':financial_record.get('accession'),'filed':financial_record.get('filed'),
                        'form':financial_record['form'],'report_date':financial_record.get('report_date'),
                        'sources':list(dict.fromkeys(sources)),'duplicate_event_accessions':duplicate_accessions,
                        'context':context})
    return records
