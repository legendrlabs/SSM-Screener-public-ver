import pytest

from ssm.event_rules import classify_event
from ssm.events import event_status, event_terms


@pytest.mark.parametrize('text', [
    'In the event of liquidation, dissolution or winding up of the Company, the holders of the Preferred Stock will be entitled to a minimum preferential payment of $1,000.00 per share.',
    'The Series F Preferred Stock established by the certificate ranks senior to Common Stock with respect to distributions and payments upon liquidation, dissolution and winding up of the Company.',
    'Upon any liquidation, dissolution or winding up of the Company, holders of preferred stock are entitled to the redemption price before any distribution to junior stock.',
    'The Board approved a preferred stock designation with a liquidation preference. The preferred holders rank senior upon winding up.',
    'The Board approved a supply contract providing for liquidated damages.',
    'The Board approved a merger agreement. Upon closing, the merger subsidiary will be dissolved.',
])
def test_security_preferences_and_contract_terms_are_not_issuer_liquidation(text):
    kind, proof, _ = classify_event(text)
    assert kind != 'LIQUIDATION_DISTRIBUTION'
    assert event_status(text, kind, proof) != 'LIQUIDATING'
    assert 'distribution_per_share_usd' not in event_terms(text, kind)


@pytest.mark.parametrize('text', [
    'The Board approved a plan of sale and liquidation of the Company.',
    'The Company adopted a liquidation plan.',
    'The Company provided an update on its ongoing liquidation activities.',
    'The Company has commenced the voluntary liquidation process.',
    'The Board has declared an additional special liquidating distribution of $1.74 per common share.',
])
def test_operative_company_liquidation_evidence_remains_a_liquidating_event(text):
    kind, proof, _ = classify_event(text)
    assert kind == 'LIQUIDATION_DISTRIBUTION'
    assert event_status(text, kind, proof) == 'LIQUIDATING'


def test_adopted_rights_plan_is_not_a_hypothetical_merger_or_liquidation():
    text = ('The Board adopted a stockholder protection rights plan and declared a dividend of one right per common share. '
            'In the event of liquidation, dissolution or winding up of the Company, the holders of Preferred Stock receive a preferential payment. '
            'If the Company is acquired in a merger or business combination, rights have a flip-over adjustment. '
            'The Company has received preliminary acquisition interest.')
    kind, proof, _ = classify_event(text)
    assert kind == 'LISTING_CAPITAL_STRUCTURE'
    assert proof == 2
    assert event_status(text, kind, proof) == 'ADOPTED'
    assert event_terms(text, kind)['capital_structure_action'] == 'RIGHTS_PLAN'


def test_true_distribution_amount_cannot_come_from_par_value_or_preferred_priority():
    text = ('Common Stock has $0.0001 per share par value. '
            'The Board declared a special liquidating distribution of $1.74 per common share. '
            'In the event of dissolution, preferred holders are entitled to $1,000 per share.')
    terms = event_terms(text, 'LIQUIDATION_DISTRIBUTION')
    assert terms['distribution_per_share_usd'] == 1.74
    assert terms['distribution_status'] == 'DECLARED'
    assert 'dissolution_status' not in terms


def test_hypothetical_plan_adoption_cannot_create_an_active_liquidation():
    text = 'The Board may adopt a plan of sale and liquidation if the business combination is not completed.'
    assert classify_event(text)[0] != 'LIQUIDATION_DISTRIBUTION'


def test_closed_preferred_financing_is_not_an_asset_sale_or_preliminary_forecast():
    text = ('The Company entered into a securities purchase agreement with investors to issue and sell preferred stock and warrants. '
            'The Financing closed on August 5, 2026 and raised $1.65 billion. '
            'The certificates provide for distributions upon liquidation, dissolution and winding up. '
            'Preliminary quarterly results were reported. Covenants restrict asset acquisitions and sales.')
    kind, proof, _ = classify_event(text)
    assert kind == 'STRATEGIC_INVESTMENT_PIPE'
    assert proof == 3
    assert event_status(text, kind, proof) == 'COMPLETED'


@pytest.mark.parametrize('text', [
    'If the Board adopted a stockholder protection rights plan, the rights would become exercisable.',
    'The Board never approved a plan of liquidation.',
])
def test_conditional_or_denied_actions_are_not_completed_current_events(text):
    kind, proof, _ = classify_event(text)
    assert event_status(text, kind, proof) not in {'ADOPTED', 'LIQUIDATING'}


