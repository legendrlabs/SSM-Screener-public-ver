from ssm.dilution import heuristic_extract_dilution

def test_prefunded_quantity_is_parsed():
    d, _ = heuristic_extract_dilution(
        "Pre-funded warrants exercisable for 4,000,000 shares of common stock.",
        10_000_000,
    )
    assert d.pre_funded_shares == 4_000_000

def test_malformed_quantity_does_not_raise():
    d, warnings = heuristic_extract_dilution(
        "Warrants to purchase , shares of common stock.",
        10_000_000,
    )
    assert d.warrants_itm_shares == 0
    assert warnings


def test_prefunded_count_each_one_share():
    text="9,972,424 pre-funded warrants were issued, each exercisable for one share of common stock."
    d,_=heuristic_extract_dilution(text,11_591_124)
    assert d.pre_funded_shares==9_972_424

def test_warrant_aggregate_underlying_shares():
    text="The new warrants are exercisable to purchase up to 8,148,000 shares of common stock."
    d,_=heuristic_extract_dilution(text,4_000_000)
    assert d.warrants_itm_shares==8_148_000


def test_prefunded_does_not_hide_common_warrants():
    d, _ = heuristic_extract_dilution(
        'Pre-funded warrants exercisable for 4,000,000 shares of common stock. '
        'Common warrants exercisable for 8,000,000 shares of common stock.', 10_000_000)
    assert d.pre_funded_shares == 4_000_000
    assert d.warrants_itm_shares == 8_000_000


def test_equal_sized_distinct_warrants_are_preserved():
    d, _ = heuristic_extract_dilution(
        'Pre-funded warrants exercisable for 4,000,000 shares of common stock. '
        'Common warrants exercisable for 4,000,000 shares of common stock.', 10_000_000)
    assert d.near_fd_shares == 18_000_000


def test_one_quantity_cannot_clear_other_unresolved_instrument():
    d, warnings = heuristic_extract_dilution(
        'Warrants exercisable for 2,000,000 shares of common stock. '
        'Convertible notes are outstanding; their conversion terms are in Note 8.', 10_000_000)
    assert d.confidence == 'low'
    assert warnings


def test_same_sentence_distinct_warrants_are_preserved():
    d, _ = heuristic_extract_dilution(
        'Pre-funded warrants exercisable for 4,000,000 shares of common stock '
        'and common warrants exercisable for 8,000,000 shares of common stock.', 10_000_000)
    assert d.near_fd_shares == 22_000_000


def test_same_sentence_unresolved_common_warrants_hold():
    d, warnings = heuristic_extract_dilution(
        'Pre-funded warrants exercisable for 4,000,000 shares of common stock '
        'and common warrants with quantities specified elsewhere.', 10_000_000)
    assert d.confidence == 'low'
    assert warnings


def test_agpu_outstanding_prefunded_count_precedes_historical_issuance():
    d, _ = heuristic_extract_dilution(
        'The Company sold 4,366,703 shares or pre-funded warrants in the Cash PIPE. '
        'The total number of pre-funded warrants outstanding was 9,972,424 as of June 30, 2026.',
        11_591_124)
    assert d.pre_funded_shares == 9_972_424
