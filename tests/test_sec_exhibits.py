from ssm.providers.sec import SecClient

INDEX_HTML = """
<html><body><table>
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
<tr><td>1</td><td>Current Report</td><td><a href="event.htm">event.htm</a></td><td>8-K</td></tr>
<tr><td>2</td><td>Warrant Agreement</td><td><a href="ex4-1.htm">ex4-1.htm</a></td><td>EX-4.1</td></tr>
<tr><td>3</td><td>Securities Purchase Agreement</td><td><a href="/Archives/edgar/data/1234567/ex10-1.htm">ex10-1.htm</a></td><td>EX-10.1</td></tr>
<tr><td>4</td><td>Press Release</td><td><a href="ex99-1.htm">ex99-1.htm</a></td><td>EX-99.1</td></tr>
</table></body></html>
"""

class FakeResponse:
    def __init__(self, text):
        self.text = text

def test_filing_documents_extracts_relevant_exhibits():
    sec = SecClient(user_agent="SSM-Test test@example.com", pause=0)
    sec._get = lambda url: FakeResponse(INDEX_HTML)
    docs = sec.filing_documents(
        "1234567",
        "0000123456-26-123456",
        index_url="https://www.sec.gov/Archives/edgar/data/1234567/000012345626123456/index.htm",
    )
    types = [d["type"] for d in docs]
    assert "EX-4.1" in types
    assert "EX-10.1" in types
    assert "EX-99.1" in types
    assert "8-K" not in types