def test_preferred_distribution_cannot_override_common_holder_entitlement():
    text = 'The Board declared a liquidating distribution to preferred holders of $10 per share and to common holders of $1.74 per common share.'
    terms = event_terms(text, 'LIQUIDATION_DISTRIBUTION')
    assert terms['distribution_per_share_usd'] == 1.74
    assert terms['distribution_status'] == 'DECLARED'


def test_plan_approval_is_not_a_distribution_declaration():
    text = 'The Board approved a plan of liquidation contemplating a liquidating distribution of $2 per common share, subject to stockholder approval.'
    terms = event_terms(text, 'LIQUIDATION_DISTRIBUTION')
    assert 'distribution_per_share_usd' not in terms
    assert terms.get('distribution_status') != 'DECLARED'


@pytest.mark.parametrize('common_payout, expected', [
    (' and to common holders of $1.74 per common share', 1.74),
    ('', None),
])
def test_same_clause_common_par_value_is_not_a_distribution(common_payout, expected):
    text = ('Common Stock has $0.0001 per common share par value, and the Board declared a liquidating distribution '
            'to preferred holders of $10 per share' + common_payout + '.')
    terms = event_terms(text, 'LIQUIDATION_DISTRIBUTION')
    assert terms.get('distribution_per_share_usd') == expected


def test_completed_rights_backstop_debt_exchange_is_not_an_asset_acquisition():
    text = ('The Company completed its previously announced subscription rights offering and closed the Backstop Exchange. '
            'The Backstop Parties committed to exchange their 2030 Notes for shares of Common Stock. '
            'The exchange of notes for Common Stock reduces outstanding debt. Shares will be issued to the Backstop Parties.')
    kind, proof, _ = classify_event(text)
    assert kind == 'DEBT_RESTRUCTURING'
    assert event_status(text, kind, proof) == 'COMPLETED'
    terms = event_terms(text, kind)
    assert terms['materiality'] == 'STRUCTURAL'
    assert terms['capital_structure_action'] == 'DEBT_EQUITY_EXCHANGE'


def test_resale_registration_is_not_new_asset_purchase_or_share_issuance():
    text = ('The Company registered for resale by selling stockholders preferred stock, warrants and common shares issuable upon exercise. '
            'The Securities were issued pursuant to the Securities Purchase Agreement dated August 5, 2026. '
            'A related prospectus supplement contains stockholders who acquired securities.')
    kind, proof, _ = classify_event(text)
    assert kind == 'LISTING_CAPITAL_STRUCTURE'
    assert event_status(text, kind, proof) == 'REGISTERED'
    assert event_terms(text, kind)['capital_structure_action'] == 'RESALE_REGISTRATION'


def test_completed_merger_registration_filing_does_not_mean_merger_closed():
    text = ('The Company entered into an amended note in connection with the Merger Agreement. '
            'The amended note represents the first tranche funded by the Company. '
            'The registration statement was submitted in connection with the transactions contemplated by '
            'the Merger Agreement, which filing was completed on the same date. '
            'The note contains events of default including bankruptcy, insolvency, liquidation or winding up events.')
    kind, proof, _ = classify_event(text)
    assert kind == 'MERGER_REVERSE_MERGER'
    assert proof == 2
    assert event_status(text, kind, proof) == 'SIGNED'


def test_actual_merger_completion_survives_completed_registration_sentence():
    text = ('The parties entered into a merger agreement. '
            'The filing of the registration statement was completed. '
            'The parties completed the merger on September 30, 2026.')
    kind, proof, _ = classify_event(text)
    assert kind == 'MERGER_REVERSE_MERGER'
    assert proof == 3
    assert event_status(text, kind, proof) == 'COMPLETED'


@pytest.mark.parametrize('pending', [
    'The merger is anticipated to be completed in the fourth quarter.',
    'The merger remains to be completed after shareholder approval.',
])
def test_funded_financing_cannot_complete_a_pending_merger(pending):
    text = 'The Company entered into a merger agreement. The first financing tranche was funded. ' + pending
    kind, proof, _ = classify_event(text)
    assert proof == 2
    assert event_status(text, kind, proof) == 'SIGNED'
