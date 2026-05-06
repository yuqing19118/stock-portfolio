"""
StockScanner — pulls live data and screens the universe for candidates.
Uses yfinance (free) + basic fundamental filters.
"""

from __future__ import annotations

import yfinance as yf
import pandas as pd
import logging
from datetime import datetime, timedelta

log = logging.getLogger("Scanner")

# The universe — S&P 500 large caps as a starting point
UNIVERSE = [
    # ── Real holdings (always watched first) ─────────────────────────
    "MU","CHYM","MSFT","AVGO","ADBE","ALAB","PLTR","MRVL","SMCI","KLAR",
    "QQQ","SQQQ","BITI","BTC-USD","XRP-USD",
    # ── Semis & AI hardware ───────────────────────────────────────────
    "NVDA","AMD","TSM","ASML","ARM","QCOM","TXN","WDC","SIMO",
    # ── Mega-cap tech ─────────────────────────────────────────────────
    "AAPL","GOOGL","AMZN","META","TSLA","ORCL","CRM","NFLX",
    # ── Financials ────────────────────────────────────────────────────
    "JPM","GS","MS","BAC","V","MA","AXP","BLK","SPGI",
    # ── Healthcare & consumer ─────────────────────────────────────────
    "UNH","LLY","JNJ","MRK","ABBV","AMGN","VRTX","REGN",
    # ── Industrials & energy ──────────────────────────────────────────
    "XOM","CVX","GE","CAT","DE","RTX","FDX","UPS","CSX",
    # ── Broad ETFs ────────────────────────────────────────────────────
    "SPY","QQQ","QQQM","SMH","VTI","VXUS","SGOV","IBIT",
    # ── Cyber & cloud ─────────────────────────────────────────────────
    "PANW","CRWD","SNOW","DDOG","NET","ZS","GTLB","NOW",
]


class StockScanner:

    def scan_universe(self) -> list[dict]:
        """Download data for all tickers, compute indicators, return candidates."""
        log.info(f"Downloading data for {len(UNIVERSE)} symbols...")
        results = []

        for ticker in UNIVERSE:
            try:
                data = self._fetch(ticker)
                if data is None:
                    continue
                indicators = self._compute_indicators(ticker, data)
                results.append(indicators)
            except Exception as e:
                log.debug(f"Skipped {ticker}: {e}")

        log.info(f"Successfully processed {len(results)} symbols")
        return results

    def _fetch(self, ticker: str) -> pd.DataFrame | None:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 50:
            return None
        df.index = pd.to_datetime(df.index)
        return df

    def _compute_indicators(self, ticker: str, df: pd.DataFrame) -> dict:
        close = df["Close"]
        volume = df["Volume"]

        # Price levels
        last = float(close.iloc[-1])
        high_52w = float(close.rolling(252).max().iloc[-1])
        low_52w = float(close.rolling(252).min().iloc[-1])

        # Moving averages
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1])
        sma200 = float(close.rolling(200).mean().iloc[-1])

        # Momentum — price change over various windows
        mom_1w = (last / float(close.iloc[-6]) - 1) if len(close) >= 6 else 0
        mom_1m = (last / float(close.iloc[-22]) - 1) if len(close) >= 22 else 0
        mom_3m = (last / float(close.iloc[-63]) - 1) if len(close) >= 63 else 0
        mom_6m = (last / float(close.iloc[-126]) - 1) if len(close) >= 126 else 0

        # RSI (14)
        rsi = self._rsi(close, 14)

        # Volume trend
        avg_vol_20 = float(volume.rolling(20).mean().iloc[-1])
        vol_ratio = float(volume.iloc[-1]) / avg_vol_20 if avg_vol_20 > 0 else 1.0

        # ATR for volatility
        atr = self._atr(df, 14)
        atr_pct = atr / last if last > 0 else 0

        # Proximity to 52w high (breakout indicator)
        pct_from_high = (last - high_52w) / high_52w
        pct_from_low = (last - low_52w) / low_52w

        # Fundamentals (may be None if not available)
        info = self._safe_info(ticker)

        return {
            "ticker": ticker,
            "last": last,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pct_from_high": pct_from_high,
            "pct_from_low": pct_from_low,
            "mom_1w": mom_1w,
            "mom_1m": mom_1m,
            "mom_3m": mom_3m,
            "mom_6m": mom_6m,
            "rsi": rsi,
            "vol_ratio": vol_ratio,
            "atr_pct": atr_pct,
            "pe": info.get("pe"),
            "roe": info.get("roe"),
            "revenue_growth": info.get("revenue_growth"),
            "profit_margin": info.get("profit_margin"),
            "debt_to_equity": info.get("debt_to_equity"),
            "sector": info.get("sector", "Unknown"),
        }

    def _rsi(self, close: pd.Series, period: int = 14) -> float:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("inf"))
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        h, l, c = df["High"], df["Low"], df["Close"]
        tr = pd.concat([
            h - l,
            (h - c.shift()).abs(),
            (l - c.shift()).abs()
        ], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    def _safe_info(self, ticker: str) -> dict:
        try:
            info = yf.Ticker(ticker).info
            return {
                "pe": info.get("trailingPE"),
                "roe": info.get("returnOnEquity"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "debt_to_equity": info.get("debtToEquity"),
                "sector": info.get("sector", "Unknown"),
            }
        except Exception:
            return {}
