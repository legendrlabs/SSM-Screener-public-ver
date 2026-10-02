"""Resolve the listed security from SEC cover classes, not an issuer CIK."""
import re
from .capital_evidence import _Tables


def registered_securities(text: str) -> dict[str, str]:
    parser = _Tables()
    parser.feed(re.sub(r'<(ix:header|ix:hidden|script|style)\b[^>]*>.*?</\1\s*>', ' ', text or '', flags=re.I | re.S)[:90000])
    for table in parser.tables:
        if not re.search(r'Title of each class', ' '.join(' '.join(row) for row in table['rows']), re.I):
            continue
        out = {}
        for row in table['rows']:
            cells = [cell.strip() for cell in row if cell.strip()]
            if len(cells) < 3 or re.search(r'Title of each class', cells[0], re.I):
                continue
            # Cover tables contain one class, a trading symbol and an exchange.
            # Par value can occupy a separate cell before the symbol.
            for i, cell in enumerate(cells[1:-1], 1):
                if re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', cell):
                    out[cell] = ' '.join(cells[:i])
                    break
        if out:
            return out
    return {}


def security_type(title: str, issuer_name: str = '') -> str:
    if re.search(r'\bETF\b|exchange[- ]traded fund', issuer_name + ' ' + title, re.I):
        return 'FUND'
    if re.search(r'notes?\b|debentures?\b|bonds?\b', title, re.I):
        return 'DEBT'
    if re.search(r'preferred|depositary shares', title, re.I):
        return 'PREFERRED'
    if re.search(r'warrants?\b', title, re.I):
        return 'WARRANT'
    if re.search(r'\bunits?\b|\brights?\b', title, re.I):
        return 'UNIT_OR_RIGHT'
    if re.search(r'common stock|ordinary shares|common shares|shares of beneficial interest|american depositary', title, re.I):
        return 'COMMON_EQUITY'
    return 'UNKNOWN'


def resolve_security(sec, meta, filing):
    issuer = sec.submissions(meta['cik']).get('name') or meta['name']
    if security_type('', issuer) == 'FUND':
        return {**meta, 'security_type': 'FUND', 'security_title': issuer, 'security_source': 'SEC submissions issuer name'}
    sources = [filing]
    financial = sec.latest_financial_record(meta['cik'])
    if financial:
        sources.append(financial)
    for source in sources:
        if not source.get('filename'):
            continue
        classes = registered_securities(sec.submission_text(source['filename']))
        if meta['ticker'] in classes:
            title = classes[meta['ticker']]
            return {**meta, 'security_type': security_type(title, issuer), 'security_title': title,
                    'security_source': 'https://www.sec.gov/Archives/' + source['filename']}
    return {**meta, 'security_type': 'UNKNOWN', 'security_title': '', 'security_source': 'SEC registered class unresolved'}
