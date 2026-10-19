"""Review source-backed transactions and retain the active economic catalyst."""
from datetime import date, datetime, timedelta
import re
from .recapitalization import capital_context
from .transactions import reduce_transactions, normalized_kind, closing_evidence, sentences

from .event_rules import classify_event, operative_text, liquidation_evidence, adopted_rights_plan, resale_registration, closed_debt_equity_exchange, merger_share_consideration, merger_cash_consideration, merger_parent_name, completed_merger, MERGER_KINDS

PRIORITY = {'TERMINAL_MERGER': 110, 'MERGER_TERMINATED': 105,
            'LIQUIDATION_DISTRIBUTION': 100, 'MERGER_CASH_CVR': 90, 'REVERSE_MERGER_CVR': 90, 'MERGER_CVR_UNVERIFIED': 85,
            'MERGER_REVERSE_MERGER': 85, 'MERGER_UNVERIFIED':85, 'MERGER_CASH':85, 'MERGER_STOCK_CVR':85,
            'REVERSE_MERGER':85, 'MERGER_CASH_STOCK': 85, 'MERGER_STOCK': 85, 'ASSET_SALE_ACQUISITION': 70,
            'STRATEGIC_INVESTMENT_PIPE': 65, 'DEBT_RESTRUCTURING': 60,
            'LARGE_CONTRACT': 50, 'BUSINESS_PIVOT': 45,
            'LISTING_CAPITAL_STRUCTURE': 25}
MONTH_DATE = r'([A-Z][a-z]+\s+\d{1,2},\s*20\d{2})'
MONEY = r'(?<![A-Za-z])(?P<currency>[A-Z]{0,3}\$|€|£)\s*(?P<amount>[\d.]+)\s*million'
CURRENCIES = {'$': 'USD', 'US$': 'USD', 'USD$': 'USD', 'C$': 'CAD', 'CAD$': 'CAD',
              'A$': 'AUD', 'AU$': 'AUD', 'AUD$': 'AUD', 'HK$': 'HKD', 'NZ$': 'NZD',
              'S$': 'SGD', 'SG$': 'SGD', '€': 'EUR', '£': 'GBP'}


def select_event(reviewed):
    if not reviewed:
        return None
    reviewed = reduce_transactions(reviewed)
    latest_merger = max((x.get('filed', '') for x in reviewed if x['event_type'] in MERGER_KINDS), default='')
    eligible = [x for x in reviewed if not (x['event_type'] == 'MERGER_TERMINATED' and x.get('filed', '') < latest_merger)]
    # Retain active merger/liquidation lifecycles through routine filings.
    # Other transactions use recency; an old asset deal cannot hide refinancing.
    return max(eligible, key=lambda x: (PRIORITY.get(x['event_type'], 10) if PRIORITY.get(x['event_type'], 10) >= 85 else 0,
                                       x.get('filed', ''), x.get('accession', '')))


def _date_after(text, anchor, distance=180):
    match = re.search('(?:' + anchor + ')' + r'.{0,' + str(distance) + r'}?' + MONTH_DATE, text, re.I)
    if not match:
        return None
    try:
        return datetime.strptime(re.sub(r'\s+', ' ', match.group(1)), '%B %d, %Y').date().isoformat()
    except ValueError:
        return None


