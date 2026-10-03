from ssm.events import select_event, event_terms, event_status
from ssm.event_rules import classify_event


AGREEMENT = (
    'On September 1, 2026, Elm Inc. entered into an Agreement and Plan of Merger '
    'with Cedar Group, Inc. ("Parent") and Cedar Merger Sub, Inc. '
    'Each share of Common Stock will be converted into the right to receive '
    '$33.00 per share in cash and 0.4735 shares of Parent Common Stock.'
)


def record(text, filed, accession):
    kind, proof, summary = classify_event(text)
    return dict(
        text=text,
        combined_text=text,
        narrative=text,
        filed=filed,
        accession=accession,
        form='8-K',
        sources=['https://example.test/' + accession],
        summary=summary,
        event_type=kind,
        event_proof=proof,
        event_status=event_status(text, kind, proof),
        terms=event_terms(text, kind),
    )


def test_amendment_that_explicitly_leaves_merger_consideration_unchanged_preserves_terms():
    update = (
        'Pursuant to the September 1, 2026 Agreement and Plan of Merger with '
        'Cedar Group, Inc. and Cedar Merger Sub, Inc., the parties entered into '
        'an amendment to the Merger Agreement. The amendment did not modify the '
        'merger consideration, which remains unchanged.'
    )
    selected = select_event([
        record(AGREEMENT, '2026-09-01', 'old'),
        record(update, '2026-09-20', 'amend'),
    ])

    assert selected['terms']['cash_per_share_usd'] == 33
    assert selected['terms']['stock_exchange_ratio'] == 0.4735
    assert not selected['terms'].get('economics_reconciliation_required')
