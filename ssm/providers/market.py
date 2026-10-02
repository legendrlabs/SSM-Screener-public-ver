from __future__ import annotations
import os, datetime as dt, requests

def _snapshot_from_frame(hist):
    close = hist["Close"].dropna()
    if close.empty:
        raise RuntimeError("No close data")
    vol = hist["Volume"].fillna(0)
    price = float(close.iloc[-1])
    dollar = (hist["Close"] * vol).dropna().tail(20)
    return {
        "price": price,
        "price_as_of": str(close.index[-1]),
        "adv20_usd": float(dollar.mean()) if len(dollar) else None,
        "return_1d_pct": float((close.iloc[-1] / close.iloc[-2] - 1) * 100) if len(close) >= 2 else None,
        "return_5d_pct": float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if len(close) >= 6 else None,
    }

def _yfinance_snapshot(ticker):
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period="1mo", auto_adjust=False)
    if hist.empty:
        raise RuntimeError(f"No market data for {ticker}")
    return _snapshot_from_frame(hist)

def _yfinance_snapshots(tickers, chunk_size=100):
    import pandas as pd
    import yfinance as yf
    out = {}
    tickers = list(dict.fromkeys(t.upper() for t in tickers if t))
    for start in range(0, len(tickers), chunk_size):
        chunk = tickers[start:start + chunk_size]
        try:
            data = yf.download(
                tickers=chunk,
                period="1mo",
                auto_adjust=False,
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if len(chunk) == 1 and not isinstance(data.columns, pd.MultiIndex):
                out[chunk[0]] = _snapshot_from_frame(data)
                continue
            if isinstance(data.columns, pd.MultiIndex):
                first_level = set(data.columns.get_level_values(0))
                for ticker in chunk:
                    if ticker not in first_level:
                        continue
                    try:
                        out[ticker] = _snapshot_from_frame(data[ticker])
                    except Exception:
                        pass
        except Exception:
            pass
    # Conservative fallback only for names missed by the batch call.
    for ticker in tickers:
        if ticker in out:
            continue
        try:
            out[ticker] = _yfinance_snapshot(ticker)
        except Exception:
            pass
    return out

def _alpaca_snapshot(ticker):
    key = os.environ["APCA_API_KEY_ID"]
    secret = os.environ["APCA_API_SECRET_KEY"]
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=40)
    r = requests.get(
        f"https://data.alpaca.markets/v2/stocks/{ticker}/bars",
        headers=headers,
        params={
            "timeframe": "1Day", "start": start.isoformat(), "end": end.isoformat(),
            "limit": 50, "adjustment": "split", "feed": "iex",
        },
        timeout=30,
    )
    r.raise_for_status()
    bars = r.json().get("bars", [])
    if not bars:
        raise RuntimeError(f"No Alpaca bars for {ticker}")
    dollar = [float(x["c"]) * float(x["v"]) for x in bars[-20:]]
    return {
        "price": float(bars[-1]["c"]),
        "price_as_of": bars[-1]["t"],
        "adv20_usd": sum(dollar) / len(dollar),
        "return_1d_pct": (bars[-1]["c"] / bars[-2]["c"] - 1) * 100 if len(bars) >= 2 else None,
        "return_5d_pct": (bars[-1]["c"] / bars[-6]["c"] - 1) * 100 if len(bars) >= 6 else None,
    }

def market_snapshot(ticker):
    return _alpaca_snapshot(ticker) if os.getenv("SSM_MARKET_PROVIDER", "yfinance").lower() == "alpaca" else _yfinance_snapshot(ticker)

def market_snapshots(tickers):
    provider = os.getenv("SSM_MARKET_PROVIDER", "yfinance").lower()
    if provider == "alpaca":
        out = {}
        for ticker in tickers:
            try:
                out[ticker] = _alpaca_snapshot(ticker)
            except Exception:
                pass
        return out
    return _yfinance_snapshots(tickers)
