from ssm.providers.sec import SecClient

def test_latest_financial_record_builds_primary_document_path():
    sec = SecClient(user_agent="SSM-Test test@example.com", pause=0)
    sec.submissions = lambda cik: {
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q"],
                "filingDate": ["2026-10-01", "2026-08-10"],
                "accessionNumber": ["0000000000-26-000001", "0000000000-26-000002"],
                "primaryDocument": ["event.htm", "quarter.htm"],
                "primaryDocDescription": ["Current report", "Quarterly report"],
            }
        }
    }
    rec = sec.latest_financial_record("1234567")
    assert rec["form"] == "10-Q"
    assert rec["filed"] == "2026-08-10"
    assert rec["accession"] == "0000000000-26-000002"
    assert rec["filename"] == "edgar/data/1234567/000000000026000002/quarter.htm"
