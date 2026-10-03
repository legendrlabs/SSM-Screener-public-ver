"""Read-only, evidence-bound transaction identity and chronological state reduction."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re

DATE = r'[A-Z][a-z]+\s+\d{1,2},\s*20\d{2}'
AGREEMENT = r'agreement and plan of (?:merger|reorganization)|(?:merger|business combination|asset purchase|stock purchase|purchase) agreement'
LEGAL = r'\b[A-Z][A-Za-z0-9&-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,7},?\s+(?:Inc\.|Corporation|Corp\.|Limited|Ltd\.|LLC|L\.P\.)'
GENERIC_NAMES = {'company','the company','parent','merger sub','purchaser','seller','target','surviving corporation'}
NON_ECONOMIC = {'transaction_date','capital_context','capital_counts_as_reported','capital_counts_require_reconciliation',
                'new_common_shares_issued_reported','replacement_options_reported','replacement_warrants_reported',
                'source_reported_post_merger_common_shares','source_reported_post_merger_fd_shares',
                'reported_share_units','post_transaction_ticker','listing_termination_source_accession'}
PAYOUT_FIELDS = {'cash_per_share_usd','cash_per_share_status','cash_adjustment_direction','cash_adjustment_basis',
                 'stock_exchange_ratio','stock_consideration_security','stock_consideration_ticker',
                 'consideration_type','cvr_conditional','cvr_transferable','cvr_basis','cvr_distribution_status',
                 'illustrative_total_per_share_usd','legacy_holder_ownership_pct','target_and_financing_ownership_pct',
                 'ownership_illustrative','ownership_subject_to_closing_adjustments'}

def iso_date(raw):
    try:return datetime.strptime(re.sub(r'\s+',' ',raw), '%B %d, %Y').date().isoformat()
    except ValueError:return None

def sentences(text):
    # Legal abbreviations and decimal ratios do not terminate an operative clause.
    return re.split(r'(?<=[.;])\s+', re.sub(r'\b(Inc|Corp|Ltd)\.',r'\1',text))

def family(row):
    label=row.get('event_type','')
    if 'MERGER' in label:return 'MERGER'
    if label in {'ASSET_SALE','ASSET_SALE_ACQUISITION'}:return 'ASSET'
    return None

def identity(row):
    text=row.get('narrative') or row.get('combined_text') or row.get('text') or ''
    names=set(re.findall(LEGAL,text))
    parent=re.findall(LEGAL+r'(?=\s*(?:,?\s+a[n]?\s+[A-Za-z ]{1,50}\s+(?:corporation|company))?\s*\([“\"]Parent[”\"])',text)
    # Only source-defined aliases; generic legal roles never become identity keys.
    aliases={}
    for name in names:
        pattern=re.escape(name)+r'\s*(?:\((?:Nasdaq|NYSE):[^)]*\)\s*)?\(([^)]{1,150})\)'
        for bracket in re.findall(pattern,text,re.I):
            for alias in re.findall(r'[“\"]([^”\"]+)[”\"]',bracket):
                if alias.lower() not in GENERIC_NAMES:aliases[alias.lower()]=name.lower()
    dates=set()
    for pattern in [r'(?:'+AGREEMENT+r').{0,45}?dated(?:\s+as of)?\s+('+DATE+r')',
                    r'('+DATE+r')\s+(?:'+AGREEMENT+r')',
                    r'\bOn\s+('+DATE+r').{0,160}?\b(?:entered into|signed|executed)\b(?:(?!amendment).){0,70}?(?:'+AGREEMENT+r')']:
        dates.update(value for raw in re.findall(pattern,text,re.I) if (value:=iso_date(raw)))
    return {'family':family(row),'names':sorted(n.lower() for n in names),
            'parents':sorted(n.lower() for n in parent),'aliases':aliases,'agreement_dates':sorted(dates),
            'agreement_reference':bool(re.search(AGREEMENT,text,re.I)),
            'original_reference':bool(re.search(r'previously announced|pursuant to|original agreement|amendment|as previously disclosed',text,re.I))}

def same_transaction(left,right):
    a,b=identity(left),identity(right)
    if not a['family'] or a['family']!=b['family']:return False
    dates_a,dates_b=set(a['agreement_dates']),set(b['agreement_dates'])
    if dates_a and dates_b and not dates_a.intersection(dates_b):return False
    if a['parents'] and b['parents'] and not set(a['parents']).intersection(b['parents']):return False
    text_a=(left.get('narrative') or left.get('combined_text') or left.get('text') or '').lower()
    text_b=(right.get('narrative') or right.get('combined_text') or right.get('text') or '').lower()
    def mentioned(name,text):
        return bool(re.search(r'(?<![\w])'+re.escape(name)+r'(?![\w])',text))
    common=set(a['names']).intersection(b['names'])
    for source,dest,other in [(a,text_b,b),(b,text_a,a)]:
        for alias,legal in source['aliases'].items():
            if mentioned(alias,dest):common.add(legal)
    if not common:return False
    if len(common)==1 and len(a['names'])>1 and len(b['names'])>1 and not common.intersection(set(a['parents'])|set(b['parents'])):
        return False
    if dates_a.intersection(dates_b):return True
    if len(common)>=2 and a['agreement_reference'] and b['agreement_reference']:return True
    # A defined acquirer plus an explicit original-agreement reference is two
    # independent signals. Neither a common issuer name nor a generic deal word joins.
    parent_match=bool(common.intersection(set(a['parents'])|set(b['parents'])))
    original=bool(a['original_reference'] or b['original_reference'])
    regulatory=bool(re.search(r'regulatory|HSR|Hart-Scott|waiting period',text_a+' '+text_b,re.I))
    return parent_match and a['agreement_reference'] and b['agreement_reference'] and (original or regulatory)

def closing_evidence(text,deal_family='MERGER'):
    """Return an actual action and its date, never approval or financing completion."""
    object_pattern=r'merger|business combination|transaction' if deal_family=='MERGER' else r'asset sale|sale of.{0,80}(?:assets|business)|acquisition|transaction'
    action=(r'\b(?:closed|completed|consummated)\s+(?:(?:the|its|their|previously|announced)\s+)*(?:'+object_pattern+r')\b'
            r'|\b(?:'+object_pattern+r')\s+(?:(?:has|have) (?:been )?|was |is now )?(?:successfully )?(?:closed|completed|consummated)\b'
            r'|\bannounc(?:ed|es|ing)\s+(?:the )?(?:closing|completion|consummation)\s+of\s+(?:(?:the|its|their|previously|announced)\s+)*(?:'+object_pattern+r')\b')
    if deal_family=='MERGER':
        action+=r'|\beffective time(?:\s+of\s+the\s+merger)?\s+(?:occurred|was reached)\b|\bbecame\s+a\s+wholly owned subsidiary\b|\bmerger consideration\s+(?:was|has been)\s+paid\b|\bshares\s+were\s+issued\s+at\s+(?:the\s+)?closing\b'
    for clause in sentences(text):
        hit=re.search(action,clause,re.I)
        if not hit:continue
        if re.search(r'became\s+a\s+wholly owned subsidiary',hit[0],re.I) and not re.search(r'\bmerger\b|\bbusiness combination\b',clause,re.I):continue
        if re.search(r'\btransaction\b',hit[0],re.I):
            reference=re.search(r'(?:contemplated by|under|pursuant to|in connection with)\s+(?:the\s+)?([^.;]{1,90}?Agreement)\b',clause[hit.end():],re.I)
            expected=r'\b(?:Merger|Business Combination) Agreement\b|Agreement and Plan of Merger' if deal_family=='MERGER' else r'\b(?:Asset Purchase|Stock Purchase|Purchase) Agreement\b'
            if reference and not re.search(expected,reference[1],re.I):continue
            if not reference and re.search(r'\bfinancing\b|\bregistration statement\b',clause,re.I):continue
            deal_object=r'\bmerger\b|\bbusiness combination\b' if deal_family=='MERGER' else r'\basset sale\b|\bacquisition\b|\basset purchase\b'
            described=re.search(r'\btransaction\s+(?:involving|consisting of|for the|related to|in respect of)\s+(.+)',clause[hit.start():],re.I)
            if described and not re.search(deal_object,described[1],re.I):continue
            defined=bool(re.search(r'(?:'+deal_object+r').{0,150}\(the\s+[“\"]Transaction[”\"]\)',text,re.I))
            if not reference and not re.search(deal_object,clause,re.I) and not defined:continue
        # Split coordinated future plans away from a completed action, but an
        # expectation/condition governing the matched action stays disqualifying.
        scope=re.split(r'\s+(?:and|but)\s+(?=(?:will\b|expects?\s+to\b|plans?\s+to\b))',clause,maxsplit=1,flags=re.I)[0]
        if hit.start()>=len(scope):continue
        if re.search(r'\bif\b|\bnot\b|\bwill\b|\bwould\b|\bmay\b(?!\s+\d{1,2},)|\bexpect\w*\b|\banticipat\w*\b|\bsubject to\b|\bupon\b|\bfollowing (?:the )?closing\b|\bscheduled\b|\bplanned (?:for|to)\b|\bto be (?:closed|completed|consummated)\b',scope,re.I):continue
        when=None
        after=re.search(r'\bon\s+('+DATE+r')',scope[hit.end():],re.I)
        before=list(re.finditer(r'\bOn\s+('+DATE+r')',scope[:hit.start()],re.I))
        if after:when=iso_date(after[1])
        elif before:when=iso_date(before[-1][1])
        return {'evidence':scope.strip()[:1500],'date':when}
    return None

def reverse_structure(text,terms):
    if any(re.search(r'\breverse (?:merger|acquisition)\b',clause,re.I)
           and not re.search(r'\bif\b|\bcould\b|\bwould\b',clause,re.I) for clause in sentences(text)):return True
    legacy=terms.get('legacy_holder_ownership_pct');target=terms.get('target_and_financing_ownership_pct')
    return legacy is not None and target is not None and legacy<50<target

def normalized_kind(kind,terms,text):
    if kind in {'TERMINAL_MERGER','MERGER_TERMINATED'}:return kind
    if 'MERGER' not in kind:return kind
    reverse=reverse_structure(text,terms)
    cvr=bool(terms.get('cvr_conditional'))
    cash=terms.get('cash_per_share_usd') is not None
    stock=terms.get('stock_exchange_ratio') is not None or terms.get('consideration_type')=='STOCK'
    if reverse:return 'REVERSE_MERGER_CVR' if cvr else 'REVERSE_MERGER'
    if cash and stock:return 'MERGER_CASH_STOCK'
    if cash:return 'MERGER_CASH_CVR' if cvr else 'MERGER_CASH'
    if stock:return 'MERGER_STOCK_CVR' if cvr else 'MERGER_STOCK'
    return 'MERGER_CVR_UNVERIFIED' if cvr else 'MERGER_UNVERIFIED'

def consideration_amendment_fields(text):
    """Enacted revisions affect named components; adjustment mechanics do not."""
    changed=set()
    for clause in sentences(text):
        action=r'\b(?:amended|amendment|revised|changed|increased|decreased)\b'
        component=r'(?:merger consideration|cash consideration|stock exchange ratio|exchange ratio|stock consideration|consideration|CVR terms|contingent value rights)'
        if not re.search(action+r'.{0,70}'+component+r'|'+component+r'.{0,70}'+action,clause,re.I):continue
        if re.search(r'\bif\b|\bunless\b|\bwould\b|\bcould\b|\bmay\b|\bshall\b|\bwill be\b|\bin the event\b|\bsubject to\b',clause,re.I):continue
        if (re.search(r'\bmerger consideration\b.{0,80}\b(?:remains?|remained|is|was)\s+unchanged\b',clause,re.I)
                or re.search(r'\b(?:did|does|will)\s+not\s+(?:modify|change|amend)\b.{0,80}\bmerger consideration\b',clause,re.I)):
            continue
        cash=bool(re.search(r'cash consideration',clause,re.I))
        stock=bool(re.search(r'(?:stock )?exchange ratio|stock consideration',clause,re.I))
        cvr=bool(re.search(r'CVR terms|contingent value rights',clause,re.I))
        if cash:changed.update({'cash_per_share_usd','cash_per_share_status','cash_adjustment_direction','cash_adjustment_basis','illustrative_total_per_share_usd'})
        if stock:changed.update({'stock_exchange_ratio','stock_consideration_security','stock_consideration_ticker'})
        if cvr:changed.update({'cvr_conditional','cvr_transferable','cvr_basis','cvr_distribution_status','cvr_terms','illustrative_total_per_share_usd'})
        if not (cash or stock or cvr):changed.update(PAYOUT_FIELDS)
    return changed

def reduce_transactions(reviewed):
    groups=[];ordinary=[]
    for row in sorted(reviewed,key=lambda r:(r.get('filed',''),r.get('accession',''))):
        if not family(row) or not any(row.get(k) for k in ('narrative','combined_text','text')):
            ordinary.append(deepcopy(row));continue
        new_dates=set(identity(row)['agreement_dates'])
        matches=[]
        for group in groups:
            group_dates={d for prior in group for d in identity(prior)['agreement_dates']}
            if new_dates and group_dates and not new_dates.intersection(group_dates):continue
            if any(same_transaction(prior,row) for prior in group):matches.append(group)
        if len(matches)==1:matches[0].append(row)
        else:groups.append([row])
    resolved=[]
    for group in groups:
        latest=deepcopy(group[-1]);economics={};provenance={};invalid=set();status=None;status_source=None;actual=None
        for row in group:
            text=row.get('narrative') or row.get('combined_text') or row.get('text') or ''
            terms=row.get('terms',{})
            changed=consideration_amendment_fields(text)
            amended=bool(changed)
            if amended:
                if re.search(r'stock exchange ratio.{0,25}(?:unchanged|remains the same)',text,re.I):
                    changed-={'stock_exchange_ratio','stock_consideration_security','stock_consideration_ticker','consideration_type'}
                if re.search(r'cash consideration.{0,25}(?:unchanged|remains the same)',text,re.I):
                    changed-={'cash_per_share_usd','cash_per_share_status','cash_adjustment_direction','cash_adjustment_basis'}
                for key in changed:
                    if key in economics:invalid.add(key);economics.pop(key);provenance.pop(key,None)
            for key,value in terms.items():
                if key.startswith('_'):continue
                if key in NON_ECONOMIC or key.startswith(('economics_','lifecycle_','transaction_identity','merger_terms_source')):continue
                # Financial notes fill missing economics; explicit revisions are
                # required before they can override a definitive deal document.
                if key in invalid and key not in terms.get('_amendment_verified_fields',[]):continue
                if row.get('form','').startswith(('10-Q','10-K')) and key in economics and not amended:continue
                if amended and key in changed and key in {'cash_per_share_usd','stock_exchange_ratio'} and key not in terms.get('_amendment_verified_fields',[]):
                    invalid.add(key);continue
                economics[key]=deepcopy(value);invalid.discard(key)
                provenance[key]={'accession':row.get('accession'),'filed':row.get('filed'),'form':row.get('form'),
                                 'sources':row.get('term_sources',row.get('sources',[]))}
            closing=closing_evidence(row.get('lifecycle_narrative',text),family(row))
            if closing and closing['date'] and closing['date']>row.get('filed','9999'):closing=None
            if row.get('event_status') in {'CANCELLED','TERMINAL'}:
                status=row['event_status'];status_source=row;actual=closing
            elif closing and status!='TERMINAL':status='COMPLETED';status_source=row;actual=closing
            elif status not in {'COMPLETED','CANCELLED','TERMINAL'} and row.get('event_status') in {'SIGNED','APPROVED','PENDING_CLOSE'}:
                status=row['event_status'];status_source=row
        latest['terms']={**economics,**{k:v for k,v in latest.get('terms',{}).items() if k in NON_ECONOMIC}}
        latest['terms']['economics_provenance']=provenance
        all_narrative='\n'.join(x.get('narrative','') for x in group)
        if reverse_structure(all_narrative,economics):
            latest['terms']['reverse_structure_evidence']={'basis':'LEGACY_TARGET_OWNERSHIP_SHIFT' if economics.get('legacy_holder_ownership_pct') is not None else 'EXPLICIT_REVERSE_TRANSACTION',
                                                         'sources':list(dict.fromkeys(s for r in group for s in r.get('sources',[])))}
        if invalid.intersection({'cash_per_share_usd','stock_exchange_ratio','legacy_holder_ownership_pct','target_and_financing_ownership_pct'}):
            latest['terms']['economics_reconciliation_required']=True
            latest['terms']['economics_invalidated_fields']=sorted(invalid)
        if actual:
            latest['terms'].pop('transaction_date',None)
            if actual['date']:latest['terms']['transaction_date']=actual['date']
            latest['terms']['closing_evidence']=actual['evidence']
        if status:
            latest['event_status']=status
            if status_source:
                latest['terms']['lifecycle_source_accession']=status_source.get('accession')
                latest['terms']['lifecycle_source_date']=status_source.get('filed')
        if status=='CANCELLED':latest['event_type']='MERGER_TERMINATED'
        elif status=='TERMINAL':latest['event_type']='TERMINAL_MERGER'
        else:latest['event_type']=normalized_kind(latest['event_type'],latest['terms'],'\n'.join(x.get('narrative','') for x in group))
        if status in {'COMPLETED','TERMINAL'}:latest['event_proof']=3
        elif status in {'SIGNED','APPROVED','PENDING_CLOSE'}:latest['event_proof']=max(2,latest.get('event_proof',0))
        latest['transaction_identity']=identity(group[0])
        digest=json.dumps(latest['transaction_identity'],sort_keys=True).encode()
        latest['terms']['transaction_identity_id']=hashlib.sha256(digest).hexdigest()[:20]
        latest['terms']['transaction_filings']=[{'accession':r.get('accession'),'filed':r.get('filed'),'event_status':r.get('event_status')} for r in group]
        retained=[p for k,p in provenance.items() if k in PAYOUT_FIELDS and p.get('accession')!=latest.get('accession')]
        if retained:
            source=max(retained,key=lambda p:p.get('filed',''))
            latest['terms'].update(merger_terms_source_accession=source['accession'],merger_terms_source_date=source['filed'])
        latest['sources']=list(dict.fromkeys(s for r in group for s in r.get('sources',[])))
        latest['summary']=latest['event_type'].replace('_',' ').title()
        resolved.append(latest)
    return ordinary+resolved