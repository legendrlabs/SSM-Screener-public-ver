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

def test_accept_prior_filing_date(monkeypatch):
    client = client_with_response(monkeypatch, HEADER + "\n" + ROW.replace("2026-10-20", "2026-10-19"))
    assert client.daily_master_index(DAY)[0]["filed"] == "2026-10-19"

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

def test_prior_day_filing_in_later_dissemination_index(monkeypatch):
    body = HEADER + "\n" + ROW.replace("2026-10-20", "2026-10-19") + "\n"
    client = client_with_response(monkeypatch, body)
    rows = client.daily_master_index(DAY)
    assert len(rows) == 1
    assert rows[0]["filed"] == "2026-10-19"

def test_future_filing_date_rejected(monkeypatch):
    body = HEADER + "\n" + ROW.replace("2026-10-20", "2026-10-21") + "\n"
    client = client_with_response(monkeypatch, body)
    with pytest.raises(RuntimeError, match="inconsistent"):
        client.daily_master_index(DAY)

# SEC federal closures are not identical to exchange holidays. Only a 404
# for a verified federal holiday/weekend can be treated as an absent index.
import requests
from ssm.providers.sec import _us_federal_holiday


def _client_raising_http(monkeypatch, status):
    client = object.__new__(SecClient)
    response = requests.Response()
    response.status_code = status

    def fail(_url):
        raise requests.HTTPError(f"HTTP {status}", response=response)

    monkeypatch.setattr(client, "_get", fail)
    return client


@pytest.mark.parametrize("day", [
    dt.date(2026, 1, 1),   # New Year's Day
    dt.date(2026, 1, 19),  # MLK Day
    dt.date(2026, 5, 25),  # Memorial Day
    dt.date(2026, 6, 19),  # Juneteenth
    dt.date(2026, 7, 3),   # Independence Day observed
    dt.date(2026, 9, 7),   # Labor Day
    dt.date(2026, 10, 12), # Columbus Day
    dt.date(2026, 11, 11), # Veterans Day
    dt.date(2026, 11, 26), # Thanksgiving
    dt.date(2026, 12, 25), # Christmas
    dt.date(2027, 12, 31), # New Year's 2028 observed in previous year
])
def test_federal_holiday_404_can_be_skipped(monkeypatch, day):
    assert _us_federal_holiday(day)
    assert _client_raising_http(monkeypatch, 404).daily_master_index(day) == []


def test_weekend_404_can_be_skipped(monkeypatch):
    assert _client_raising_http(monkeypatch, 404).daily_master_index(dt.date(2026, 10, 18)) == []


@pytest.mark.parametrize("day", [
    dt.date(2026, 10, 21), # ordinary Wednesday
    dt.date(2026, 4, 3),   # Good Friday: exchange holiday != federal holiday
])
def test_non_federal_weekday_404_is_data_hold(monkeypatch, day):
    assert not _us_federal_holiday(day)
    with pytest.raises(RuntimeError, match="lookback completeness unverified"):
        _client_raising_http(monkeypatch, 404).daily_master_index(day)


@pytest.mark.parametrize("day", [
    dt.date(2026, 10, 18), # Sunday
    dt.date(2026, 11, 26), # Thanksgiving
    dt.date(2026, 10, 21), # ordinary weekday
])
def test_http_403_never_silently_skipped(monkeypatch, day):
    with pytest.raises(requests.HTTPError):
        _client_raising_http(monkeypatch, 403).daily_master_index(day)
