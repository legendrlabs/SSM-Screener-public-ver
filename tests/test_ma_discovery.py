"""Offline SEC M&A cross-issuer discovery regression fixtures.

Representative compact fact patterns from the buyer 8-K and tender schedule;
tests do not contact EDGAR and contain no ticker-specific production branches.
"""
import csv
from datetime import date
import json
from pathlib import Path

import pytest
from ssm.ma_discovery import TENDER_FORMS, name_index, discover, extract_terms
from ssm import pipeline
from ssm.models import Candidate
from ssm.report import write_outputs

ACQUIRER = {"ticker": "ENS", "name": "EnerSys", "exchange": "NYSE", "cik": "1289308"}
TARGET = {"ticker": "ULBI", "name": "Ultralife Corp", "exchange": "Nasdaq", "cik": "875657"}
EXTRA = {"ticker": "ELSE", "name": "Elsewhere Corporation", "exchange": "Nasdaq", "cik": "900001"}

MERGER_8K = """
On October 27, 2026, EnerSys entered into an Agreement and Plan of Merger with
EnerSys Mergersub Inc. and Ultralife Corporation. The Merger Agreement provides
for the acquisition of Ultralife by Parent through a tender offer followed by a
merger. The offer is to purchase all outstanding Ultralife common shares for
$16.00 per Share, net to seller in cash. The offer is subject to regulatory
approval and the minimum tender condition; the tender has not yet closed.
"""
TENDER_COVER = """
SCHEDULE TO
ULTRALIFE CORPORATION
(Name of Subject Company)
ENERSYS MERGERSUB INC.
(Offeror)
This Schedule TO relates to a tender offer for outstanding shares of Ultralife
Corporation for $16.00 per Share payable in cash. This transaction is subject
to regulatory approvals and the minimum tender condition.
"""
INDEX = name_index({"ENS": ACQUIRER, "ULBI": TARGET, "ELSE": EXTRA})


def filing(form="8-K", acc="0001193125-26-434415", *, cik="1289308", when="2026-10-27"):
    return {"form": form, "cik": cik, "filed": when, "accession": acc,
            "items": "1.01", "filename": f"edgar/data/{cik}/{acc.replace('-', '')}/primary.htm"}


class FakeSec:
    last_discovery_mode = "atom"
    def __init__(self, entries=None, bodies=None):
        self._entries = entries or [filing()]
        self._bodies = bodies or {"8-K": MERGER_8K, "SC TO-C": TENDER_COVER}
        self.calls = []
    def exchange_tickers(self):
        return [{"cik": x["cik"], "ticker": x["ticker"], "name": x["name"], "exchange": x["exchange"]}
                for x in (ACQUIRER, TARGET, EXTRA)]
    def recent_filings(self, days, forms):
        return self._entries
    def enrich_filing(self, cik, raw):
        return raw
    def submission_text(self, path):
        self.calls.append(path)
        form = "SC TO-C" if "435071" in path else "8-K"
        return self._bodies[form]


def test_big_acquirer_8k_detects_separate_small_target():
    out = discover(FakeSec(), filing(), INDEX, text=MERGER_8K)
    assert out.ticker == "ULBI" and out.cik == "875657"
    assert out.gate_status == out.bucket == "DATA_HOLD"
    assert out.discovery_status == "M&A_DISCOVERY_REVIEW_REQUIRED"
    assert out.event_status == "SIGNED"
    assert out.event_terms["cash_per_share_usd"] == 16.00
    assert out.event_terms["consideration_type"] == "CASH"
    assert out.event_terms["discovery_accession"] == "0001193125-26-434415"
    assert out.event_terms["counterparty_identification"] == "exact_unique_sec_exchange_issuer_name"
    assert out.event_sources == [
        "https://www.sec.gov/Archives/edgar/data/1289308/000119312526434415/primary.htm"]


@pytest.mark.parametrize("form", ["SC TO-C", "SC TO-T", "SC TO-T/A", "SC 14D9", "SC 14D9/A"])
def test_tender_schedule_links_target_without_acquirer_marketcap(form):
    assert form in TENDER_FORMS
    f = filing(form, "0001193125-26-435071")
    out = discover(FakeSec(), f, INDEX, text=TENDER_COVER)
    assert out.ticker == "ULBI"
    assert out.gate_status == "DATA_HOLD"
    assert out.event_terms["source_form"] == form
    assert out.event_terms["cash_per_share_usd"] == 16.00


def test_cash_stock_cvr_and_outcome_are_not_conflated():
    base = "The parties entered into a merger agreement to acquire Elsewhere Corporation. "
    cash = extract_terms(base + "Each common share receives $12.50 per share in cash.", "8-K")
    assert cash["consideration_type"] == "CASH"
    cvr = extract_terms(base + "Each common share receives $12.50 per share in cash. "
                        "A Contingent Value Right may be payable.", "8-K")
    assert cvr["consideration_type"] == "CASH" and cvr["cvr"] == "PRESENT_VALUE_UNVERIFIED"
    timing = extract_terms(base +
        "The acquisition is expected to close in the first quarter of calendar year 2027. "
        "The offer is not subject to a financing condition; convertible notes must be reconciled.", "8-K")
    assert timing["expected_closing"] == "Q1 2027"
    assert timing["financing_condition"] == "NONE_DISCLOSED"
    assert timing["preferred_convertibles_warrants"] == "MENTIONED_REQUIRES_REVIEW"
    stock = extract_terms(base + "Each common share receives $12.50 per share in cash; "
                          "a stock exchange ratio applies.", "8-K")
    assert stock["consideration_type"] == "CASH_AND_STOCK_UNVERIFIED"
    unverified = extract_terms("We expect to acquire Elsewhere Corporation by tender offer.", "8-K")
    assert unverified["deal_status"] == "ANNOUNCED"
    assert unverified["cash_per_share_usd"] is None
    terminated = extract_terms(base + "The merger agreement has been terminated.", "8-K")
    assert terminated["deal_status"] == "TERMINATED"
    completed = extract_terms(base + "The merger has been completed.", "8-K")
    assert completed["deal_status"] == "COMPLETED"


