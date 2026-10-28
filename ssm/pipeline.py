from __future__ import annotations
import csv, json, os
from pathlib import Path
from .models import Candidate, Dilution
from .event_rules import classify_event
from .dilution import heuristic_extract_dilution, apply_override
from .gates import evaluate_gates
from .scoring import score_candidate, bucket_candidate
from .providers.sec import SecClient, latest_fact_record, filing_risk_flags
from .providers.market import market_snapshot, market_snapshots
from .financial_review import financial_note_hits, conservative_merge_dilution, cover_page_common_shares, extract_atm_remaining_usd
from .events import review_material_events, event_terms, event_status
from .securities import resolve_security
from .recapitalization import reconcile_capital_context
from .capital_evidence import completed_warrant_exercise_evidence
from .ma_discovery import TENDER_FORMS, name_index, discover
from .financial_recapitalization import financial_capital_contexts

OFFERING_FORMS = {"S-1", "S-3", "424B3", "424B5"}
OWNERSHIP_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
PROXY_FORMS = {"DEF 14A", "PRE 14A"}

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_watchlist(path):
    p = Path(path)
    if not p.exists():
        return set()
    with p.open(encoding="utf-8") as f:
        return {(r.get("ticker") or "").strip().upper() for r in csv.DictReader(f) if (r.get("ticker") or "").strip()}

def _ticker_map(sec):
    by_cik, by_ticker = {}, {}
    for x in sec.exchange_tickers():
        cik = str(int(x.get("cik")))
        t = str(x.get("ticker", "")).upper()
        rec = {"ticker": t, "name": x.get("name", ""), "exchange": x.get("exchange", ""), "cik": cik}
        by_cik.setdefault(cik, []).append(rec)
        by_ticker[t] = rec
    return by_cik, by_ticker

def _common_shares(facts):
    """Return dated SEC common-shares evidence, or (0, None)."""
    record = latest_fact_record(facts, "EntityCommonStockSharesOutstanding")
    try:
        return (float(record["val"]), record) if record and float(record["val"]) > 0 else (0.0, None)
    except (TypeError, ValueError):
        return 0.0, None

def _items(filing):
    return {x.strip() for x in (filing.get("items") or "").replace(";", ",").split(",") if x.strip()}

def _metadata_event(filing):
    form, items = filing.get("form", ""), _items(filing)
    if form == "8-K":
        rules = [
            ("2.01", "ASSET_SALE_ACQUISITION", 3),
            ("5.01", "CONTROL_CHANGE", 3),
            ("3.02", "STRATEGIC_INVESTMENT_PIPE", 2),
            ("2.03", "FINANCING_DEBT", 2),
            ("1.01", "MATERIAL_DEFINITIVE_AGREEMENT", 2),
            ("5.03", "LISTING_CAPITAL_STRUCTURE", 1),
            ("5.07", "CORPORATE_ACTION", 1),
            ("8.01", "OTHER", 1),
        ]
        for item, label, proof in rules:
            if item in items:
                return label, proof, f"8-K Item {item} metadata"
        return "OTHER", 0, "8-K metadata"
    if form in OFFERING_FORMS:
        return "SECURITIES_OFFERING", 2, f"{form} financing filing"
    if form in OWNERSHIP_FORMS:
        return "OWNERSHIP_CHANGE", 1, f"{form} ownership filing"
    if form in PROXY_FORMS:
        return "CORPORATE_ACTION", 1, f"{form} proxy filing"
    return "OTHER", 0, form

def _material(filing, cfg):
    if filing.get("form") != "8-K":
        return filing.get("form") in set(cfg["event_forms"])
    return bool(_items(filing) & set(cfg["material_8k_items"]))

def _watch_filing(sec, cik, event_forms):
    r = sec.submissions(cik).get("filings", {}).get("recent", {})
    n = len(r.get("form", []))
    for i in range(n):
        form = r.get("form", [""] * n)[i]
        if form not in event_forms:
            continue
        filed = r.get("filingDate", [""] * n)[i]
        acc = r.get("accessionNumber", [""] * n)[i]
        doc = r.get("primaryDocument", [""] * n)[i]
        items = r.get("items", [""] * n)[i] if i < len(r.get("items", [])) else ""
        return {
            "cik": cik, "form": form, "filed": filed, "accession": acc,
            "items": items or "", "primary_document": doc,
            "filename": f"edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}",
            "source": "submissions-watchlist",
        }
    return None

