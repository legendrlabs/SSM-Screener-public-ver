"""Review source-backed transactions and retain the active economic catalyst."""
from datetime import date, datetime, timedelta
import re

from .event_rules import classify_event, operative_text, liquidation_evidence, adopted_rights_plan, resale_registration, closed_debt_equity_exchange, merger_share_consideration, merger_parent_name, completed_merger, MERGER_KINDS

PRIORITY = {'TERMINAL_MERGER': 110, 'MERGER_TERMINATED': 105,
            'LIQUIDATION_DISTRIBUTION': 100, 'MERGER_CASH_CVR': 90, 'REVERSE_MERGER_CVR': 90, 'MERGER_CVR_UNVERIFIED': 85,
            'MERGER_REVERSE_MERGER': 85, 'MERGER_CASH_STOCK': 85, 'MERGER_STOCK': 85, 'ASSET_SALE_ACQUISITION': 70,
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
        cash = re.search(r'\$\s*(\d+(?:\.\d+)?)\s+per share.{0,45}?in cash', t, re.I)
        if not cash:
            cash = re.search(r'converted into.{0,100}?\$\s*(\d+(?:\.\d+)?)\s+(?:cash|per share)', t, re.I)
        if cash and kind != 'REVERSE_MERGER_CVR':
            terms['cash_per_share_usd'] = float(cash.group(1))
        if kind in {'MERGER_CASH_CVR', 'REVERSE_MERGER_CVR', 'MERGER_CVR_UNVERIFIED'}:
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
        if kind in {'MERGER_CASH_STOCK', 'MERGER_STOCK'}:
            terms.update(merger_share_consideration(t))
            if kind == 'MERGER_STOCK':
                terms.pop('cash_per_share_usd', None)
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
    if filing.get('form') == '8-K' and re.search(r'Exhibit\s+99\.|99\.\d', primary, re.I):
        for doc in sec.filing_documents(cik, filing.get('accession'), filing.get('index_url')):
            if doc['type'].startswith('EX-99'):
                exhibit = sec.submission_text(doc['url'])
                text += '\n' + exhibit
                narratives.append(operative_text(exhibit))
                sources.append(doc['url'])
    narrative = '\n'.join(narratives)
    label, proof, summary = classify_event(narrative, cleaned=True)
    return {**filing, 'event_type': label, 'event_proof': proof,
            'event_status': event_status(narrative, label, proof), 'summary': summary,
            'terms': event_terms(narrative, label, cleaned=True), 'sources': sources,
            'text': primary, 'combined_text': text, 'narrative': narrative}


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
        current = operative_text(selected['combined_text'])
        missing_payout = not any(k in selected['terms'] for k in ('cash_per_share_usd', 'stock_exchange_ratio', 'legacy_holder_ownership_pct'))
        if (selected['event_type'] in MERGER_KINDS and missing_payout
                and re.search(r'regulatory|HSR|Hart-Scott|waiting period', current, re.I)
                and re.search(r'Merger Agreement', current, re.I)
                and not re.search(r'(?:amended|amendment to|revised|new).{0,45}(?:merger agreement|agreement and plan of merger|consideration)|(?:merger agreement|consideration).{0,25}(?:amended|revised)', current, re.I)):
            oldest = (date.today() - timedelta(days=cfg.get('financial_filing_max_age_days', 210))).isoformat()
            candidates = list(reviewed)
            for i, form in enumerate(recent.get('form', [])):
                if (form == '8-K' and oldest <= recent['filingDate'][i] < cutoff
                        and '1.01' in (recent.get('items', [''] * len(recent['form']))[i] or '')):
                    acc = recent['accessionNumber'][i]
                    filing = {'cik': cik, 'form': form, 'filed': recent['filingDate'][i], 'accession': acc,
                              'filename': f"edgar/data/{int(cik)}/{acc.replace('-', '')}/{recent['primaryDocument'][i]}"}
                    try:
                        candidates.append(_read_event_filing(sec, cik, filing))
                    except Exception as exc:
                        warnings.append(f'Merger term source review failed for {acc}: {exc}')
            for prior in sorted(candidates, key=lambda x: x.get('filed', ''), reverse=True):
                if (prior['event_type'] in MERGER_KINDS and prior['event_proof'] >= 2
                        and same_merger_counterparty(current, prior)
                        and any(k in prior['terms'] for k in ('cash_per_share_usd', 'stock_exchange_ratio'))):
                    selected['terms'] = {k: v for k, v in prior['terms'].items() if k != 'transaction_date'} | selected['terms']
                    selected['terms'].update(merger_terms_source_accession=prior['accession'], merger_terms_source_date=prior['filed'])
                    selected['sources'] = list(dict.fromkeys(selected['sources'] + prior['sources']))
                    selected['event_type'] = prior['event_type']
                    selected['summary'] = prior['summary']
                    selected['selection_reason'] += ' Consideration retained from the original same-counterparty agreement; latest regulatory update retained.'
                    break
    return selected, reviewed, warnings
