"""Source-backed capital purpose; context never certifies the complete FD table."""
import re
from decimal import Decimal
from datetime import datetime

from .capital_evidence import capital_clauses

Q = r'\d[\d,]*(?:\.\d+)?(?:\s+(?:million|thousand))?'
MONEY = r'(?<![A-Za-z])(?P<currency>[A-Z]{0,3}\$|€|£)\s*(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>million|thousand)?'
FX = {'$':'USD','US$':'USD','C$':'CAD','CAD$':'CAD','A$':'AUD','HK$':'HKD','€':'EUR','£':'GBP'}
FUTURE = r'\bwill\b|\bwould\b|\bmay\b|\bintend\w*\b|\bexpect\w*\b|\bplanned\b|\bproposed\b|\bsubject to\b|\bif\b|\b(?:has|have|had|did) not\b|\bnot yet\b|\bagreed to\b'
ACTION = r'\bredeem\w*\b|\brepay\w*\b|\brepaid\b|\bpaid off\b|\bextinguish\w*\b|\bexchang\w*\b|\bconvert\w*\b'


def quantity(value):
    raw=re.match(r'(\d[\d,]*(?:\.\d+)?)\s*(million|thousand)?',value,re.I)
    return float(Decimal(raw[1].replace(',','')) * {'million':1000000,'thousand':1000,None:1}[raw[2].lower() if raw[2] else None])


def _identity(clause):
    preferred=re.search(r'\bSeries\s+[A-Z0-9-]+\s+(?:Perpetual\s+|Convertible\s+)?Preferred\s+(?:Stock|Shares)',clause,re.I)
    if preferred:return preferred[0].lower()
    note=re.search(r'\b(?:20\d{2}\s+)?Convertible\s+(?:Notes|Debentures)(?:\s+due\s+20\d{2})?',clause,re.I)
    return note[0].lower() if note else None


def _action_date(clause):
    dates = set()
    for match in re.finditer(r'\bOn\s+([A-Za-z]+\s+\d{1,2},\s*20\d{2})', clause, re.I):
        try:
            dates.add(datetime.strptime(match[1], '%B %d, %Y').date().isoformat())
        except ValueError:
            pass
    return next(iter(dates)) if len(dates) == 1 else None


def _retirement_rows(clause, issuer):
    # Each verb keeps its own object. "All debt" cannot erase a partially
    # redeemed preferred class in the preceding coordinated action.
    parts = re.split(r'\s+and\s+(?=(?:'+issuer+r'\s+)?(?:has\s+|had\s+|will\s+)?(?:'+ACTION+r'))', clause, flags=re.I)
    direct = issuer + r'\s+(?:(?:has|have|had|will|would|may)\s+|(?:intends|expects|plans)\s+to\s+)?(?:(?:used|use)\s+(?:the\s+)?(?:net\s+)?proceeds\s+to\s+)?(?:'+ACTION+r')'
    inherit = bool(re.search(direct, parts[0], re.I))
    for index, part in enumerate(parts):
        if index and inherit and re.match(ACTION, part, re.I):
            part = 'The Company ' + part
        identity = _identity(part)
        liability = re.search(r'preferred (?:stock|shares)|\bdebt\b|\bnotes\b|\bloan\b|\bdebentures\b', part, re.I)
        passive = re.search(r'all (?:of the )?(?:outstanding|then-outstanding).{0,100}?(?:was|were|has been|have been)\s+(?:extinguished|redeemed|converted|exchanged)', part, re.I)
        if not liability or not (re.search(direct, part, re.I) or passive):
            continue
        typ = 'PREFERRED' if 'preferred' in liability[0].lower() else 'CONVERTIBLE' if re.search(r'convertible', part, re.I) else 'DEBT'
        status = 'PLANNED' if re.search(FUTURE, part, re.I) or not re.search(r'\b(?:redeemed|repaid|paid off|extinguished|exchanged|converted|used)\b', part, re.I) else 'COMPLETED'
        # Aggregate principal/claim must be the verb's object, never sale
        # proceeds, issue price, coupon, or a redemption price per unit.
        money = re.search(r'(?:'+ACTION+r')\s+'+MONEY+r'\s+(?:of\s+)?(?:its\s+|the\s+|outstanding\s+)*(?:Series\s+[A-Z0-9-]+\s+)?(?:Perpetual\s+|Convertible\s+)?(?:Preferred\s+(?:Stock|Shares)|debt|notes|loans?|debentures)', part, re.I)
        amount = quantity(money['amount']+' '+(money['unit'] or '')) if money else None
        currency = FX.get(money['currency'].upper(), 'UNVERIFIED') if money else None
        object_name = re.escape(identity) if identity else re.escape(liability[0])
        whole = bool(re.search(r'all\s+(?:of\s+the\s+)?(?:outstanding|then-outstanding)\s+'+object_name, part, re.I)
                     or re.search(object_name+r'\s+(?:(?:was|were)\s+)?(?:redeemed|repaid|extinguished|converted|exchanged)\s+in full', part, re.I))
        if re.search(r'\b(?:portion|partial|partially)\b', part, re.I):
            whole = False
        yield {'instrument_type':typ, 'identity':identity, 'status':status,
               'claim_amount':amount, 'currency':currency, 'whole_instrument':whole,
               'transaction_date':_action_date(part), 'evidence':part[:500]}