def test_incidental_company_mentions_and_ambiguous_names_do_not_create_target():
    text = "EnerSys will supply Ultralife Corporation batteries under an ordinary contract."
    assert discover(FakeSec(), filing(), INDEX, text=text) is None
    # Same legal stem at two different CIKs is unsafe.
    ambiguous = name_index({
        "A": {"ticker": "A", "name": "Ultralife Corp", "cik": "1", "exchange": "Nasdaq"},
        "B": {"ticker": "B", "name": "Ultralife Corporation", "cik": "2", "exchange": "NYSE"},
    })
    assert "ultralife" not in ambiguous
    assert discover(FakeSec(), filing(), ambiguous, text=MERGER_8K) is None


def test_pipeline_adds_one_discovery_row_and_same_run_report(tmp_path, monkeypatch):
    entries = [filing(), filing("SC TO-C", "0001193125-26-435071")]
    sec = FakeSec(entries)
    monkeypatch.setattr(pipeline, "SecClient", lambda: sec)
    monkeypatch.setattr(pipeline, "resolve_security", lambda s, m, f: {**m, "security_type": "COMMON_EQUITY"})
    monkeypatch.setattr(pipeline, "market_snapshots", lambda tickers: {})
    monkeypatch.setattr(pipeline, "build_candidate", lambda s, meta, f, overrides, cfg, snap=None:
        Candidate(ticker=meta["ticker"], name=meta["name"], cik=meta["cik"],
                  exchange=meta["exchange"], gate_status="REJECT", bucket="REJECT",
                  data_warnings=["Acquirer equity is outside expanded microcap universe."]))
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({
        "event_forms": ["8-K", "SC TO-C"],
        "material_8k_items": ["1.01", "2.01"],
        "exchanges": ["Nasdaq", "NYSE"],
        "ma_discovery_max_acquirer_8k_reads": 5,
        "max_candidates": 5,
    }))
    rows, cfg = pipeline.scan(7, str(cfg_path), str(tmp_path / "no_watch.csv"),
                              str(tmp_path / "no_override.json"))
    assert sum(c.ticker == "ULBI" for c in rows) == 1
    ulbi = next(c for c in rows if c.ticker == "ULBI")
    assert ulbi.gate_status == "DATA_HOLD"
    assert len(ulbi.event_sources) == 2
    assert cfg["_ma_discovery_count"] == 1
    assert cfg["_ma_acquirer_8k_reads"] == 1
    write_outputs(rows, cfg, tmp_path / "out")
    report = (tmp_path / "out/latest.md").read_text()
    quality = json.loads((tmp_path / "out/quality.json").read_text())
    csv_rows = list(csv.DictReader((tmp_path / "out/candidates.csv").open(encoding="utf-8-sig")))
    assert "**ULBI**" in report and "M&A DISCOVERY / REVIEW REQUIRED" in report
    assert quality["ma_discovery_count"] == 1
    assert quality["SAFE_TO_ACT"] is False and quality["pass_count"] == 0
    assert len([r for r in csv_rows if r["ticker"] == "ULBI"]) == 1
    assert next(r for r in csv_rows if r["ticker"] == "ULBI")["discovery_status"] == "M&A_DISCOVERY_REVIEW_REQUIRED"


def test_acquirer_read_budget_is_reported_not_silently_certified(tmp_path, monkeypatch):
    sec = FakeSec()
    monkeypatch.setattr(pipeline, "SecClient", lambda: sec)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"event_forms":["8-K"], "exchanges":["NYSE"],
                               "material_8k_items":["1.01"],
                               "max_candidates":5,"ma_discovery_max_acquirer_8k_reads":0}))
    monkeypatch.setattr(pipeline, "resolve_security", lambda s, m, f: {**m, "security_type": "COMMON_EQUITY"})
    monkeypatch.setattr(pipeline, "market_snapshots", lambda tickers: {})
    monkeypatch.setattr(pipeline, "build_candidate",
                        lambda s, m, f, o, c, snap=None: Candidate(ticker=m["ticker"],gate_status="REJECT",bucket="REJECT"))
    rows, state = pipeline.scan(7, str(cfg), str(tmp_path / "no_watch.csv"), str(tmp_path / "no_override.json"))
    assert not any(c.ticker == "ULBI" for c in rows)
    assert state["_ma_8k_budget_exceeded_count"] == 1
    assert state["_ma_discovery_partial"] is True


def test_discovery_does_not_modify_fd_and_incremental_baseline():
    target = discover(FakeSec(), filing(), INDEX, text=MERGER_8K)
    assert target.dilution.confidence == "low"
    assert target.dilution.strict_fd_shares == 0
    assert target.strict_fd_market_cap() is None
    # Existing checkpoint schema stays unchanged, including 7-day full anchor.
    code = Path(pipeline.__file__).read_text()
    assert 'prior_full_days < 7' in code
    assert '"INCREMENTAL_DELTA"' in code
