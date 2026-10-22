"""Daily SEC index format and fail-closed regression tests."""
import datetime as dt
from types import SimpleNamespace
import pytest
from ssm.providers.sec import SecClient

DAY = dt.date(2026, 10, 20)
HEADER = "CIK|Company Name|Form Type|Date Filed|Filename"
ROW = "1234567|Test Inc|8-K|2026-10-20|edgar/data/1234567/000000.txt"

def client_with_response(monkeypatch, body, status=200, content_type="application/octet-stream"):
    client = object.__new__(SecClient)
    response = SimpleNamespace(
        text=body, content=body.encode("utf-8"),
        status_code=status, headers={"Content-Type": content_type},
    )
    monkeypatch.setattr(client, "_get", lambda url: response)
    return client

def test_valid_index(monkeypatch):
    client = client_with_response(monkeypatch, "Description: Master Index\n" + HEADER + "\n-----\n" + ROW + "\n")
    rows = client.daily_master_index(DAY)
    assert len(rows) == 1
    assert rows[0]["source"] == "daily-index"

def test_bom_spaces_case(monkeypatch):
    header = "\ufeff cik | Company Name | FORM TYPE | Date Filed | Filename "
    client = client_with_response(monkeypatch, header + "\n" + ROW + "\n")
    assert len(client.daily_master_index(DAY)) == 1

@pytest.mark.parametrize("body", ["<html>blocked</html>", '{"error":"bad"}', "", "garbage"])
def test_reject_unrecognized_body(monkeypatch, body):
    client = client_with_response(monkeypatch, body)
    with pytest.raises(RuntimeError, match="missing expected header"):
        client.daily_master_index(DAY)

def test_reject_invalid_date(monkeypatch):
    client = client_with_response(monkeypatch, HEADER + "\n" + ROW.replace("2026-10-20", "2026-10-19"))
    with pytest.raises(RuntimeError, match="inconsistent"):
        client.daily_master_index(DAY)

def test_reject_truncated_row(monkeypatch):
    client = client_with_response(monkeypatch, HEADER + "\n1234567|Test")
    with pytest.raises(RuntimeError, match="malformed"):
        client.daily_master_index(DAY)

@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-8-sig"])
def test_index_byte_decoding(monkeypatch, encoding):
    body = HEADER + "\n" + ROW + "\n"
    raw = body.encode(encoding)
    client = object.__new__(SecClient)
    response = SimpleNamespace(
        content=raw, text=raw.decode("latin-1"),
        status_code=200, headers={"Content-Type": "application/octet-stream"},
    )
    monkeypatch.setattr(client, "_get", lambda url: response)
    assert len(client.daily_master_index(DAY)) == 1

def test_real_sec_daily_index_format(monkeypatch):
    """Observed SEC 2026-10-21 format uses File Name and YYYYMMDD."""
    day = dt.date(2026, 10, 21)
    header = "CIK|Company Name|Form Type|Date Filed|File Name"
    row = "1000209|MEDALLION FINANCIAL CORP|8-K|20261021|edgar/data/1000209/0001193125-26-427818.txt"
    client = client_with_response(monkeypatch, "Description: Daily Index of EDGAR Dissemination Feed\n" + header + "\n" + "-" * 80 + "\n" + row + "\n")
    filings = client.daily_master_index(day)
    assert len(filings) == 1
    assert filings[0]["filed"] == "2026-10-21"
    assert filings[0]["filename"].endswith("0001193125-26-427818.txt")