def capital_context(text):
    clauses=capital_clauses(text)
    actual=set();alternatives=set();planned=set();purposes=set();retirements={};capacity=None;pre=None;fixed=None
    dates=set();unknown_date=False;reissued=set()
    aliases={'company','we','registrant','issuer'}
    for bracket in re.findall(r'\(([^)]{0,120})\)',text):
        names=re.findall(r'[“"]([^”"]+)[”"]',bracket)
        if any(n.lower() in {'company','the company'} for n in names):
            aliases.update(n.lower() for n in names if n.lower() not in {'the company','company'})
    issuer=r'\b(?:'+ '|'.join(re.escape(n) for n in aliases) + r')\b'
    for clause in clauses:
        if re.search(r'\bcustomer\b|\btarget company\b|\bthird party\b',clause,re.I):continue
        auth=re.search(r'authoriz\w*.{0,140}?common stock.{0,100}?from\s+('+Q+r')\s+shares\s+to\s+('+Q+r')\s+shares',clause,re.I)
        if auth:capacity=(quantity(auth[1]),quantity(auth[2]))
        before=re.search(r'(?:immediately before|prior to)\s+(?:the )?transaction.{0,50}?('+Q+r')\s+shares of common stock\s+(?:were |was )?outstanding',clause,re.I)
        if before:pre=quantity(before[1])
        issued=re.search(issuer+r'\s+(?:(?:has|had|will|would|may)\s+|agreed to\s+|has agreed to\s+)?\b(?P<verb>issued|sold|issue)\s+(?:an aggregate of\s+|approximately\s+)?(?P<shares>'+Q+r')\s+(?:new\s+)?shares of common stock',clause,re.I)
        if issued:
            # A future use of proceeds does not turn a past-tense issuance
            # into a pending issuance. Bind tense/conditions to the issue.
            issuance_clause = re.split(r'\s+and\s+(?=(?:will|the\s+proceeds|'+issuer+r')\b)', clause, maxsplit=1, flags=re.I)[0]
            pending = issued['verb'].lower() == 'issue' or bool(re.search(FUTURE,issuance_clause,re.I))
            alternative = bool(re.search(r'\bor\b.{0,40}pre[- ]?funded warrants?', clause[issued.end():], re.I))
            (planned if pending else alternatives if alternative else actual).add(quantity(issued['shares']))
            action_date = _action_date(clause)
            if action_date:dates.add(action_date)
            else:unknown_date=True
        identity = _identity(clause)
        if identity:
            replacement = re.search(r'\b(?:issued|issue|sold|sell)\b(.{0,120}?)'+re.escape(identity), clause, re.I)
            if replacement and not re.search(r'common stock|in exchange', replacement[1], re.I):
                reissued.add(identity)
        # Capital spending alone is not a statement about this financing's use.
        use=re.search(r'\b(?:proceeds|cash raised|capital raise)\b',clause,re.I)
        if use and re.search(r'\buse\w*\b|\bfund\w*\b|\bfor\b|\bto\b',clause,re.I):
            for purpose,pattern in [('DEBT_REPAYMENT',r'(?:repay|pay off|repaid|repayment).{0,60}(?:debt|loan|notes)'),
                                    ('PREFERRED_REDEMPTION',r'(?:redeem|redemption|eliminat).{0,80}preferred'),
                                    ('ACQUISITION',r'\bacquisition\b'),('WORKING_CAPITAL',r'working capital'),
                                    ('GENERAL_CORPORATE',r'general corporate purposes')]:
                if re.search(pattern,clause,re.I):purposes.add(purpose)
        for row in _retirement_rows(clause, issuer):
            key=tuple(row[k] for k in ('instrument_type','identity','status','claim_amount','currency','whole_instrument','transaction_date'))
            retirements[key]=row
            if row['status']=='COMPLETED':
                purposes.add('PREFERRED_REDEMPTION' if row['instrument_type']=='PREFERRED' else 'DEBT_REPAYMENT')
                if row['transaction_date']:dates.add(row['transaction_date'])
                else:unknown_date=True
        charge=re.search(r'annual.{0,50}(?:dividend|interest|fixed charge).{0,60}(?:reduced|decreased|eliminated)\s+by\s*'+MONEY,clause,re.I)
        if charge and not re.search(FUTURE,clause,re.I) and FX.get(charge['currency'].upper())=='USD':
            fixed=quantity(charge['amount']+' '+(charge['unit'] or ''))
    if not(capacity or actual or alternatives or planned or reissued or any(r['status']=='COMPLETED' for r in retirements.values())):return {}
    actual_count=None if alternatives else next(iter(actual)) if len(actual)==1 else None if actual else 0
    proposed_count=next(iter(planned)) if len(planned)==1 else None
    rows=list(retirements.values())
    claims = {(r['instrument_type'],r['identity'],r['claim_amount']) for r in rows
              if r['status']=='COMPLETED' and r['currency']=='USD' and r['claim_amount'] is not None}
    # Repeated descriptions do not prove multiple redemptions. Multiple
    # amounts for one identity (or several unnamed claims) cannot be summed.
    identities = [(typ, identity) for typ,identity,amount in claims]
    claim = (sum(amount for typ,identity,amount in claims)
             if len(set(identities)) == len(identities) else None)
    uses=sorted(purposes) or ['UNKNOWN']
    if capacity and not(actual or alternatives or planned or rows or reissued):assessment='ISSUANCE_CAPACITY'
    elif uses==['UNKNOWN']:assessment='UNKNOWN_USE_OF_PROCEEDS'
    elif any(r['status']=='COMPLETED' for r in rows):
        assessment='RECAPITALIZATION_MIXED' if actual or alternatives or planned else 'RECAPITALIZATION_BALANCE_SHEET_IMPROVEMENT'
    elif purposes.intersection({'DEBT_REPAYMENT','PREFERRED_REDEMPTION'}):assessment='RECAPITALIZATION_MIXED'
    else:assessment='DILUTION_ONLY'
    context={'actual_common_issued':actual_count,'planned_common_equivalent_shares':proposed_count,
             'actual_common_equivalent_shares':next(iter(alternatives)) if len(alternatives)==1 and not actual else None,
             'transaction_date':next(iter(dates)) if len(dates)==1 and not unknown_date else None,
             'reissued_instrument_identities':sorted(reissued),
             'pre_transaction_common_shares':pre,'use_of_proceeds':uses,'retirements':rows,
             'confirmed_claim_reduction_usd':claim,'annual_fixed_charge_reduction_usd':fixed,
             'assessment':assessment,'reconciliation_required':bool(actual or alternatives or planned or rows or reissued),
             'issuance_increase_pct':actual_count/pre*100 if actual_count is not None and pre else None,
             'existing_holder_ownership_reduction_pct':actual_count/(pre+actual_count)*100 if actual_count is not None and pre else None}
    if capacity:
        context.update(authorized_common_before=capacity[0],authorized_common_after=capacity[1],
                       authorized_capacity_increase=capacity[1]-capacity[0])
    return context


