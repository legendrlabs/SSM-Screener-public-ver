import datetime as dt
from types import SimpleNamespace
from ssm.providers.sec import SecClient

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>8-K - Example Corp (0001234567)</title>
    <updated>{today}T12:34:56-04:00</updated>
    <summary type="html">Filed: {today} AccNo: 0000123456-26-123456</summary>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1234567/000012345626123456/0000123456-26-123456-index.htm" />
  </entry>
</feed>
"""

class FakeResponse:
    def __init__(self, text):
        self.text = text

def test_atom_recent_filings_parses_cik_accession_and_date():
    today = dt.date.today().isoformat()
    sec = SecClient(user_agent="SSM-Test test@example.com", pause=0)
    sec._get = lambda url: FakeResponse(ATOM.format(today=today))
    rows = sec.atom_recent_filings(days=1, forms=["8-K"], count=100, max_pages_per_form=1)
    assert len(rows) == 1
    row = rows[0]
    assert row["cik"] == "1234567"
    assert row["accession"] == "0000123456-26-123456"
    assert row["filed"] == today
    assert row["source"] == "atom"