def event_terms(text, kind, *, cleaned=False):
    t = text if cleaned else operative_text(text)
    terms = {}
    if kind in MERGER_KINDS | {'TERMINAL_MERGER'}:
        cash = merger_cash_consideration(t)
        specialized=list(re.finditer(r'cash consideration per common share (?:was |is )?(?:increased|decreased|changed|revised) to\s*\$\s*(\d+(?:\.\d+)?)',t,re.I))
        revised=list(re.finditer(r'(?:amended|revised|changed|increased|decreased).{0,60}(?:merger consideration|cash consideration).{0,20}?to\s*\$\s*(\d+(?:\.\d+)?)\s+per (?:common )?share\s+in cash',t,re.I))
        cash_updates=sorted(specialized+revised,key=lambda m:m.start())
        if cash_updates:cash=cash_updates[-1]
        if cash and kind != 'REVERSE_MERGER_CVR':
            terms['cash_per_share_usd'] = float(cash.group(1))
            terms['cash_per_share_status'] = 'FIXED'
        if re.search(r'contingent value right|\bCVR\b',t,re.I):
            terms['cvr_conditional'] = True
            if re.search(r'non[- ]tradable|non[- ]transferable', t, re.I):
                terms['cvr_transferable'] = False
            illustrative = re.search(r'aggregate potential merger consideration (?:of|is)\s*\$\s*(\d+(?:\.\d+)?)\s+per share', t, re.I)
            if kind == 'MERGER_CASH_CVR' and illustrative and re.search(r'assuming full|illustration', t, re.I):
                terms['illustrative_total_per_share_usd'] = float(illustrative.group(1))
        if kind == 'REVERSE_MERGER_CVR':
            terms['consideration_type'] = 'STOCK'
            for key, pattern in [('legacy_holder_ownership_pct', r'pre[- ]merger (?:company|parent) stockholders.{0,180}?approximately\s*([\d.]+)%'),
                                 ('target_and_financing_ownership_pct', r'stockholders\s*\(inclusive of investors in the private placement\).{0,180}?approximately\s*([\d.]+)%')]:
                ownership = re.search(pattern, t, re.I)
                if ownership:
                    terms[key] = float(ownership.group(1))
            terms['ownership_illustrative'] = True
            terms['ownership_subject_to_closing_adjustments'] = True
            if re.search(r'net proceeds|monetization', t, re.I):
                terms['cvr_basis'] = 'Legacy asset monetization net proceeds'
            if re.search(r'may declare', t, re.I):
                terms['cvr_distribution_status'] = 'CONTEMPLATED'
        share_terms=merger_share_consideration(t)
        if share_terms:
            if cash_updates:share_terms.pop('cash_per_share_usd',None)
            terms.update(share_terms)
        verified=[]
        if cash_updates:verified.append('cash_per_share_usd')
        updated_stock=list(re.finditer(r'(?:amended|revised|changed|increased|decreased).{0,50}stock exchange ratio\s+to\s*(\d+(?:\.\d+)?)\s+shares\b',t,re.I))
        if updated_stock:
            terms['stock_exchange_ratio']=float(updated_stock[-1][1]);verified.append('stock_exchange_ratio')
        for clause in sentences(t):
            if re.search(r'\b(?:amended|revised)\b',clause,re.I) and re.search(r'\beach share\b',clause,re.I):
                amended_payout=merger_share_consideration(clause)
                for key in ('cash_per_share_usd','stock_exchange_ratio'):
                    if key in amended_payout:terms[key]=amended_payout[key];verified.append(key)
        if verified:terms['_amendment_verified_fields']=sorted(set(verified))
        if 'cash_per_share_usd' in terms:
            terms['cash_per_share_status']='CONDITIONAL' if terms.get('cash_adjustment_direction') else 'FIXED'
        for key,pattern in [
            ('closing_conditions',r'(?:subject to|conditioned upon).{0,350}?(?:approval|conditions|consents)[^.]*'),
            ('working_capital_adjustment',r'(?:net working capital|net debt).{0,130}adjust\w*|adjust\w*.{0,130}(?:net working capital|net debt)'),
            ('collar_or_election_mechanics',r'(?:exchange ratio collar|collar|election (?:procedures|mechanics)|cash or stock election)[^.]{0,350}'),
            ('cvr_terms',r'(?:contingent value right|\bCVR\b)[^.]{0,500}'),
            ('earnout_terms',r'earn[- ]?out[^.]{0,350}'),
        ]:
            evidence=re.search(pattern,t,re.I)
            if evidence:terms[key]=evidence[0]
        for key,anchor in [('total_transaction_value',r'(?:total|aggregate) (?:transaction|merger|enterprise|equity) value (?:of|is)'),
                           ('termination_fee',r'termination fee (?:of|equal to)'),
                           ('special_dividend',r'special (?:cash )?dividend (?:of|equal to)'),
                           ('debt_assumed_or_repaid',r'(?:assume|repay)(?:d|s)? (?:approximately )?')]:
            value=re.search(anchor+r'\s*(US\$|C\$|\$|€|£)\s*([\d,.]+)\s*(million|billion)?',t,re.I)
            if value:
                terms[key]={'amount':float(value[2].replace(',',''))*{'million':1e6,'billion':1e9,None:1}[(value[3] or '').lower() or None],
                            'currency':CURRENCIES.get(value[1].upper(),'UNVERIFIED'),'evidence':value[0]}
        if completed_merger(t):
            def quantity(pattern):
                m = re.search(pattern, t, re.I)
                return int(float(m.group(1).replace(',', '')) * (1e6 if m.group(2) else 1)) if m else None
            fields = {
                'new_common_shares_issued_reported': r'(?:Company|issuer) issued (?:approximately )?([\d,.]+)\s*(million)? shares of Common Stock',
                'replacement_options_reported': r'([\d,.]+)\s*(million)? Replacement Options',
                'replacement_warrants_reported': r'([\d,.]+)\s*(million)? Replacement Warrants',
                'source_reported_post_merger_common_shares': r'there were (?:approximately )?([\d,.]+)\s*(million)? shares of (?:Combined Company )?common stock issued and outstanding',
                'source_reported_post_merger_fd_shares': r'aggregate of ([\d,.]+)\s*(million)? shares issuable on a fully diluted basis',
            }
            for key, pattern in fields.items():
                value = quantity(pattern)
                if value is not None:
                    terms[key] = value
            if any(key in terms for key in fields):
                terms['capital_counts_as_reported'] = True
                terms['capital_counts_require_reconciliation'] = True
            if re.search(r'all references to share and per share amounts.{0,80}reflect (?:the )?Reverse Stock Split', t, re.I):
                terms['reported_share_units'] = 'POST_REVERSE_SPLIT'
            symbol = re.search(r'(?:common stock|ordinary shares).{0,220}under the ticker symbol [“"]([A-Z]+)[.,”"]', t, re.I)
            if symbol:
                terms['post_transaction_ticker'] = symbol.group(1).upper()
    if kind == 'LIQUIDATION_DISTRIBUTION':
        distribution = None
        for clause in liquidation_evidence(t):
            declaration = re.search(r'\b(?:approved|approves|declared|declares)\b(?P<gap>.{0,100}?)liquidating (?:cash )?distribution', clause, re.I)
            if (not declaration or re.search(r'\bplan\b|contemplat|propos|consider', declaration.group('gap'), re.I)
                    or re.search(r'subject to|contingent upon', clause, re.I)):
                continue
            # A preferred-holder amount is not a common-share distribution.
            entitlement = clause[declaration.start():]
            if re.search(r'preferred', clause, re.I):
                distribution = re.search(r'\$\s*(\d+(?:\.\d+)?)\s+per common share(?!\s+par value)', entitlement, re.I)
            else:
                distribution = re.search(r'liquidating (?:cash )?distribution.{0,90}?\$\s*(\d+(?:\.\d+)?)\s*(?:\([^)]*\)\s*)?per (?:common )?share(?!\s+par value)', entitlement, re.I)
                if not distribution:
                    distribution = re.search(r'\$\s*(\d+(?:\.\d+)?)\s+per (?:common )?share(?!\s+par value).{0,50}liquidating (?:cash )?distribution', entitlement, re.I)
            if distribution:
                break
        if distribution:
            terms['distribution_per_share_usd'] = float(distribution.group(1))
            terms['distribution_status'] = 'DECLARED'
        for key, anchor in [('payment_date', r'(?:special dividend|distribution).{0,30}(?:will be paid|is payable|payable) on|payment date (?:is|of)'),
                            ('record_date', r'record (?:on|date)'),
                            ('ex_dividend_date', r'ex[- ]dividend date (?:is|of|will be)'),
                            ('last_trading_date', r'last (?:day of trading|trading day)(?: on the NYSE)? (?:is|to be|is expected to be)'),
                            ('dissolution_date', r'dissolution[, ]+(?:effective|is planned for)|articles of dissolution.{0,40}(?:on|effective)')]:
            value = _date_after(t, anchor, 60)
            if value:
                terms[key] = value
        before_ex = re.search(MONTH_DATE + r'\s+ex[- ]dividend date', t, re.I)
        if before_ex:
            terms['ex_dividend_date'] = datetime.strptime(before_ex.group(1), '%B %d, %Y').date().isoformat()
        if re.search(r'due bills?|due[- ]bill', t, re.I):
            terms['due_bills'] = True
        if 'dissolution_date' in terms or re.search(r'(?:company|registrant|issuer).{0,80}(?:intends? to|plans? to|will).{0,80}(?:voluntary dissolution|dissolve|terminate its existence)', t, re.I):
            terms['dissolution_status'] = 'PLANNED'
        if 'payment_date' not in terms:
            value = _date_after(t, r'(?:special dividend|distribution) will be paid on', 40)
            if value:
                terms['payment_date'] = value
        if 'record_date' not in terms:
            value = _date_after(t, r'shareholders of record', 80)
            if value:
                terms['record_date'] = value
    if kind == 'LISTING_CAPITAL_STRUCTURE' and adopted_rights_plan(t):
        terms['capital_structure_action'] = 'RIGHTS_PLAN'
    if kind == 'LISTING_CAPITAL_STRUCTURE' and resale_registration(t):
        terms['capital_structure_action'] = 'RESALE_REGISTRATION'
    if kind == 'DEBT_RESTRUCTURING':
        warrant = re.search(r'warrants.{0,100}purchase.{0,60}?(\d[\d,]*)\s+shares.{0,140}exercise price of\s*\$\s*(\d+(?:\.\d+)?)', t, re.I)
        if warrant:
            terms['new_warrant_shares'] = int(warrant.group(1).replace(',', ''))
            terms['new_warrant_exercise_price_usd'] = float(warrant.group(2))
            terms['warrant_reconciliation_required'] = True
        structural = bool(warrant or closed_debt_equity_exchange(t))
        if closed_debt_equity_exchange(t):
            terms['capital_structure_action'] = 'DEBT_EQUITY_EXCHANGE'
            rights = re.search(r'(\d[\d,]*) shares.{0,200}purchased.{0,160}subscription price of\s*\$\s*([\d.]+).{0,100}gross proceeds of\s*\$\s*([\d.]+)\s*million', t, re.I)
            if rights:
                terms.update(rights_offering_shares=int(rights.group(1).replace(',', '')),
                             rights_subscription_price_usd=float(rights.group(2)),
                             rights_gross_proceeds_usd=float(rights.group(3)) * 1e6)
            post = re.search(r'expects to have\s*(\d[\d,]*) shares of Common Stock issued and outstanding', t, re.I)
            if post:
                terms['expected_post_transaction_common_shares'] = int(post.group(1).replace(',', ''))
                terms['post_transaction_share_count_status'] = 'EXPECTED'
            backstop = re.search(r'(\d[\d,]*) shares of Common Stock will be issued to the Backstop Parties', t, re.I)
            if backstop:
                terms['backstop_exchange_common_shares'] = int(backstop.group(1).replace(',', ''))
                terms['backstop_share_issuance_status'] = 'EXPECTED'
            reduction = re.search(r'principal amount.{0,80}will be reduced by\s*\$\s*([\d.]+)\s*million.{0,140}combination of par redemptions', t, re.I)
            if reduction:
                terms['combined_notes_principal_reduction_usd'] = float(reduction.group(1)) * 1e6
                terms['debt_principal_reduction_status'] = 'EXPECTED'
                terms['debt_principal_reduction_scope'] = 'EXCHANGE_AND_PAR_REDEMPTIONS'
        for sentence in re.split(r'(?<=[.;])\s+', t):
            if re.search(r'\bif\b|\bunless\b|\bmay\b|\bwould\b|\bnot\b', sentence, re.I):
                continue
            if re.search(r'(?:debt|notes).{0,80}(?:were|was|has been|have been) converted into.{0,50}(?:equity|common stock)|(?:exchanged|converted).{0,100}(?:debt|notes).{0,100}(?:equity|common stock)|(?:creditors|lenders).{0,60}(?:forgave|forgiven).{0,60}(?:debt|notes)|(?:cured|resolved).{0,40}(?:payment default|actual default)', sentence, re.I):
                structural = True
        routine = bool(re.search(r'amend|amends and restates', t, re.I) and re.search(r'credit(?: and security)? agreement|loan agreement', t, re.I))
        terms['materiality'] = 'STRUCTURAL' if structural else 'ROUTINE' if routine else 'UNVERIFIED'
        commitments = re.search(r'(?:revolving commitments|commitments).{0,60}from\s*\$\s*([\d.]+)\s*million\s+to\s*\$\s*([\d.]+)\s*million', t, re.I)
        if commitments:
            terms['revolving_commitment_before_usd'] = float(commitments.group(1)) * 1e6
            terms['revolving_commitment_after_usd'] = float(commitments.group(2)) * 1e6
            terms['commitment_change_is_debt_reduction'] = False
    if kind == 'ASSET_SALE_ACQUISITION':
        amount = re.search(r'aggregate purchase price.{0,70}?' + MONEY, t, re.I)
        if amount:
            currency = CURRENCIES.get(amount['currency'].upper(), 'UNVERIFIED')
            terms.update(sale_price_amount=float(amount['amount']) * 1e6, sale_price_currency=currency)
            if re.match(r'\s+in cash', t[amount.end():], re.I):
                terms['sale_payment_type'] = 'CASH'
            if currency == 'USD':
                terms['sale_price_estimate_usd'] = terms['sale_price_amount']
            else:
                equivalent = re.search(r'(?:cash consideration paid in (?:the )?acquisition|purchase price.{0,70}?(?:approximately|equivalent to)).{0,30}?US\$\s*([\d.]+)\s*million', t, re.I)
                if equivalent:
                    terms['sale_price_estimate_usd'] = float(equivalent.group(1)) * 1e6
                    terms['usd_equivalent_source'] = 'ISSUER_DISCLOSED'
        earnout = re.search(r'earnout (?:payment )?.{0,50}?up to\s*' + MONEY, t, re.I)
        if earnout:
            terms.update(earnout_max_amount=float(earnout['amount']) * 1e6,
                         earnout_currency=CURRENCIES.get(earnout['currency'].upper(), 'UNVERIFIED'),
                         earnout_conditional=True)
        repurchase = re.search(r'increase.{0,80}repurchase authorization from\s*\$\s*([\d.]+)\s*million to\s*\$\s*([\d.]+)\s*million', t, re.I)
        if repurchase:
            terms['repurchase_total_usd'] = float(repurchase.group(2)) * 1e6
            terms['repurchase_increment_usd'] = (float(repurchase.group(2)) - float(repurchase.group(1))) * 1e6
            terms['repurchase_conditional'] = bool(re.search(r'conditioned upon|only upon.{0,50}closing', t, re.I))
    actual_date = re.search(r'\bOn\s+' + MONTH_DATE, t)
    if actual_date:
        try:
            terms['transaction_date'] = datetime.strptime(actual_date.group(1), '%B %d, %Y').date().isoformat()
        except ValueError:
            pass
    context = capital_context(t)
    if context:
        terms['capital_context'] = context
    return terms


