from __future__ import annotations
import os, re, time, datetime as dt, html
import urllib.parse
import xml.etree.ElementTree as ET
import requests

SEC_BASE = "https://www.sec.gov"
SEC_DATA_BASE = "https://data.sec.gov"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

class SecClient:
    def __init__(self, user_agent=None, pause=.20, max_retries=3):
        raw_user_agent = user_agent or os.getenv("SEC_USER_AGENT", "")
        if not raw_user_agent:
            raise RuntimeError("Set SEC_USER_AGENT='Organization ContactEmail' before live SEC requests.")
        self.user_agent = raw_user_agent.encode("ascii", "ignore").decode("ascii").strip()
        if not self.user_agent:
            raise RuntimeError("SEC_USER_AGENT became empty after ASCII normalization.")
        self.pause = pause
        self.max_retries = max_retries
        self.last_discovery_mode = None
        self._submissions_cache = {}
        self._facts_cache = {}
        self._ticker_cache = None
        self._texts_cache = {}
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json,text/plain,text/html,application/atom+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        })

    def _get(self, url):
        last = None
        for attempt in range(self.max_retries):
            time.sleep(self.pause * (attempt + 1))
            try:
                r = self.s.get(url, timeout=30)
                if r.status_code in (403, 429, 500, 502, 503, 504):
                    last = requests.HTTPError(f"{r.status_code} for {url}", response=r)
                    if attempt < self.max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last = e
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        raise last

    def exchange_tickers(self):
        if self._ticker_cache is None:
            r = self._get(f"{SEC_BASE}/files/company_tickers_exchange.json").json()
            fields = r["fields"]
            self._ticker_cache = [dict(zip(fields, row)) for row in r["data"]]
        return self._ticker_cache

    def daily_master_index(self, day):
        q = (day.month - 1) // 3 + 1
        url = f"{SEC_BASE}/Archives/edgar/daily-index/{day.year}/QTR{q}/master.{day:%Y%m%d}.idx"
        try:
            txt = self._get(url).text
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return []
            raise
        lines = txt.splitlines()
        start = 0
        for i, line in enumerate(lines):
            if line.startswith("CIK|Company Name|Form Type|Date Filed|Filename"):
                start = i + 1
                break
        out = []
        for line in lines[start:]:
            if "|" not in line:
                continue
            p = line.split("|")
            if len(p) == 5:
                out.append({
                    "cik": p[0], "company": p[1], "form": p[2],
                    "filed": p[3], "filename": p[4], "source": "daily-index",
                })
        return out

    def _daily_recent_filings(self, days, forms):
        forms = set(forms)
        today = dt.date.today()
        rows = []
        for i in range(days + 1):
            for row in self.daily_master_index(today - dt.timedelta(days=i)):
                if row["form"] in forms:
                    rows.append(row)
        self.last_discovery_mode = "daily-index"
        return rows

    @staticmethod
    def _atom_entry_date(entry):
        summary = entry.findtext("a:summary", default="", namespaces=ATOM_NS) or ""
        m = re.search(r"Filed:\s*</?[^>]*>?\s*(\d{4}-\d{2}-\d{2})", summary, re.I)
        if not m:
            m = re.search(r"Filed:\s*(\d{4}-\d{2}-\d{2})", re.sub(r"<[^>]+>", " ", summary), re.I)
        if m:
            return m.group(1)
        updated = entry.findtext("a:updated", default="", namespaces=ATOM_NS) or ""
        return updated[:10] if len(updated) >= 10 else ""

    @staticmethod
    def _atom_entry_link(entry):
        for link in entry.findall("a:link", ATOM_NS):
            href = link.attrib.get("href", "")
            if "/Archives/edgar/data/" in href:
                return href
        for link in entry.findall("a:link", ATOM_NS):
            href = link.attrib.get("href", "")
            if href:
                return href
        return ""

    def atom_recent_filings(self, days, forms, count=100, max_pages_per_form=15):
        cutoff = dt.date.today() - dt.timedelta(days=days)
        rows = []
        seen = set()
        for form in forms:
            for page in range(max_pages_per_form):
                params = {
                    "action": "getcurrent",
                    "type": form,
                    "owner": "include",
                    "start": page * count,
                    "count": count,
                    "output": "atom",
                }
                url = f"{SEC_BASE}/cgi-bin/browse-edgar?{urllib.parse.urlencode(params)}"
                xml_text = self._get(url).text
                try:
                    root = ET.fromstring(xml_text)
                except ET.ParseError:
                    break
                entries = root.findall("a:entry", ATOM_NS)
                if not entries:
                    break
                oldest = None
                for entry in entries:
                    filed = self._atom_entry_date(entry)
                    try:
                        filed_date = dt.date.fromisoformat(filed)
                    except Exception:
                        continue
                    oldest = filed_date if oldest is None or filed_date < oldest else oldest
                    if filed_date < cutoff:
                        continue
                    link = self._atom_entry_link(entry)
                    title = entry.findtext("a:title", default="", namespaces=ATOM_NS) or ""
                    summary = entry.findtext("a:summary", default="", namespaces=ATOM_NS) or ""
                    cik_m = re.search(r"/data/(\d+)/", link)
                    if not cik_m:
                        cik_m = re.search(r"\((\d{6,10})\)", title)
                    acc_m = re.search(r"(\d{10}-\d{2}-\d{6})", link + " " + summary)
                    if not cik_m:
                        continue
                    cik = str(int(cik_m.group(1)))
                    accession = acc_m.group(1) if acc_m else ""
                    key = (cik, accession or link, form)
                    if key in seen:
                        continue
                    seen.add(key)
                    filename = ""
                    if "/Archives/" in link:
                        filename = link.split("/Archives/", 1)[1]
                    rows.append({
                        "cik": cik,
                        "company": title,
                        "form": form,
                        "filed": filed,
                        "filename": filename,
                        "index_url": link,
                        "accession": accession,
                        "source": "atom",
                    })
                if len(entries) < count or (oldest is not None and oldest < cutoff):
                    break
        self.last_discovery_mode = "atom"
        return rows

    def recent_filings(self, days, forms):
        mode = os.getenv("SSM_SEC_DISCOVERY_MODE", "auto").strip().lower()
        if mode == "atom":
            return self.atom_recent_filings(days, forms)
        if mode in ("daily", "daily-index"):
            return self._daily_recent_filings(days, forms)
        try:
            return self._daily_recent_filings(days, forms)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                return self.atom_recent_filings(days, forms)
            raise

    def submission_text(self, filename_or_url):
        url = filename_or_url if filename_or_url.startswith(('http://', 'https://')) else f"{SEC_BASE}/Archives/{filename_or_url.lstrip('/')}"
        if url not in self._texts_cache:
            self._texts_cache[url] = self._get(url).text
        return self._texts_cache[url]

    def filing_index_url(self, cik, accession, index_url=None):
        if index_url:
            return index_url
        acc = str(accession or "")
        if not acc:
            return ""
        return (
            f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/"
            f"{acc.replace('-', '')}/{acc}-index.htm"
        )

    def filing_documents(self, cik, accession, index_url=None):
        url = self.filing_index_url(cik, accession, index_url=index_url)
        if not url:
            return []
        page = self.submission_text(url)
        docs = []
        seen = set()
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, re.I | re.S):
            plain = html.unescape(re.sub(r"<[^>]+>", " ", row))
            plain = re.sub(r"\s+", " ", plain).strip()
            type_m = re.search(r"\b(EX-(?:2|4|10|99)(?:\.\d+)?)\b", plain, re.I)
            if not type_m:
                continue
            href_m = re.search(r'href=["\']([^"\']+)["\']', row, re.I)
            if not href_m:
                continue
            href = urllib.parse.urljoin(url, html.unescape(href_m.group(1)))
            if href in seen:
                continue
            if re.search(r"\.(?:xml|xsd|jpg|jpeg|gif|png)$", href, re.I):
                continue
            seen.add(href)
            docs.append({
                "type": type_m.group(1).upper(),
                "url": href,
                "description": plain[:300],
            })
        priority = {"EX-2": 0, "EX-4": 1, "EX-10": 2, "EX-99": 3}
        docs.sort(key=lambda d: (
            min((rank for prefix, rank in priority.items() if d["type"].startswith(prefix)), default=9),
            d["type"],
        ))
        return docs

    def relevant_exhibit_texts(self, cik, accession, index_url=None, max_docs=6):
        out = []
        for doc in self.filing_documents(cik, accession, index_url=index_url)[:max_docs]:
            try:
                text = self.submission_text(doc["url"])
            except requests.RequestException:
                continue
            out.append({**doc, "text": text})
        return out

    def submissions(self, cik):
        key = str(int(cik))
        if key not in self._submissions_cache:
            self._submissions_cache[key] = self._get(
                f"{SEC_DATA_BASE}/submissions/CIK{int(cik):010d}.json"
            ).json()
        return self._submissions_cache[key]

    def submission_record(self, cik, accession=None, form=None, filed=None):
        recent = self.submissions(cik).get("filings", {}).get("recent", {})
        n = len(recent.get("form", []))
        fields = list(recent.keys())
        for i in range(n):
            rec = {k: recent.get(k, [None] * n)[i] if i < len(recent.get(k, [])) else None for k in fields}
            if accession and rec.get("accessionNumber") == accession:
                return rec
            if not accession and form and filed and rec.get("form") == form and rec.get("filingDate") == filed:
                return rec
        return None

    def enrich_filing(self, cik, filing):
        rec = self.submission_record(
            cik,
            accession=filing.get("accession") or None,
            form=filing.get("form"),
            filed=filing.get("filed"),
        )
        out = dict(filing)
        if not rec:
            return out
        out["accession"] = rec.get("accessionNumber") or out.get("accession", "")
        out["items"] = rec.get("items") or ""
        out["primary_document"] = rec.get("primaryDocument") or ""
        out["primary_description"] = rec.get("primaryDocDescription") or ""
        if rec.get("filingDate"):
            out["filed"] = rec["filingDate"]
        if rec.get("form"):
            out["form"] = rec["form"]
        acc = out.get("accession", "")
        doc = out.get("primary_document", "")
        if acc and doc:
            out["filename"] = f"edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
        return out

    def latest_financial_record(self, cik):
        r = self.submissions(cik).get("filings", {}).get("recent", {})
        n = len(r.get("form", []))
        for i in range(n):
            form = r.get("form", [""] * n)[i]
            if form not in ("10-Q", "10-K"):
                continue
            filed = r.get("filingDate", [""] * n)[i]
            acc = r.get("accessionNumber", [""] * n)[i]
            doc = r.get("primaryDocument", [""] * n)[i]
            desc = r.get("primaryDocDescription", [""] * n)[i] if i < len(r.get("primaryDocDescription", [])) else ""
            return {
                "cik": str(int(cik)),
                "form": form,
                "filed": filed,
                "accession": acc,
                "primary_document": doc,
                "primary_description": desc or "",
                "report_date": r.get("reportDate", [""] * n)[i] or filed,
                "filename": f"edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}",
                "source": "submissions-financial",
            }
        return None

    def latest_financial_filing(self, cik):
        rec = self.latest_financial_record(cik)
        return rec.get("filed") if rec else None

    def companyfacts(self, cik):
        key = str(int(cik))
        if key not in self._facts_cache:
            self._facts_cache[key] = self._get(
                f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
            ).json()
        return self._facts_cache[key]

