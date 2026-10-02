from datetime import date
import json

from ssm.pipeline import build_candidate


class CoverOnlySec:
    def __init__(self, event, financial_extra=''):
        self.event = event
        self.financial_extra = financial_extra

    def latest_financial_record(self, cik):
        return {'filename': 'financial', 'filed': date.today().isoformat(), 'form': '10-Q'}

    def companyfacts(self, cik):
        return {}

    def submissions(self, cik):
        return {'filings': {'recent': {}}}

    def submission_text(self, filename):
        if filename == 'event':
            return self.event
        return ('As of August 10, 2026, there were 10,000,000 shares of common stock outstanding. '
                'PART I. Financial statements. Preferred stock, none issued. ' + self.financial_extra)

    def relevant_exhibit_texts(self, *args, **kwargs):
        return []


def build(event, financial_extra='', override=None):
    return build_candidate(CoverOnlySec(event, financial_extra),
                           {'ticker': 'COVER', 'name': 'Cover', 'exchange': 'Nasdaq', 'cik': '1', 'security_type': 'COMMON_EQUITY'},
                           {'filename': 'event', 'filed': date.today().isoformat(), 'form': '8-K', 'items': '2.01', 'accession': '1'},
                           {'COVER': override} if override else {}, json.load(open('config/default.json')),
                           {'price': 5, 'adv20_usd': 1_000_000})


def test_cover_resolution_clears_only_missing_common_confidence():
    c = build('The Company completed the asset acquisition.')
    assert c.dilution.common_shares == 10_000_000
    assert c.dilution.confidence == 'medium'
    assert c.gate_status == 'PASS'


def test_cover_cannot_clear_unresolved_instruments_or_missing_event():
    for event, extra in (
        ('Warrants remain outstanding; quantities are unspecified.', ''),
        ('Customer agreement.', 'Series B preferred stock: 79,246 shares outstanding.'),
        ('', ''),
        ('The Company completed the merger. The merger consideration includes 30,000,000 newly issued shares of common stock and an earnout payable in 10,000,000 shares.', ''),
        ('The Company entered into a merger agreement. At closing, 30,000,000 shares of common stock will be issued to the target shareholders.', ''),
        ('The Company completed the merger. The Company will issue 30,000,000 shares of common stock to the target shareholders.', ''),
        ('The Company entered into a merger agreement. Consideration terms are provided in Exhibit 2.1.', ''),
        ('The Company signed a definitive business combination agreement providing for 30,000,000 shares of common stock.', ''),
    ):
        c = build(event, extra)
        assert c.dilution.confidence == 'low'
        assert c.gate_status == 'DATA_HOLD'
        assert c.dilution.fd_ratio is None


def test_cover_does_not_override_explicit_low_confidence():
    assert build('Customer agreement.', override={'confidence': 'low'}).dilution.confidence == 'low'
