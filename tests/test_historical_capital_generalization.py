from ssm.financial_recapitalization import financial_capital_contexts


RECORD = {
    'form': '10-Q',
    'filed': '2026-08-10',
    'report_date': '2026-06-30',
    'accession': 'q',
    'filename': 'q',
}


def test_old_common_issuance_is_historical_without_current_fd_impact():
    rows = financial_capital_contexts(
        'On March 1, 2026, the Company issued 2 million shares of common stock in a PIPE.',
        RECORD,
    )
    context = rows[0]['context']
    assert context['classification'] == 'HISTORICAL_INCLUDED'
    assert context['current_fd_impact'] == 'NONE'
    assert context['common_count_reconciliation'] == 'ALREADY_INCLUDED_OR_HISTORICAL'
    assert context['reconciliation_required'] is False
    assert context['actual_common_issued'] == 2e6
    assert context['read_only'] is True


def test_issuance_after_current_share_baseline_requires_reconciliation():
    text = (
        'As of July 15, 2026, there were 10,000,000 shares of common stock outstanding. PART I. '
        'On August 1, 2026, the Company issued 2 million shares of common stock in a PIPE.'
    )
    context = financial_capital_contexts(text, RECORD)[0]['context']
    assert context['classification'] == 'CURRENT_RECONCILIATION_REQUIRED'
    assert context['current_fd_impact'] == 'UNRESOLVED'
    assert context['reconciliation_required'] is True


def test_past_fully_retired_exchange_has_no_current_incremental_shares():
    text = (
        'On March 1, 2026, the Company exchanged all outstanding Series D Preferred Stock '
        'for 2 million newly issued shares of common stock.'
    )
    context = financial_capital_contexts(text, RECORD)[0]['context']
    assert context['actual_common_issued'] == 2e6
    assert context['classification'] == 'HISTORICAL_INCLUDED'
    assert context['current_fd_impact'] == 'NONE'
    assert context['reconciliation_required'] is False


def test_distinct_same_day_same_size_placements_keep_separate_stable_ids():
    text = (
        'On March 1, 2026, the Company issued 2 million shares of common stock to Alpha LLC in a private placement. '
        'On March 1, 2026, the Company issued 2 million shares of common stock to Beta LLC in a separate private placement.'
    )
    first = financial_capital_contexts(text, RECORD)
    second = financial_capital_contexts(text, RECORD | {'accession': 'other', 'filename': 'other'})
    assert len(first) == 2
    assert len({row['capital_event_id'] for row in first}) == 2
    assert [row['capital_event_id'] for row in first] == [row['capital_event_id'] for row in second]
