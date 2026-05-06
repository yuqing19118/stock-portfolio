"""
ResearchWatcher — daily news/filing-style context collector.

This does not trade. It gives the agent a structured memory of what changed:
Yahoo Finance news, financial snapshots, analyst-style metadata available
through yfinance, and user-provided research notes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf
from core.memory import AgentMemory

log = logging.getLogger("ResearchWatcher")

RESEARCH_NOTES_FILE = Path("data/research_notes.json")
RESEARCH_FEED_FILE = Path("data/research_feed.json")


DEFAULT_RESEARCH_TICKERS = [
    "NVDA", "CSX", "MU", "TSM", "WDC", "SIMO", "AVGO", "ASML", "ARM",
    "SMH", "QQQ", "SPY",
]


class ResearchWatcher:
    def __init__(self, max_tickers: int = 18):
        self.max_tickers = max_tickers

    def run(self, portfolio) -> dict:
        """Collect daily research context for active and relevant watchlist names."""
        tickers = self._research_universe(portfolio)
        feed = {
            "updated_at": datetime.now().isoformat(),
            "source_policy": "Yahoo Finance/yfinance plus user-provided research notes. Reference only; not a trade instruction.",
            "tickers": tickers,
            "items": [],
            "takeaways": [],
            "risk_flags": [],
        }

        for ticker in tickers:
            try:
                feed["items"].append(self._ticker_snapshot(ticker))
            except Exception as e:
                log.debug(f"Research snapshot failed for {ticker}: {e}")

        feed["takeaways"] = self._derive_takeaways(feed["items"])
        feed["risk_flags"] = self._derive_risk_flags(feed["items"])

        RESEARCH_FEED_FILE.parent.mkdir(exist_ok=True)
        RESEARCH_FEED_FILE.write_text(json.dumps(feed, indent=2, ensure_ascii=False))
        self._remember(feed)
        log.info(f"Research feed updated for {len(feed['items'])} tickers")
        return feed

    def _research_universe(self, portfolio) -> list[str]:
        tickers = []

        for pos in portfolio.positions():
            tickers.append(pos["ticker"])

        tickers.extend(DEFAULT_RESEARCH_TICKERS)

        notes = self._load_research_notes()
        for key in ("preferred_core_watchlist", "tactical_high_beta_watchlist"):
            for item in notes.get(key, []):
                ticker = item.get("ticker")
                if ticker:
                    tickers.append(ticker)

        clean = []
        seen = set()
        for ticker in tickers:
            if ticker not in seen:
                clean.append(ticker)
                seen.add(ticker)
            if len(clean) >= self.max_tickers:
                break
        return clean

    def _ticker_snapshot(self, ticker: str) -> dict:
        t = yf.Ticker(ticker)
        info = self._safe_info(t)
        news = self._safe_news(t)

        return {
            "ticker": ticker,
            "company": info.get("shortName") or info.get("longName") or ticker,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "beta": info.get("beta"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "profit_margin": info.get("profitMargins"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "recommendation": info.get("recommendationKey"),
            "target_mean_price": info.get("targetMeanPrice"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "latest_news": news[:5],
            "updated_at": datetime.now().isoformat(),
        }

    def _safe_info(self, ticker_obj) -> dict:
        try:
            return ticker_obj.info or {}
        except Exception:
            return {}

    def _safe_news(self, ticker_obj) -> list[dict]:
        try:
            raw = ticker_obj.news or []
        except Exception:
            return []

        items = []
        for item in raw:
            content = item.get("content", item) if isinstance(item, dict) else {}
            title = content.get("title") or item.get("title") if isinstance(item, dict) else None
            publisher = content.get("provider", {}).get("displayName") if isinstance(content.get("provider"), dict) else item.get("publisher")
            link = content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else item.get("link")
            pub_time = content.get("pubDate") or item.get("providerPublishTime")
            if isinstance(pub_time, int):
                pub_time = datetime.fromtimestamp(pub_time, tz=timezone.utc).isoformat()
            if title:
                items.append({
                    "title": title,
                    "publisher": publisher,
                    "published_at": pub_time,
                    "url": link,
                })
        return items

    def _derive_takeaways(self, items: list[dict]) -> list[str]:
        takeaways = []
        for item in items:
            ticker = item.get("ticker")
            beta = item.get("beta")
            rev_growth = item.get("revenue_growth")
            margin = item.get("profit_margin")
            rec = item.get("recommendation")

            if beta and beta > 1.5:
                takeaways.append(f"{ticker}: high beta ({beta:.2f}); returns must be judged on beta-adjusted alpha.")
            if rev_growth and rev_growth > 0.20:
                takeaways.append(f"{ticker}: revenue growth is strong ({rev_growth:.1%}); verify whether valuation already prices it in.")
            if margin and margin > 0.25:
                takeaways.append(f"{ticker}: high profit margin ({margin:.1%}); research moat durability.")
            if rec:
                takeaways.append(f"{ticker}: Yahoo recommendation key is '{rec}'; treat as context, not proof.")

        return takeaways[:12]

    def _derive_risk_flags(self, items: list[dict]) -> list[str]:
        flags = []
        for item in items:
            ticker = item.get("ticker")
            pe = item.get("trailing_pe") or item.get("forward_pe")
            beta = item.get("beta")
            news_count = len(item.get("latest_news") or [])
            if pe and pe > 60:
                flags.append(f"{ticker}: valuation is rich (P/E {pe:.1f}); require stronger growth confirmation.")
            if beta and beta > 2:
                flags.append(f"{ticker}: beta above 2; position size and options exposure must stay capped.")
            if news_count == 0:
                flags.append(f"{ticker}: no recent Yahoo news fetched; do not infer no news.")
        return flags[:12]

    def _load_research_notes(self) -> dict:
        try:
            return json.loads(RESEARCH_NOTES_FILE.read_text())
        except Exception:
            return {}

    def _remember(self, feed: dict):
        memory = AgentMemory()
        memory.remember("daily_research_feed", {
            "updated_at": feed.get("updated_at"),
            "tickers": feed.get("tickers", []),
            "takeaways": feed.get("takeaways", []),
            "risk_flags": feed.get("risk_flags", []),
        })
        for item in feed.get("items", []):
            memory.remember("ticker_research_snapshot", {
                "ticker": item.get("ticker"),
                "company": item.get("company"),
                "beta": item.get("beta"),
                "trailing_pe": item.get("trailing_pe"),
                "forward_pe": item.get("forward_pe"),
                "profit_margin": item.get("profit_margin"),
                "revenue_growth": item.get("revenue_growth"),
                "recommendation": item.get("recommendation"),
                "news_titles": [n.get("title") for n in item.get("latest_news", [])],
            })
