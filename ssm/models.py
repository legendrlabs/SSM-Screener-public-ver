from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict

@dataclass
class Dilution:
    common_shares: float = 0.0
    pre_funded_shares: float = 0.0
    options_itm_shares: float = 0.0
    warrants_itm_shares: float = 0.0
    warrants_otm_shares: float = 0.0
    converts_shares: float = 0.0
    preferred_shares_equiv: float = 0.0
    merger_consideration_shares: float = 0.0
    sbc_rsus_shares: float = 0.0
    atm_remaining_usd: float = 0.0
    warrant_exercise_cash_usd: float = 0.0
    pre_funded_warrants_outstanding: Optional[float] = None
    ordinary_warrants_outstanding: Optional[float] = None
    warrant_units_as_of: Optional[str] = None
    pending_stock_consideration_usd: Optional[float] = None
    source: str = ""
    confidence: str = "low"

    @property
    def near_fd_shares(self) -> float:
        return (self.common_shares + self.pre_funded_shares + self.options_itm_shares +
                self.warrants_itm_shares + self.sbc_rsus_shares)

    @property
    def strict_fd_shares(self) -> float:
        return (self.near_fd_shares + self.warrants_otm_shares + self.converts_shares +
                self.preferred_shares_equiv + self.merger_consideration_shares)

    @property
    def fd_ratio(self) -> Optional[float]:
        return self.strict_fd_shares / self.common_shares if self.common_shares > 0 and self.confidence != 'low' else None

@dataclass
class Candidate:
    ticker: str
    name: str = ""
    exchange: str = ""
    cik: str = ""
    security_type: str = 'COMMON_EQUITY'
    security_title: str = ''
    security_source: str = ''
    event_status: str = 'UNKNOWN'
    event_terms: Dict = field(default_factory=dict)
    event_sources: List[str] = field(default_factory=list)
    event_history: List[Dict] = field(default_factory=list)
    event_review_complete: bool = True
    event_selection_reason: str = ''
    most_recent_filing_date: Optional[str] = None
    price: Optional[float] = None
    price_as_of: Optional[str] = None
    adv20_usd: Optional[float] = None
    return_1d_pct: Optional[float] = None
    return_5d_pct: Optional[float] = None
    public_float: Optional[float] = None
    latest_financial_filing_date: Optional[str] = None
    latest_financial_form: Optional[str] = None
    latest_financial_accession: Optional[str] = None
    financial_review_complete: bool = False
    financial_note_hits: List[str] = field(default_factory=list)
    common_shares_source: str = ""
    share_count_conflict: bool = False
    exhibit_review_complete: bool = False
    exhibit_documents_reviewed: List[str] = field(default_factory=list)
    latest_event_date: Optional[str] = None
    latest_event_form: Optional[str] = None
    latest_event_accession: Optional[str] = None
    event_type: str = ""
    event_proof: int = 0
    event_summary: str = ""
    asset_value_usd: Optional[float] = None
    net_cash_usd: Optional[float] = None
    dilution: Dilution = field(default_factory=Dilution)
    going_concern: bool = False
    nasdaq_deficiency: bool = False
    reverse_split: bool = False
    vie_or_offshore: bool = False
    related_party: bool = False
    auditor_flag: bool = False
    data_warnings: List[str] = field(default_factory=list)
    gate_status: str = "DATA_HOLD"
    priority_score: Optional[float] = None
    bucket: str = "DATA_HOLD"

    def basic_market_cap(self):
        if self.event_terms.get('capital_counts_require_reconciliation'): return None
        if self.event_terms.get('post_transaction_ticker', self.ticker) != self.ticker: return None
        if self.security_type != 'COMMON_EQUITY' or self.event_status in {'TERMINAL', 'CANCELLED'} or self.gate_status == 'EXCLUDED': return None
        return self.price * self.dilution.common_shares if self.price is not None and self.dilution.common_shares > 0 else None

    def near_fd_market_cap(self):
        if self.basic_market_cap() is None: return None
        if self.dilution.confidence == 'low': return None
        return self.price * self.dilution.near_fd_shares if self.price is not None and self.dilution.near_fd_shares > 0 else None

    def strict_fd_market_cap(self):
        if self.basic_market_cap() is None: return None
        if self.dilution.confidence == 'low': return None
        return self.price * self.dilution.strict_fd_shares if self.price is not None and self.dilution.strict_fd_shares > 0 else None

    def nav_coverage(self):
        mc = self.strict_fd_market_cap()
        return self.asset_value_usd / mc if mc and self.asset_value_usd is not None else None

    def atm_ratio(self):
        mc = self.basic_market_cap()
        if not mc:
            return None
        return self.dilution.atm_remaining_usd / mc if self.dilution.atm_remaining_usd > 0 else 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d.update({
            "basic_market_cap": self.basic_market_cap(),
            "near_fd_market_cap": self.near_fd_market_cap(),
            "strict_fd_market_cap": self.strict_fd_market_cap(),
            "nav_coverage": self.nav_coverage(),
            "atm_ratio": self.atm_ratio(),
            "fd_ratio": None if self.event_terms.get('capital_counts_require_reconciliation') else self.dilution.fd_ratio,
        })
        return d
