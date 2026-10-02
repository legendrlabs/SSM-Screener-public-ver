from ssm.dilution import heuristic_extract_dilution


def test_unissued_preferred_capacity_is_not_live_dilution():
    for text in (
        'Preferred stock, $0.0001 par value, 5,000 shares authorized; none issued — — Common stock.',
        'Preferred stock (200,000,000 shares authorized, none issued and outstanding as of June 30, 2026).',
        'Preferred stock, 20,000,000 shares authorized, none outstanding.',
    ):
        d, warnings = heuristic_extract_dilution(text, 10_000_000)
        assert d.confidence == 'medium'
        assert warnings == []


def test_zero_class_does_not_clear_another_class_or_later_issuance():
    for text in (
        'Series A preferred stock, none outstanding. Series B preferred stock, 79,246 shares outstanding.',
        'Preferred stock, none outstanding as of June 30, 2026. On July 1, the Company issued preferred stock.',
        'Preferred stock: 100 shares outstanding; none issued during the quarter.',
        'ASU 2026-01 applies to 100 preferred shares outstanding.',
        'Preferred stock: none issued during the quarter; dividends were paid on Series A.',
        'Preferred stock, none outstanding at June 30, 2026; 1,000 shares were issued on July 1, 2026.',
        'ASU 2026-01 applies to our Series A preferred stock, 100 shares issued on July 1, 2026.',
    ):
        d, warnings = heuristic_extract_dilution(text, 10_000_000)
        assert d.confidence == 'low'
        assert 'Unresolved share quantity for preferred shares.' in warnings


def test_accounting_standard_and_future_shelf_are_not_current_preferred():
    text = ('The FASB issued ASU 2026-01, Equity (Topic 505): Paid-in-Kind Dividends on Equity-Classified Preferred Stock. '
            'ASU 2026-01 requires preferred stock dividends to be measured using the preferred stock agreement. '
            'We may, from time to time, sell common stock, preferred stock under a shelf registration statement. '
            'Authorize the issuance of blank check preferred stock that our board could use in a poison pill.')
    d, warnings = heuristic_extract_dilution(text, 10_000_000)
    assert d.confidence == 'medium'
    assert warnings == []
    d, warnings = heuristic_extract_dilution(text + ' Our preferred stock remains outstanding.', 10_000_000)
    assert d.confidence == 'low'
    assert warnings


def warrant_table(total='4,475,130', second_column=''):
    return ('<p>The Company has 4,475,130 warrants outstanding and exercisable as of June 30, 2026, as summarized below.</p>'
            '<table><tr><td>As of June 30,</td></tr><tr><td>Issue Date</td><td>2026</td></tr>'
            '<tr><td>April 25, 2019 at an exercise price of $20.00</td><td>85,830</td></tr>'
            '<tr><td>June 1, 2026 Pre-Funded Warrants at an exercise price of $0.0001</td><td>2,005,900</td>' + second_column + '</tr>'
            '<tr><td>June 1, 2026 Common Warrants at an exercise price of $0.21</td><td>2,383,400</td></tr>'
            '<tr><td></td><td>' + total + '</td></tr></table>')


def test_reconciled_table_reports_units_without_inventing_share_equivalents():
    text = ('177,500 shares were sold alongside pre-funded warrants. ' + warrant_table())
    d, warnings = heuristic_extract_dilution(text, 1_861_303)
    assert d.pre_funded_warrants_outstanding == 2_005_900
    assert d.ordinary_warrants_outstanding == 2_469_230
    assert d.warrant_units_as_of == '2026-06-30'
    assert d.pre_funded_shares == 0
    assert d.confidence == 'low'
    assert d.fd_ratio is None
    assert any('units' in warning for warning in warnings)


def test_unreconciled_or_multicolumn_table_is_not_accepted():
    for text in (warrant_table(total='4,000,000'), warrant_table(second_column='<td>1,000</td>'),
                 warrant_table().replace('<td>As of June 30,</td>', '<td>As of March 31,</td>')):
        d, _ = heuristic_extract_dilution(text, 1_861_303)
        assert d.pre_funded_warrants_outstanding is None


def test_latest_dated_unit_evidence_survives_merge():
    from ssm.financial_review import conservative_merge_dilution
    from ssm.models import Dilution
    older = Dilution(pre_funded_warrants_outstanding=4_000_000,
                     ordinary_warrants_outstanding=5_000_000, warrant_units_as_of='2026-03-31')
    newer, _ = heuristic_extract_dilution(warrant_table(), 1_861_303)
    for a, b in ((older, newer), (newer, older)):
        merged = conservative_merge_dilution(a, b)
        assert merged.pre_funded_warrants_outstanding == 2_005_900
        assert merged.warrant_units_as_of == '2026-06-30'
        assert merged.confidence == 'low'


def test_unit_counts_are_visible_in_report_but_fd_remains_blank(tmp_path):
    import csv
    from ssm.models import Candidate
    from ssm.report import write_outputs
    d, _ = heuristic_extract_dilution(warrant_table(), 1_861_303)
    write_outputs([Candidate(ticker='GIPR', dilution=d)], {'max_candidates': 5}, tmp_path)
    with (tmp_path / 'dilution_check.csv').open(encoding='utf-8-sig') as f:
        row = next(csv.DictReader(f))
    assert row['pre_funded_warrants_outstanding'] == '2005900'
    assert row['ordinary_warrants_outstanding'] == '2469230'
    assert row['warrant_units_as_of'] == '2026-06-30'
    assert row['near_fd_shares'] == row['strict_fd_shares'] == row['fd_ratio'] == ''