def latest_fact_value(companyfacts, tag):
    node = (
        companyfacts.get("facts", {}).get("dei", {}).get(tag)
        or companyfacts.get("facts", {}).get("us-gaap", {}).get(tag)
    )
    if not node:
        return None
    rows = []
    for u in node.get("units", {}).values():
        rows.extend(u)
    rows = [x for x in rows if x.get("val") is not None and x.get("filed")]
    rows.sort(key=lambda x: x.get("filed", ""), reverse=True)
    return rows[0]["val"] if rows else None

def filing_risk_flags(text):
    t = re.sub(r"\s+", " ", text or "").lower()
    return {
        "going_concern": "substantial doubt about our ability to continue as a going concern" in t,
        "nasdaq_deficiency": bool(re.search(r"minimum bid price|nasdaq deficiency|listing qualifications", t)),
        "reverse_split": bool(re.search(r"reverse stock split|reverse split", t)),
        "vie_or_offshore": bool(re.search(r"variable interest entity|\bvie\b|cayman islands|british virgin islands|\bbvi\b|\bprc\b", t)),
        "related_party": "related party" in t or "related-party" in t,
        "auditor_flag": bool(re.search(r"auditor resignation|dismissed.*independent registered public accounting firm|pcaob.*unable", t)),
    }
