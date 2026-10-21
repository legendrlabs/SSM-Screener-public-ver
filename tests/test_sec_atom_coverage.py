"""SEC Atom discovery must not silently accept incomplete pagination."""
from datetime import date, timedelta
import xml.etree.ElementTree as ET

import pytest

from ssm.providers.sec import SecClient


def _feed(dates):
    entries = "".join(
        '<entry><title>Test (0001234567)</title>'
        '<link href="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/x.htm"/>'
        f'<updated>{day}T12:00:00Z</updated></entry>'
        for day in dates
    )
    return '<feed xmlns="http://www.w3.org/2005/Atom">' + entries + '</feed>'


def _client(monkeypatch, pages):
    client = object.__new__(SecClient)
    requests = []
    def get(url):
        requests.append(url)
        class Response:
            text = pages[min(len(requests) - 1, len(pages) - 1)]
        return Response()
    monkeypatch.setattr(client, "_get", get)
    return client, requests


def test_atom_rejects_malformed_xml(monkeypatch):
    client, _ = _client(monkeypatch, ["not xml"])
    with pytest.raises(RuntimeError, match="parsed"):
        client.atom_recent_filings(7, ["8-K"])


def test_atom_rejects_empty_first_page(monkeypatch):
    client, _ = _client(monkeypatch, [_feed([])])
    with pytest.raises(RuntimeError, match="no entries"):
        client.atom_recent_filings(7, ["8-K"])


def test_atom_rejects_short_page_without_cutoff_evidence(monkeypatch):
    today = date.today().isoformat()
    client, _ = _client(monkeypatch, [_feed([today])])
    with pytest.raises(RuntimeError, match="coverage"):
        client.atom_recent_filings(7, ["8-K"], count=100)


def test_atom_accepts_page_with_older_cutoff_evidence(monkeypatch):
    today = date.today()
    client, requests = _client(monkeypatch, [_feed([
        today.isoformat(), (today - timedelta(days=9)).isoformat()
    ])])
    rows = client.atom_recent_filings(7, ["8-K"], count=100)
    assert len(rows) == 1
    assert len(requests) == 1


def test_atom_rejects_unverified_page_limit(monkeypatch):
    today = date.today().isoformat()
    client, _ = _client(monkeypatch, [_feed([today])])
    with pytest.raises(RuntimeError, match="coverage|pagination"):
        client.atom_recent_filings(7, ["8-K"], count=1, max_pages_per_form=1)