def event_status(text, kind, proof):
    if kind == 'TERMINAL_MERGER': return 'TERMINAL'
    if kind == 'MERGER_TERMINATED': return 'CANCELLED'
    if kind == 'LIQUIDATION_DISTRIBUTION': return 'LIQUIDATING'
    if kind == 'LISTING_CAPITAL_STRUCTURE' and adopted_rights_plan(operative_text(text)): return 'ADOPTED'
    if kind == 'LISTING_CAPITAL_STRUCTURE' and resale_registration(operative_text(text)): return 'REGISTERED'
    if proof <= 1: return 'PRELIMINARY' if proof else 'UNKNOWN'
    return 'COMPLETED' if proof >= 3 else 'SIGNED'


def _read_event_filing(sec, cik, filing):
    primary = sec.submission_text(filing['filename'])
    sources = ['https://www.sec.gov/Archives/' + filing['filename']]
    text = primary
    narratives = [operative_text(primary)]
    lifecycle_narratives=list(narratives)
    term_sources=list(sources)
    if filing.get('form') in {'8-K','8-K/A'} and re.search(r'Exhibit\s+(?:99|2|10)\.|99\.\d', primary, re.I):
        for doc in sec.filing_documents(cik, filing.get('accession'), filing.get('index_url')):
            if (doc['type'].startswith(('EX-99','EX-2'))
                    or (doc['type'].startswith('EX-10') and re.search(r'merger|purchase|transaction',doc.get('description',''),re.I))):
                exhibit = sec.submission_text(doc['url'])
                text += '\n' + exhibit
                narratives.append(operative_text(exhibit))
                sources.append(doc['url'])
                term_sources.append(doc['url'])
                if doc['type'].startswith('EX-99'):lifecycle_narratives.append(operative_text(exhibit))
    narrative = '\n'.join(narratives)
    lifecycle='\n'.join(lifecycle_narratives)
    label, proof, summary = classify_event(lifecycle, cleaned=True)
    terms=event_terms(narrative,label,cleaned=True)
    label=normalized_kind(label,terms,narrative)
    lifecycle='\n'.join(lifecycle_narratives)
    status=event_status(lifecycle,label,proof)
    if label in MERGER_KINDS and not closing_evidence(lifecycle):
        proof=min(proof,2);status=event_status(lifecycle,label,proof)
    return {**filing, 'event_type': label, 'event_proof': proof,
            'event_status': status, 'summary': summary,
            'terms': terms, 'sources': sources,'term_sources':term_sources,
            'text': primary, 'combined_text': text, 'narrative': narrative,'lifecycle_narrative':lifecycle}