def build_candidate(sec, meta, filing, overrides, cfg, snapshot=None):
    c = Candidate(ticker=meta["ticker"], name=meta["name"], exchange=meta["exchange"], cik=meta["cik"])
    c.latest_event_date = filing.get("filed")
    c.latest_event_form = filing.get("form")
    c.latest_event_accession = filing.get("accession") or filing.get("filename")
    c.event_type, c.event_proof, c.event_summary = _metadata_event(filing)
    c.most_recent_filing_date = filing.get('filed')
    try:
        resolved = meta if meta.get('security_type') else resolve_security(sec, meta, filing)
        for key in ('security_type', 'security_title', 'security_source'):
            setattr(c, key, resolved.get(key, ''))
    except Exception as exc:
        c.security_type = 'UNKNOWN'
        c.data_warnings.append(f'SEC security class review failed: {exc}')
    if c.security_type != 'COMMON_EQUITY':
        if c.security_type != 'UNKNOWN' and filing.get('filename'):
            # Keep the exclusion's filing content inspectable without assigning
            # corporate common-share counts or market prices to a bond/fund.
            try:
                body = sec.submission_text(filing['filename'])
                c.event_type, c.event_proof, c.event_summary = classify_event(body)
                c.event_status = event_status(body, c.event_type, c.event_proof)
                c.event_terms = event_terms(body, c.event_type)
                c.event_sources = ['https://www.sec.gov/Archives/' + filing['filename']]
            except Exception as exc:
                c.event_review_complete = False
                c.data_warnings.append(f'Excluded security filing content unavailable: {exc}')
        c.gate_status, reasons = evaluate_gates(c, cfg)
        c.data_warnings.extend(reasons)
        c.priority_score = score_candidate(c)
        c.bucket = bucket_candidate(c)
        return c

    if snapshot:
        for k, v in snapshot.items():
            setattr(c, k, v)
    else:
        try:
            for k, v in market_snapshot(c.ticker).items():
                setattr(c, k, v)
        except Exception as e:
            c.data_warnings.append(f"Market data error: {e}")

    financial_record = None
    try:
        financial_record = sec.latest_financial_record(meta["cik"])
        if financial_record:
            c.latest_financial_filing_date = financial_record.get("filed")
            c.latest_financial_form = financial_record.get("form")
            c.latest_financial_accession = financial_record.get("accession")
        common, share_record = _common_shares(sec.companyfacts(meta["cik"]))
        if common > 0:
            c.common_shares_as_of = share_record.get("end")
            c.common_shares_source = (
                "SEC companyfacts as of " + (c.common_shares_as_of or "date unresolved")
                + ", filed " + share_record.get("filed", "unknown")
            )
    except Exception as e:
        common = 0.0
        c.data_warnings.append(f"SEC facts error: {e}")

    c.dilution = apply_override(
        Dilution(common_shares=common, source="SEC companyfacts metadata precheck", confidence="low"),
        overrides.get(c.ticker, {}),
    )

    mc = c.basic_market_cap()
    if mc is not None and mc > cfg["market_cap_expand_max"]:
        c.gate_status = c.bucket = "REJECT"
        c.data_warnings.append("Market cap above expanded universe ceiling; filing body skipped.")
        c.priority_score = score_candidate(c)
        return c

    selected = None
    reviewed = []
    try:
        selected, reviewed, event_warnings = review_material_events(sec, meta['cik'], filing, cfg)
        c.event_review_complete = not event_warnings and selected is not None
        c.data_warnings.extend(event_warnings)
        c.event_history = [{k: x.get(k) for k in ('filed', 'accession', 'event_type', 'event_status', 'terms', 'sources')} for x in reviewed]
        if selected:
            filing = selected
            c.latest_event_date = selected.get('filed')
            c.latest_event_form = selected.get('form')
            c.latest_event_accession = selected.get('accession')
            c.event_type = selected['event_type']
            c.event_proof = selected['event_proof']
            c.event_summary = selected['summary']
            c.event_status = selected['event_status']
            c.event_terms = selected['terms']
            c.event_sources = selected['sources']
            c.event_selection_reason = selected['selection_reason']
    except Exception as exc:
        c.event_review_complete = False
        c.data_warnings.append(f'Material event review failed: {exc}')
    if c.event_status in {'TERMINAL', 'CANCELLED'}:
        c.dilution = Dilution(source='Terminal transaction: no active common-equity economics', confidence='low')
        c.price = c.adv20_usd = None
        c.gate_status, reasons = evaluate_gates(c, cfg)
        c.data_warnings.extend(reasons)
        c.priority_score = score_candidate(c)
        c.bucket = bucket_candidate(c)
        return c

    txt = ""
    dilution_evidence_complete = False
    try:
        if selected:
            txt = selected['text']
        elif filing.get("filename"):
            txt = sec.submission_text(filing["filename"])
    except Exception as e:
        c.data_warnings.append(f"Filing-text retrieval error: {e}")

    if txt:
        label, proof, summary = classify_event(txt)
        if label != "OTHER" and not selected:
            c.event_type = label
        if not selected:
            c.event_proof = max(c.event_proof, proof)
        if summary and not selected:
            c.event_summary = summary
        for k, v in filing_risk_flags(txt).items():
            setattr(c, k, v)
        d, warnings = heuristic_extract_dilution(txt, common, event_context=True)
        dilution_evidence_complete = not warnings
        d.atm_remaining_usd = max(d.atm_remaining_usd, extract_atm_remaining_usd(txt))
        c.dilution = apply_override(d, overrides.get(c.ticker, {}))
        c.data_warnings.extend(warnings)

        # Targeted exhibit second pass. Many microcap financing terms live in
        # EX-4 / EX-10 / EX-99 rather than the 8-K body. Only follow exhibits
        # when the primary event filing signals dilution but does not resolve it,
        # or when the event itself is an offering filing.
        needs_exhibits = bool(warnings) or filing.get("form") in OFFERING_FORMS
        if needs_exhibits and filing.get("accession"):
            try:
                exhibits = sec.relevant_exhibit_texts(
                    meta["cik"],
                    filing.get("accession"),
                    index_url=filing.get("index_url"),
                    max_docs=6,
                )
                c.exhibit_review_complete = True
                c.exhibit_documents_reviewed = [x.get("type", "") for x in exhibits]
                for exhibit in exhibits:
                    ex_d, ex_warnings = heuristic_extract_dilution(exhibit.get("text", ""), common, event_context=True)
                    dilution_evidence_complete = dilution_evidence_complete and not ex_warnings
                    ex_d.atm_remaining_usd = max(
                        ex_d.atm_remaining_usd,
                        extract_atm_remaining_usd(exhibit.get("text", "")),
                    )
                    ex_d.source = f"{exhibit.get('type', 'EX')} exhibit parser"
                    c.dilution = conservative_merge_dilution(c.dilution, ex_d)
                    c.data_warnings.extend(ex_warnings)
                c.dilution = apply_override(c.dilution, overrides.get(c.ticker, {}))
            except Exception as e:
                dilution_evidence_complete = False
                c.data_warnings.append(f"Exhibit second-pass error: {e}")
    elif c.dilution.confidence != "high":
        c.data_warnings.append("Event filing body unavailable; dilution verification incomplete.")

    # Event priority chooses the catalyst, never which capital changes exist.
    # Financing after the financial filing remains incremental even when a
    # later routine contract becomes the representative event.
    for interim in reviewed:
        if interim.get('accession') == c.latest_event_accession:
            continue
        baseline_date = (financial_record or {}).get('report_date') or (financial_record or {}).get('filed', '')
        if baseline_date and interim.get('filed', '') < baseline_date:
            continue
        interim_d, interim_warnings = heuristic_extract_dilution(interim.get('combined_text', ''), common, event_context=True)
        if interim['terms'].get('warrant_reconciliation_required'):
            interim_d.confidence = 'low'
            interim_warnings.append('New warrant tranche requires reconciliation with the financial baseline.')
        if interim_warnings or any(getattr(interim_d, key) for key in ('pre_funded_shares','warrants_itm_shares','converts_shares','preferred_shares_equiv','sbc_rsus_shares')):
            c.dilution = conservative_merge_dilution(c.dilution, interim_d)
            dilution_evidence_complete = dilution_evidence_complete and not interim_warnings
            c.data_warnings.extend(f"Interim capital event {interim.get('accession')}: {warning}" for warning in interim_warnings)

    # Mandatory second pass: read the latest 10-Q/10-K body for notes that often
    # contain warrants, converts, preferreds, SBC, related-party items, liquidity
    # language and subsequent events. Event discovery and financial validation are
    # deliberately separate stages.
    financial_text = ""
    if financial_record and financial_record.get("filename"):
        try:
            financial_text = sec.submission_text(financial_record["filename"])
            if not financial_text.strip():
                raise ValueError('Financial filing body is empty')
            c.financial_note_hits = financial_note_hits(financial_text)
            cover_common = cover_page_common_shares(financial_text)
            common_resolved_from_cover = common <= 0 and cover_common > 0
            if common <= 0 and cover_common > 0:
                common = cover_common
                c.dilution.common_shares = cover_common
                c.common_shares_source = "10-Q/10-K cover"
                c.data_warnings.append("Common shares resolved from latest 10-Q/10-K cover page.")
            elif common > 0 and cover_common > 0:
                ratio = cover_common / common
                if ratio < 0.8 or ratio > 1.25:
                    c.share_count_conflict = True
                    c.data_warnings.append(
                        f"Companyfacts vs cover-page shares differ materially ({common:.0f} vs {cover_common:.0f})."
                    )
            for k, v in filing_risk_flags(financial_text).items():
                setattr(c, k, bool(getattr(c, k)) or bool(v))
            fin_dilution, fin_warnings = heuristic_extract_dilution(financial_text, common)
            fin_dilution.atm_remaining_usd = max(
                fin_dilution.atm_remaining_usd,
                extract_atm_remaining_usd(financial_text),
            )
            fin_dilution.source = f"{financial_record.get('form')} second-pass filing parser"
            if (common_resolved_from_cover and dilution_evidence_complete
                    and c.dilution.confidence == 'low'
                    and overrides.get(c.ticker, {}).get('confidence') != 'low'):
                # The cover fixes missing common shares only. Unresolved event
                # or exhibit instruments still prevent a confidence upgrade.
                c.dilution.confidence = 'medium'
            c.dilution = conservative_merge_dilution(c.dilution, fin_dilution)
            c.dilution = apply_override(c.dilution, overrides.get(c.ticker, {}))
            c.data_warnings.extend(fin_warnings)
            c.financial_review_complete = True
        except Exception as e:
            c.data_warnings.append(f"Financial filing second-pass error: {e}")
    else:
        c.data_warnings.append("Latest 10-Q/10-K primary document unavailable.")

    if financial_text and c.financial_review_complete:
        # Historical financial evidence is read-only: it cannot re-add shares,
        # subtract FD instruments, or rewrite the representative 8-K catalyst.
        try:
            c.validation_audit.update(history_common_before=c.dilution.common_shares,history_confidence_before=c.dilution.confidence)
            financial_capital = financial_capital_contexts(financial_text, financial_record, reviewed,
                                                         baseline={'share_count_conflict':c.share_count_conflict})
            if financial_capital:
                c.event_terms['financial_capital_context_history'] = financial_capital
                if any(row['context'].get('reconciliation_required') for row in financial_capital):
                    c.dilution.confidence = 'low'
                    c.data_warnings.append('Current financial capital events require FD reconciliation; historical issuance is not re-added and financing links do not waive dilution risk.')
            c.validation_audit.update(history_common_after=c.dilution.common_shares,history_confidence_after=c.dilution.confidence)
        except Exception as exc:
            c.dilution.confidence = 'low'
            c.event_terms['financial_capital_review_incomplete'] = True
            c.data_warnings.append(f'Financial capital context review incomplete: {exc}')

    capital_events = list(reviewed)
    if selected and not any(x.get('accession') == selected.get('accession') for x in capital_events):
        capital_events.append(selected)
    baseline_date = (financial_record or {}).get('report_date') or (financial_record or {}).get('filed')
    capital_history = []
    reissued_identities = {identity for event in capital_events
                          for identity in event.get('terms', {}).get('capital_context', {}).get('reissued_instrument_identities', [])}
    for capital_event in sorted(capital_events, key=lambda x: (x.get('filed', ''), x.get('accession', ''))):
        context = capital_event.get('terms', {}).get('capital_context')
        if not context:
            continue
        # Filing date and the first agreement date are not proof of the actual
        # capital action's date. Unknown/mixed chronology stays unresolved.
        event_date = context.get('transaction_date')
        # Past financing cannot be added to an already newer financial baseline.
        if event_date and baseline_date and event_date < baseline_date:
            continue
        reconcile_capital_context(c.dilution, context, financial_text, event_date, baseline_date, reissued_identities)
        capital_history.append({'accession': capital_event.get('accession'), 'filed': capital_event.get('filed'),
                                'sources': capital_event.get('sources', []), 'context': context})
    if capital_history:
        c.event_terms['capital_context_history'] = capital_history
        if any(x['context'].get('reconciliation_required') for x in capital_history):
            c.dilution.confidence = 'low'
            c.data_warnings.append('Capital issuance/retirement requires complete post-transaction FD reconciliation; economic context does not clear dilution warnings.')

    # A companyfacts balance predating a verified capital transaction is not
    # a certified *current* common-share count. Do not automatically add shares
    # from overlapping 8-K descriptions or apply an uncertain warrant ratio.
    # Mask derived market-cap metrics until a newer dated SEC common balance
    # and the outstanding instruments have been reconciled.
    if c.common_shares_as_of:
        post_baseline_events = [
            e for e in capital_events
            if (e.get('filed') or '') > c.common_shares_as_of
            and (
                (e.get('terms', {}).get('capital_context', {}).get('actual_common_issued') or 0) > 0
                or (e.get('terms', {}).get('capital_context', {}).get('actual_common_equivalent_shares') or 0) > 0
                or (e.get('event_status') == 'COMPLETED'
                    and (e.get('terms', {}).get('warrant_reconciliation_required')
                         or completed_warrant_exercise_evidence(e.get('combined_text', ''))))
            )
        ]
        if post_baseline_events:
            c.event_terms['common_share_baseline_stale'] = True
            c.dilution.confidence = 'low'
            c.data_warnings.append(
                f"Common-share balance as of {c.common_shares_as_of} predates "
                f"{len(post_baseline_events)} completed/reportable capital event(s); "
                "updated share count and instrument retirements are unresolved."
            )

    if c.event_terms.get('warrant_reconciliation_required') and c.dilution.confidence != 'high':
        c.dilution.confidence = 'low'
        c.data_warnings.append('New event warrant tranche must be reconciled against the financial filing baseline; max() cannot establish the updated total.')
    if c.event_status == 'LIQUIDATING':
        last = c.event_terms.get('last_trading_date')
        from datetime import date
        if last and date.today().isoformat() > last:
            c.event_review_complete = False
            c.data_warnings.append('Planned last trading date has passed; current listing/liquidation status requires a newer source.')

    if c.event_terms.get('capital_counts_require_reconciliation'):
        c.dilution.confidence = 'low'
    if c.event_terms.get('post_transaction_ticker', c.ticker) != c.ticker:
        c.price = c.adv20_usd = None
    c.data_warnings = list(dict.fromkeys(c.data_warnings))

    c.gate_status, reasons = evaluate_gates(c, cfg)
    c.data_warnings.extend(reasons)
    c.priority_score = score_candidate(c)
    c.bucket = bucket_candidate(c)
    return c

