"""
PaperPortfolio — simulated portfolio with configurable starting capital.
Tracks positions, executes paper trades, checks stop-losses and targets.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
import yfinance as yf

log = logging.getLogger("Portfolio")

PORTFOLIO_FILE = Path("data/portfolio.json")
SNAPSHOTS_FILE = Path("data/snapshots.json")
STATUS_FILE = Path("data/status.json")

STARTING_CAPITAL = float(os.getenv("PAPER_CAPITAL", 50_000))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 15)) / 100
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", 7)) / 100
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", 25)) / 100
BENCHMARK_SYMBOL = os.getenv("BENCHMARK_SYMBOL", "SPY")


class PaperPortfolio:

    def __init__(self):
        self._load()

    # ── Core access ───────────────────────────────────────────────

    def positions(self) -> list[dict]:
        return self.state.get("positions", [])

    def cash(self) -> float:
        return self.state.get("cash", STARTING_CAPITAL)

    def nav(self) -> float:
        total = self.cash()
        for p in self.positions():
            total += p["shares"] * p["last_price"]
        return total

    def summary(self) -> dict:
        pos = self.positions()
        nav = self.nav()
        benchmark_return = self.benchmark_return()
        total_return = (nav - STARTING_CAPITAL) / STARTING_CAPITAL
        portfolio_beta = self.portfolio_beta()
        beta_adjusted_alpha = (
            total_return - (portfolio_beta * benchmark_return)
            if benchmark_return is not None and portfolio_beta is not None
            else None
        )
        return {
            "nav": round(nav, 2),
            "cash": round(self.cash(), 2),
            "positions": len(pos),
            "tickers": [p["ticker"] for p in pos],
            "total_return_pct": round(total_return, 4),
            "benchmark_symbol": self.state.get("benchmark_symbol", BENCHMARK_SYMBOL),
            "benchmark_return_pct": round(benchmark_return, 4) if benchmark_return is not None else None,
            "alpha_pct": round(total_return - benchmark_return, 4) if benchmark_return is not None else None,
            "portfolio_beta": round(portfolio_beta, 3) if portfolio_beta is not None else None,
            "beta_adjusted_alpha_pct": round(beta_adjusted_alpha, 4) if beta_adjusted_alpha is not None else None,
        }

    # ── Trade execution ───────────────────────────────────────────

    def execute(self, signal: dict):
        ticker = signal["ticker"]
        action = signal["action"]
        price = signal["price"]
        confidence = signal.get("confidence", 0)
        suggested_pct = signal.get("suggested_position_pct", 5) / 100

        if action == "BUY":
            self._buy(ticker, price, confidence, suggested_pct)
        elif action == "SELL":
            self._sell(ticker, price, "signal")

    def _buy(self, ticker: str, price: float, confidence: float, suggested_pct: float):
        # Don't double up
        existing = next((p for p in self.positions() if p["ticker"] == ticker), None)
        if existing:
            log.info(f"Already hold {ticker} — skipping BUY")
            return

        # Size the position based on confidence + suggested %
        alloc_pct = min(suggested_pct * confidence, MAX_POSITION_PCT)
        capital = self.nav() * alloc_pct
        if capital > self.cash():
            capital = self.cash() * 0.90  # Use available cash

        shares = int(capital / price)
        if shares < 1:
            log.info(f"Insufficient capital for {ticker}")
            return

        cost = shares * price
        self.state["cash"] -= cost
        self.state["positions"].append({
            "ticker": ticker,
            "shares": shares,
            "avg_cost": price,
            "last_price": price,
            "stop_loss": round(price * (1 - STOP_LOSS_PCT), 2),
            "take_profit": round(price * (1 + TAKE_PROFIT_PCT), 2),
            "entered_at": datetime.now().isoformat(),
            "confidence": confidence,
        })
        self._log_trade(ticker, "BUY", shares, price, cost)
        self._save()

    def _sell(self, ticker: str, price: float, reason: str):
        pos = next((p for p in self.positions() if p["ticker"] == ticker), None)
        if not pos:
            return

        proceeds = pos["shares"] * price
        pnl = proceeds - (pos["shares"] * pos["avg_cost"])
        pnl_pct = pnl / (pos["shares"] * pos["avg_cost"])

        self.state["cash"] += proceeds
        self.state["positions"] = [p for p in self.positions() if p["ticker"] != ticker]
        self.state["trade_history"].append({
            "ticker": ticker,
            "action": "SELL",
            "shares": pos["shares"],
            "price": price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
            "reason": reason,
            "at": datetime.now().isoformat(),
        })
        self._log_trade(ticker, "SELL", pos["shares"], price, proceeds, pnl)
        self._save()

    def _log_trade(self, ticker, action, shares, price, total, pnl=None):
        entry = {
            "ticker": ticker, "action": action,
            "shares": shares, "price": price, "total": round(total, 2),
            "at": datetime.now().isoformat(),
        }
        if pnl is not None:
            entry["pnl"] = round(pnl, 2)
        self.state.setdefault("trade_history", []).append(entry)

    # ── Risk management ───────────────────────────────────────────

    def check_stops_and_targets(self) -> list[dict]:
        self.refresh_prices()
        alerts = []
        for pos in self.positions():
            price = pos["last_price"]
            if price <= pos["stop_loss"]:
                self._sell(pos["ticker"], price, "stop_loss")
                alerts.append({"ticker": pos["ticker"], "type": "STOP_LOSS", "price": price})
            elif price >= pos["take_profit"]:
                self._sell(pos["ticker"], price, "take_profit")
                alerts.append({"ticker": pos["ticker"], "type": "TAKE_PROFIT", "price": price})
        return alerts

    def refresh_prices(self):
        today = datetime.now().date().isoformat()
        if self.state.get("refresh_date") == today:
            count = self.state.get("refresh_count", 0)
        else:
            count = 0
        if count >= 3:
            log.debug("Daily price refresh limit (3) reached — using cached prices")
            return
        for pos in self.state["positions"]:
            try:
                ticker_obj = yf.Ticker(pos["ticker"])
                hist = ticker_obj.history(period="1d")
                if not hist.empty:
                    pos["last_price"] = round(float(hist["Close"].iloc[-1]), 2)
            except Exception as e:
                log.debug(f"Could not refresh {pos['ticker']}: {e}")
        self.state["refresh_date"] = today
        self.state["refresh_count"] = count + 1
        self._save()

    # ── Reporting ─────────────────────────────────────────────────

    def daily_summary(self) -> dict:
        snaps = self._load_snapshots()
        prev_nav = snaps[-1]["nav"] if snaps else STARTING_CAPITAL
        current_nav = self.nav()
        day_pnl = (current_nav - prev_nav) / prev_nav
        benchmark_return = self.benchmark_return()
        total_return = (current_nav - STARTING_CAPITAL) / STARTING_CAPITAL

        return {
            "nav": round(current_nav, 2),
            "cash": round(self.cash(), 2),
            "day_pnl": round(day_pnl, 4),
            "total_return": round(total_return, 4),
            "benchmark_symbol": self.state.get("benchmark_symbol", BENCHMARK_SYMBOL),
            "benchmark_return": round(benchmark_return, 4) if benchmark_return is not None else None,
            "alpha": round(total_return - benchmark_return, 4) if benchmark_return is not None else None,
            "portfolio_beta": self.summary().get("portfolio_beta"),
            "beta_adjusted_alpha": self.summary().get("beta_adjusted_alpha_pct"),
            "positions": len(self.positions()),
            "tickers": [p["ticker"] for p in self.positions()],
            "date": datetime.now().date().isoformat(),
        }

    def weekly_stats(self) -> dict:
        history = self.state.get("trade_history", [])
        wins = [t for t in history if t.get("pnl", 0) > 0]
        losses = [t for t in history if t.get("pnl", 0) < 0]
        win_rate = len(wins) / max(len(wins) + len(losses), 1)
        avg_win = sum(t["pnl"] for t in wins) / max(len(wins), 1)
        avg_loss = sum(t["pnl"] for t in losses) / max(len(losses), 1)

        return {
            "total_trades": len(history),
            "win_rate": round(win_rate, 3),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0,
            "nav": round(self.nav(), 2),
            "total_return": round((self.nav() - STARTING_CAPITAL) / STARTING_CAPITAL, 4),
            "benchmark_symbol": self.state.get("benchmark_symbol", BENCHMARK_SYMBOL),
            "benchmark_return": self.summary().get("benchmark_return_pct"),
            "alpha": self.summary().get("alpha_pct"),
            "portfolio_beta": self.summary().get("portfolio_beta"),
            "beta_adjusted_alpha": self.summary().get("beta_adjusted_alpha_pct"),
        }

    def save_snapshot(self):
        snaps = self._load_snapshots()
        summary = self.summary()
        snaps.append({
            "date": datetime.now().isoformat(),
            "nav": summary["nav"],
            "total_return_pct": summary["total_return_pct"],
            "benchmark_symbol": summary["benchmark_symbol"],
            "benchmark_return_pct": summary["benchmark_return_pct"],
            "alpha_pct": summary["alpha_pct"],
            "portfolio_beta": summary["portfolio_beta"],
            "beta_adjusted_alpha_pct": summary["beta_adjusted_alpha_pct"],
        })
        SNAPSHOTS_FILE.write_text(json.dumps(snaps[-365:], indent=2))  # Keep 1 year
        self.write_status()

    def benchmark_return(self) -> float | None:
        """Return benchmark performance since this paper portfolio started."""
        current = self._latest_price(BENCHMARK_SYMBOL)
        if current is None:
            return None

        baseline = self.state.get("benchmark_start_price")
        if not baseline:
            self.state["benchmark_symbol"] = BENCHMARK_SYMBOL
            self.state["benchmark_start_price"] = current
            self.state["benchmark_started_at"] = datetime.now().isoformat()
            self._save()
            return 0.0

        return (current - baseline) / baseline

    def portfolio_beta(self) -> float | None:
        """Estimate weighted beta using current holdings and cash beta of zero."""
        nav = self.nav()
        if nav <= 0:
            return None

        total_beta = 0.0
        beta_weight = 0.0
        for pos in self.positions():
            market_value = pos["shares"] * pos["last_price"]
            weight = market_value / nav
            beta = pos.get("beta")
            if beta is None:
                beta = self._ticker_beta(pos["ticker"])
                if beta is not None:
                    pos["beta"] = beta
            if beta is None:
                continue
            total_beta += weight * beta
            beta_weight += weight

        if beta_weight == 0:
            return 0.0 if not self.positions() else None

        self._save()
        return total_beta

    def write_status(self):
        """Write a compact local status file for dashboards and review."""
        STATUS_FILE.parent.mkdir(exist_ok=True)
        STATUS_FILE.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "starting_capital": STARTING_CAPITAL,
            "summary": self.summary(),
            "positions": self.positions(),
            "trade_history": self.state.get("trade_history", [])[-50:],
            "snapshots": self._load_snapshots()[-120:],
        }, indent=2))

    # ── Persistence ───────────────────────────────────────────────

    def _load(self):
        try:
            self.state = json.loads(PORTFOLIO_FILE.read_text())
        except Exception:
            self.state = {
                "cash": STARTING_CAPITAL,
                "positions": [],
                "trade_history": [],
                "started": datetime.now().isoformat(),
                "starting_capital": STARTING_CAPITAL,
                "benchmark_symbol": BENCHMARK_SYMBOL,
            }
            self._save()

    def _save(self):
        PORTFOLIO_FILE.parent.mkdir(exist_ok=True)
        PORTFOLIO_FILE.write_text(json.dumps(self.state, indent=2))

    def _load_snapshots(self) -> list:
        try:
            return json.loads(SNAPSHOTS_FILE.read_text())
        except Exception:
            return []

    def _latest_price(self, ticker: str) -> float | None:
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty:
                return None
            return round(float(hist["Close"].iloc[-1]), 2)
        except Exception as e:
            log.debug(f"Could not fetch {ticker}: {e}")
            return None

    def _ticker_beta(self, ticker: str) -> float | None:
        try:
            info = yf.Ticker(ticker).info
            beta = info.get("beta")
            return float(beta) if beta is not None else None
        except Exception as e:
            log.debug(f"Could not fetch beta for {ticker}: {e}")
            return None