def reconcile_capital_context(dilution, context, financial_text, event_date, baseline_date, blocked_identities=()):
    if not context or not context.get('reconciliation_required'):return
    # New capital events cannot certify all other securities or remove warnings.
    dilution.confidence='low'
    pre=context.get('pre_transaction_common_shares');issued=context.get('actual_common_issued')
    if pre and issued:
        if dilution.common_shares==pre and event_date and baseline_date and event_date>baseline_date:
            dilution.common_shares=pre+issued
            context['common_count_reconciliation']='PRE_PLUS_ACTUAL_ISSUANCE'
        elif dilution.common_shares==pre+issued:
            context['common_count_reconciliation']='ALREADY_POST_TRANSACTION'
        else:context['common_count_reconciliation']='UNRESOLVED'
    if not(event_date and baseline_date and event_date>baseline_date):return
    # Aggregate buckets are reduced only when every baseline share equivalent in
    # that bucket has an explicit identity and their sum equals the current total.
    baseline={}
    for clause in capital_clauses(financial_text):
        identity=_identity(clause)
        equiv=re.search(r'convertible into\s+('+Q+r')\s+shares of common stock',clause,re.I)
        if identity and equiv and re.search(r'\boutstanding\b',clause,re.I) and not re.search(FUTURE,clause,re.I):
            baseline[identity]=quantity(equiv[1])
    removed=0
    for typ,field in [('PREFERRED','preferred_shares_equiv'),('CONVERTIBLE','converts_shares')]:
        relevant={k:v for k,v in baseline.items() if ('preferred' in k)==(typ=='PREFERRED')}
        if sum(relevant.values())!=getattr(dilution,field) or not relevant:continue
        blocked=set(blocked_identities) | set(context.get('reissued_instrument_identities', []))
        retired={r['identity'] for r in context['retirements'] if r['instrument_type']==typ and r['status']=='COMPLETED' and r['whole_instrument'] and r['identity'] not in blocked}
        amount=sum(v for k,v in relevant.items() if k in retired)
        setattr(dilution,field,getattr(dilution,field)-amount);removed+=amount
    if removed:context['removed_fd_equivalents']=removed