def _filing_key(raw):
    """Stable SEC identity; never deduplicate using the ticker or filing date."""
    cik = str(int(raw["cik"]))
    form = str(raw.get("form") or "")
    accession = raw.get("accession") or raw.get("filename") or raw.get("index_url")
    if not accession:
        raise ValueError("SEC discovery filing has no stable accession or URL")
    return "|".join((cik, form, str(accession)))


def scan(days=7, config_path="config/default.json", watchlist_path="config/watchlist.csv",
         overrides_path="config/overrides.json", incremental_state_path=None):
    cfg = load_json(config_path)
    previous_entries = {}
    previous_run_id = None
    if incremental_state_path is not None:
        previous = load_json(incremental_state_path)
        if previous.get("schema_version") != 1 or not isinstance(previous.get("entries"), dict):
            raise ValueError("Incompatible incremental checkpoint; run full scan")
        previous_entries = previous["entries"]
        previous_run_id = previous.get("run_id")
        if not previous_run_id:
            raise ValueError("Incremental checkpoint missing source run ID")
        # A delta must inherit the *verified full* baseline, never substitute
        # its shorter lookback or the previous delta's completion timestamp.
        prior_full_at = previous.get("last_full_completed_at_utc")
        prior_full_days = previous.get("last_full_lookback_days")
        if (not isinstance(prior_full_at, str) or not prior_full_at.strip()
                or type(prior_full_days) is not int or prior_full_days < 7):
            raise ValueError("Incremental checkpoint missing a seven-day full baseline")
    overrides = load_json(overrides_path) if Path(overrides_path).exists() else {}
    sec = SecClient()
    by_cik, by_ticker = _ticker_map(sec)
    latest = {}
    # Acquisition discovery is independent of the acquirer's microcap gate.
    ma_index = name_index(by_ticker)
    ma_linked = {}
    ma_reads = 0
    ma_unmatched = 0
    ma_budget_exceeded = 0
    ma_read_limit = max(0, min(200, int(cfg.get("ma_discovery_max_acquirer_8k_reads", 80))))
    # Rolling ledger means the same accession in SEC's overlapping Atom
    # pages is not treated as a newly discovered event on every run.
    from datetime import date, timedelta
    ledger_cutoff = (date.today() - timedelta(days=10)).isoformat()
    encountered = {k: v for k, v in previous_entries.items()
                   if isinstance(v, str) and v >= ledger_cutoff}
    discovery_count = 0
    new_discovery_count = 0
    for raw in sec.recent_filings(days, cfg["event_forms"]):
        discovery_count += 1
        key = _filing_key(raw)
        if key in encountered and incremental_state_path is not None:
            continue
        new_discovery_count += 1
        encountered[key] = raw.get("filed") or date.today().isoformat()
        metas = by_cik.get(str(int(raw["cik"])), [])
        if not metas and raw.get("form") not in TENDER_FORMS:
            continue
        try:
            filing = sec.enrich_filing(str(int(raw["cik"])), raw)
        except Exception:
            # Do not checkpoint an unverified filing as fully processed.
            encountered.pop(key, None)
            filing = raw
        if not _material(filing, cfg):
            continue
        form = filing.get("form", "")
        is_tender = form in TENDER_FORMS
        # Only Item 1.01 / 2.01 acquirer reports get a bounded secondary
        # text read. Never let the acquirer's market cap block this lookup.
        is_buyer_8k = (form in {"8-K", "8-K/A"}
                       and bool(_items(filing) & {"1.01", "2.01"}))
        should_read = is_tender or (is_buyer_8k and ma_reads < ma_read_limit)
        if is_buyer_8k and not is_tender and not should_read:
            ma_budget_exceeded += 1
            # Do not claim an unchecked filing is processed in the delta ledger.
            encountered.pop(key, None)
        if should_read:
            if is_buyer_8k:
                ma_reads += 1
            try:
                linked = discover(sec, filing, ma_index)
                if linked:
                    t = linked.ticker
                    prior = ma_linked.get(t)
                    if prior is None:
                        ma_linked[t] = linked
                    else:
                        # Every source stays auditable; a newer completed or
                        # cancelled filing overrides older signed conditions.
                        for url in linked.event_sources:
                            if url not in prior.event_sources:
                                prior.event_sources.append(url)
                        if (linked.latest_event_date or "") >= (prior.latest_event_date or ""):
                            linked.event_sources = prior.event_sources
                            ma_linked[t] = linked
                elif is_tender:
                    ma_unmatched += 1
            except Exception:
                # SEC failures must not poison the incremental checkpoint.
                encountered.pop(key, None)
                ma_unmatched += 1
        for meta in metas:
            if meta['exchange'] not in cfg['exchanges']:
                continue
            t = meta['ticker']
            if t not in latest or (filing.get('filed') or '') > (latest[t].get('filed') or ''):
                latest[t] = filing

    event_forms = set(cfg["event_forms"])
    for t in load_watchlist(watchlist_path):
        if t in latest or t not in by_ticker:
            continue
        try:
            f = _watch_filing(sec, by_ticker[t]["cik"], event_forms)
            if f:
                latest[t] = f
        except Exception:
            pass

    for ticker, filing in latest.items():
        try:
            by_ticker[ticker] = resolve_security(sec, by_ticker[ticker], filing)
        except Exception:
            by_ticker[ticker] = {**by_ticker[ticker], 'security_type': 'UNKNOWN'}
    eligible = [t for t in latest if by_ticker[t].get('security_type') == 'COMMON_EQUITY']
    snapshots = market_snapshots(eligible) if eligible else {}
    out = []
    for t, filing in latest.items():
        try:
            out.append(build_candidate(sec, by_ticker[t], filing, overrides, cfg, snapshots.get(t)))
        except Exception as e:
            c = Candidate(ticker=t, name=by_ticker[t]["name"], exchange=by_ticker[t]["exchange"], cik=by_ticker[t]["cik"])
            c.data_warnings.append(f"Pipeline error: {e}")
            out.append(c)

    # Target issuer is a distinct discovery record. Do not insert the large
    # acquirer into the microcap investment universe or apply its equity data
    # to a different listed subject company.
    by_candidate = {c.ticker: c for c in out}
    for ticker, linked in ma_linked.items():
        existing = by_candidate.get(ticker)
        if existing is not None:
            # A verified target-side merger can be retained, but a routine
            # filing, unrelated REJECT, or stale event must not mask discovery.
            if existing.event_type in {
                "MERGER_CASH", "MERGER_CASH_CVR", "MERGER_STOCK",
                "MERGER_CASH_STOCK", "MERGER_UNVERIFIED", "MERGER_TERMINATED",
                "TERMINAL_MERGER",
            } and existing.event_review_complete:
                existing.discovery_status = "M&A_DISCOVERY_REVIEW_REQUIRED"
                for url in linked.event_sources:
                    if url not in existing.event_sources:
                        existing.event_sources.append(url)
                existing.event_terms.setdefault("third_party_discovery", linked.event_terms)
                continue
            out.remove(existing)
        out.append(linked)

    # A processing exception should be retried on the next incremental run,
    # rather than being concealed forever by the accession checkpoint.
    for c in out:
        if any(str(w).startswith("Pipeline error:") for w in c.data_warnings):
            try:
                encountered.pop(_filing_key(latest[c.ticker]), None)
            except (KeyError, ValueError):
                pass

    # One issuer can list multiple common classes. Keep the SEC ticker-master's
    # first verified common class as representative, never a listed note.
    represented = set()
    order = {t: i for i, t in enumerate(by_ticker)}
    for c in sorted(out, key=lambda x: order.get(x.ticker, 10**9)):
        if c.security_type != 'COMMON_EQUITY':
            continue
        if c.cik in represented:
            c.gate_status = c.bucket = 'EXCLUDED'
            c.data_warnings.append('Duplicate common class for an issuer already represented in this scan.')
            c.priority_score = 0
        else:
            represented.add(c.cik)

    cfg["_ma_discovery_count"] = len(ma_linked)
    cfg["_ma_discovery_form_unmatched_count"] = ma_unmatched
    cfg["_ma_acquirer_8k_reads"] = ma_reads
    cfg["_ma_8k_budget_exceeded_count"] = ma_budget_exceeded
    cfg["_ma_discovery_partial"] = bool(ma_budget_exceeded or ma_unmatched)
    cfg["_sec_discovery_mode"] = sec.last_discovery_mode or os.getenv("SSM_SEC_DISCOVERY_MODE", "auto")
    cfg["_scan_scope"] = "INCREMENTAL_DELTA" if incremental_state_path is not None else "FULL"
    cfg["_incremental_source_run_id"] = previous_run_id
    cfg["_discovered_filing_count"] = discovery_count
    cfg["_new_filing_count"] = new_discovery_count
    cfg["_seen_filings"] = {
        "schema_version": 1, "ma_discovery_version": 1,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "entries": encountered,
        "last_full_completed_at_utc": None,
        "last_full_lookback_days": None,
    }
    if incremental_state_path is not None:
        # Preserve both fields through pipeline -> report -> verifier -> next
        # artifact. verify_scan_outputs independently checks the >=7-day anchor.
        cfg["_seen_filings"]["last_full_completed_at_utc"] = prior_full_at
        cfg["_seen_filings"]["last_full_lookback_days"] = prior_full_days
    out.sort(key=lambda c: (c.bucket == "A_RESEARCH_NOW", c.priority_score or -1), reverse=True)
    return out, cfg
