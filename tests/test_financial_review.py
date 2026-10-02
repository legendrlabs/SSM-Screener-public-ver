from ssm.models import Dilution
from ssm.financial_review import financial_note_hits, conservative_merge_dilution, cover_page_common_shares, extract_atm_remaining_usd

def test_financial_note_hits():
    text = """
    Note 7 Warrants and Pre-Funded Warrants.
    The Company evaluated substantial doubt about its ability to continue as a going concern.
    Subsequent Events include an at-the-market offering.
    """
    hits = set(financial_note_hits(text))
    assert {"WARRANTS","PRE_FUNDED","GOING_CONCERN","SUBSEQUENT_EVENTS","ATM_EQUITY_LINE"} <= hits

def test_conservative_merge_uses_max_not_sum():
    event = Dilution(
        common_shares=10_000_000,
        pre_funded_shares=4_000_000,
        warrants_itm_shares=2_000_000,
        source="8-K",
        confidence="medium",
    )
    fin = Dilution(
        common_shares=10_000_000,
        pre_funded_shares=4_000_000,
        warrants_itm_shares=3_000_000,
        converts_shares=1_000_000,
        source="10-Q",
        confidence="medium",
    )
    merged = conservative_merge_dilution(event, fin)
    assert merged.pre_funded_shares == 4_000_000
    assert merged.warrants_itm_shares == 3_000_000
    assert merged.converts_shares == 1_000_000
    assert merged.strict_fd_shares == 18_000_000


def test_clean_exhibit_cannot_clear_unresolved_filing():
    from ssm.dilution import heuristic_extract_dilution
    from ssm.gates import evaluate_gates
    from ssm.models import Candidate
    from datetime import date
    import json
    unresolved, _ = heuristic_extract_dilution('Warrants remain outstanding; quantities are in an exhibit.', 10_000_000)
    clean, _ = heuristic_extract_dilution('The company entered a customer agreement.', 10_000_000)
    merged = conservative_merge_dilution(unresolved, clean)
    assert merged.confidence == 'low'
    c = Candidate(ticker='UNRESOLVED', exchange='Nasdaq', price=5, adv20_usd=1_000_000,
                  dilution=merged, financial_review_complete=True, event_proof=3,
                  latest_event_date=date.today().isoformat(), latest_financial_filing_date=date.today().isoformat())
    cfg = json.load(open('config/default.json'))
    assert evaluate_gates(c, cfg)[0] == 'DATA_HOLD'


def test_cover_page_common_shares_generic():
    text="As of August 10, 2026, there were 12,345,678 shares of common stock outstanding."
    assert cover_page_common_shares(text)==12_345_678

def test_cover_page_common_shares_sums_classes():
    text="As of August 10, 2026, 10,000,000 shares of Class A common stock and 2,000,000 shares of Class B common stock were outstanding."
    assert cover_page_common_shares(text)==12_000_000


def test_extract_atm_remaining_usd():
    text="Approximately $50.0 million remained available under the at-the-market sales agreement."
    assert extract_atm_remaining_usd(text)==50_000_000


def test_cover_parser_ignores_note_section():
    text=(
        "FORM 10-Q As of August 10, 2026, there were 20,000,000 shares of common stock outstanding. "
        "PART I Item 1. Financial Statements. "
        "A later note says 1,100,000 shares of common stock outstanding under an award plan."
    )
    assert cover_page_common_shares(text)==20_000_000


def test_gpro_combined_class_counts_ignore_hidden_inline_header():
    # Visible wording and quantities from GPRO 2026 Q2 10-Q cover.
    text = ('<ix:header><ix:hidden>1,129,944 shares of common stock outstanding'
            '</ix:hidden></ix:header><p>As of August&nbsp;7, 2026, '
            '<ix:nonFraction>158,245,863</ix:nonFraction> and '
            '<ix:nonFraction>26,258,546</ix:nonFraction> shares of Class A '
            'and Class B common stock were outstanding, respectively.</p>'
            '<p>PART I. FINANCIAL INFORMATION</p>'
            '<p>500,000,000 shares of common stock outstanding</p>')
    assert cover_page_common_shares(text) == 184_504_409


def test_authorized_share_capacity_is_not_outstanding_shares():
    text = ('FORM 10-Q Common stock, 248,500,000 shares authorized, '
            'with 4,966,818 issued and outstanding. PART I. FINANCIAL INFORMATION')
    assert cover_page_common_shares(text) == 0


def test_nested_inline_header_is_removed_completely():
    from ssm.financial_review import visible_filing_text
    text = ('<ix:header><ix:hidden>hidden fact</ix:hidden>'
            '<ix:resources>hidden contexts</ix:resources></ix:header>'
            '<p>visible cover</p>')
    assert visible_filing_text(text) == 'visible cover'