def same_merger_counterparty(current, prior):
    parent = merger_parent_name(operative_text(prior['text']))
    if not parent:
        return False
    names = [parent]
    # A shortened brand must be explicitly defined by the original source.
    narrative = prior.get('narrative', operative_text(prior['combined_text']))
    alias = re.escape(parent) + r'\s*(?:\((?:Nasdaq|NYSE):[^)]*\)\s*)?\([“"]([^”"]+)[”"]'
    names.extend(m.group(1) for m in re.finditer(alias, narrative, re.I)
                 if m.group(1).lower() not in {'parent', 'company', 'the company'})
    return any(re.search(r'\b' + re.escape(name) + r'\s*,?\s*(?:and\b|in consultation with\b)', current, re.I)
               for name in names)


def review_material_events(sec, cik, discovered, cfg):
    recent = sec.submissions(cik).get('filings', {}).get('recent', {})
    cutoff = (date.today() - timedelta(days=cfg['event_max_age_days'])).isoformat()
    declared_items = set(re.split(r'[,;]', discovered.get('items', '') or ''))
    eligible_discovered = (discovered.get('form') != '8-K' or not discovered.get('items')
                           or bool(declared_items.intersection(cfg['material_8k_items'] + ['7.01'])))
    filings = {discovered.get('accession') or discovered.get('filename'): dict(discovered)} if eligible_discovered else {}
    for i, form in enumerate(recent.get('form', [])):
        if form != '8-K' or recent['filingDate'][i] < cutoff:
            continue
        items = recent.get('items', [''] * len(recent['form']))[i] or ''
        if not set(re.split(r'[,;]', items)).intersection(cfg['material_8k_items'] + ['7.01']):
            continue
        accession = recent['accessionNumber'][i]
        filings[accession] = {'cik': cik, 'form': form, 'filed': recent['filingDate'][i], 'items': items,
                              'accession': accession, 'filename': f"edgar/data/{int(cik)}/{accession.replace('-', '')}/{recent['primaryDocument'][i]}"}
    reviewed, warnings = [], []
    for filing in filings.values():
        try:
            event = _read_event_filing(sec, cik, filing)
            items = {item.strip() for item in re.split(r'[,;]', filing.get('items', '') or '') if item.strip()}
            # Routine 7.01 announcements stay out; an affirmative merger closing
            # is economically material regardless of the issuer's item choice.
            if (filing.get('form') == '8-K' and items and not items.intersection(cfg['material_8k_items'])
                    and not (event['event_type'] in MERGER_KINDS and event['event_status'] == 'COMPLETED')):
                continue
            reviewed.append(event)
        except Exception as exc:
            warnings.append(f"Event review failed for {filing.get('accession')}: {exc}")
    selected = select_event(reviewed)
    if selected:
        selected = dict(selected)
        selected['selection_reason'] = 'Retain an active merger/liquidation lifecycle; otherwise select the most recent material economic event.'
        if selected['event_type'] in MERGER_KINDS and selected['event_status'] == 'COMPLETED':
            for i, form in enumerate(recent.get('form', [])):
                if form != '25-NSE' or abs((date.fromisoformat(recent['filingDate'][i]) - date.fromisoformat(selected['filed'])).days) > 7:
                    continue
                acc = recent['accessionNumber'][i]
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{recent['primaryDocument'][i]}"
                try:
                    removal = sec.submission_text(url)
                    # Exchange-certified exchange of the registered common class,
                    # not a proposed delisting or removal of preferred/debt alone.
                    exchanged = re.search(r'<input\b[^>]*\bchecked\b[^>]*>\s*17 CFR 240\.12d2-2\(a\)\(3\)', removal, re.I)
                    if exchanged and re.search(r'common (?:stock|shares)|ordinary shares', operative_text(removal), re.I):
                        selected['event_type'], selected['event_status'] = 'TERMINAL_MERGER', 'TERMINAL'
                        selected['terms']['listing_termination_source_accession'] = acc
                        selected['sources'] = list(dict.fromkeys(selected['sources'] + [url]))
                        selected['selection_reason'] += ' Completed merger and exchange-certified common-class exchange terminate the original listing.'
                        break
                except Exception as exc:
                    warnings.append(f'Completed-merger listing review failed for {acc}: {exc}')
        # Economics are independent of the current filing's status vocabulary.
        # Search bounded older agreement/proxy sources whenever a material deal
        # is active; the identity reducer rejects unrelated transactions.
        if selected['event_type'] in MERGER_KINDS | {'TERMINAL_MERGER','ASSET_SALE_ACQUISITION'}:
            oldest = (date.today() - timedelta(days=cfg.get('financial_filing_max_age_days', 210))).isoformat()
            seen = {x.get('accession') for x in reviewed}
            extra = []
            forms = {'8-K','8-K/A','DEFM14A','DEFA14A','DEF 14A','S-4','S-4/A','F-4','F-4/A','424B3','10-Q','10-K'}
            for i, form in enumerate(recent.get('form', [])):
                filed = recent['filingDate'][i]
                if form not in forms or filed < oldest:continue
                acc = recent['accessionNumber'][i]
                if acc in seen:continue
                items = (recent.get('items', [''] * len(recent['form']))[i] or '')
                if form.startswith('8-K') and not set(re.split(r'[,;]',items)).intersection({'1.01','2.01','8.01','7.01'}):continue
                # Ordinary old 8-Ks are outside the catalyst window. Definitive
                # sources and the latest financial note may supplement a live deal.
                filing = {'cik':cik,'form':form,'filed':filed,'accession':acc,
                          'filename':f"edgar/data/{int(cik)}/{acc.replace('-', '')}/{recent['primaryDocument'][i]}"}
                extra.append(filing)
            for filing in extra:
                try:
                    candidate=_read_event_filing(sec,cik,filing)
                    from .transactions import same_transaction
                    if any(same_transaction(prior,candidate) for prior in reviewed):
                        reviewed.append(candidate)
                except Exception as exc:
                    warnings.append(f"Transaction source review failed for {filing['accession']}: {exc}")
            terminal=selected if selected['event_status']=='TERMINAL' else None
            selected=select_event(reviewed)
            if terminal:
                selected['event_type'],selected['event_status']='TERMINAL_MERGER','TERMINAL'
                selected['terms'].update({k:v for k,v in terminal['terms'].items() if k=='listing_termination_source_accession'})
                selected['sources']=list(dict.fromkeys(selected['sources']+terminal['sources']))
            selected['selection_reason']='Transaction identity links explicit lifecycle evidence and independently sourced valid economics.'
    return selected, reviewed, warnings
