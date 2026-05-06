"""
AgentBrain — the reasoning engine.
Scores stocks using multi-strategy signals, calls Claude API for
qualitative analysis, and tracks its own learning history.
"""

import json
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
import anthropic

log = logging.getLogger("Brain")

HISTORY_FILE = Path("data/brain_history.json")
REFLECTIONS_FILE = Path("data/reflections.json")

SYSTEM_PROMPT = """You are BuffetBot, an AI investment research agent trained in the principles of
Warren Buffett and Charlie Munger — value investing, moats, quality businesses, long-term thinking.

You are doing PAPER TRADING only — no real money is at risk. Your job is to:
1. Analyze stock candidates using fundamental and technical data provided
2. Assign a signal: BUY, SELL, HOLD, or WATCH
3. Give a confidence score 0.0 to 1.0 (only recommend action above 0.70)
4. Explain your reasoning concisely

Principles you follow:
- Favor quality businesses with durable competitive advantages (moats)
- Buy wonderful companies at fair prices, not fair companies at wonderful prices
- Pay attention to ROE, profit margins, debt levels, and revenue growth consistency
- Momentum matters — don't fight strong trends but don't chase parabolic moves
- Capital preservation first — avoid permanent loss of capital
- Be fearful when others are greedy, greedy when others are fearful

Always respond with valid JSON only. No prose outside the JSON."""


class AgentBrain:

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else None
        if not self.client:
            log.warning("ANTHROPIC_API_KEY not set — using rule-only analysis fallback")
        self._load_history()

    def score_candidates(self, candidates: list[dict], portfolio) -> list[dict]:
        """Score all candidates — rule-based pre-filter, then AI analysis on top picks."""
        # Step 1: Fast rule-based pre-filter (no API call)
        scored = [self._rule_score(c) for c in candidates]
        scored.sort(key=lambda x: abs(x["rule_score"]), reverse=True)

        # Step 2: AI deep analysis on top 10 candidates + existing positions
        top_candidates = scored[:10]
        existing_tickers = [p["ticker"] for p in portfolio.positions()]
        existing = [c for c in candidates if c["ticker"] in existing_tickers]

        to_analyze = {c["ticker"]: c for c in top_candidates + existing}

        signals = []
        for ticker, data in to_analyze.items():
            signal = self._ai_analyze(ticker, data, portfolio)
            signals.append(signal)
            log.info(f"{ticker}: {signal['action']} | confidence {signal['confidence']:.0%} | {signal['reason'][:60]}")

        return signals

    def _rule_score(self, c: dict) -> dict:
        """Fast quantitative scoring — no API call."""
        score = 0.0

        # Momentum signals
        if c.get("mom_3m", 0) > 0.10:
            score += 0.20
        if c.get("mom_6m", 0) > 0.20:
            score += 0.15
        if c.get("last", 0) > c.get("sma50", 0) > c.get("sma200", 0):
            score += 0.20  # Golden cross alignment

        # RSI — avoid extremes
        rsi = c.get("rsi", 50)
        if 40 < rsi < 65:
            score += 0.10
        elif rsi > 80:
            score -= 0.20  # Overbought
        elif rsi < 25:
            score += 0.15  # Oversold — potential mean reversion

        # Volume confirmation
        if c.get("vol_ratio", 1) > 1.5:
            score += 0.10

        # Proximity to 52w high — breakout signal
        pct_from_high = c.get("pct_from_high", -1)
        if -0.03 < pct_from_high <= 0:
            score += 0.25  # Near new high — breakout territory

        # Fundamental quality
        roe = c.get("roe", 0) or 0
        if roe > 0.20:
            score += 0.15
        pe = c.get("pe", 999) or 999
        if 10 < pe < 30:
            score += 0.10
        elif pe > 60:
            score -= 0.10

        debt = c.get("debt_to_equity", 999) or 999
        if debt < 0.5:
            score += 0.05

        margin = c.get("profit_margin", 0) or 0
        if margin > 0.15:
            score += 0.10

        c["rule_score"] = round(score, 3)
        return c

    def _ai_analyze(self, ticker: str, data: dict, portfolio) -> dict:
        """Call Claude API for qualitative analysis."""
        if not self.client:
            return self._fallback_analyze(ticker, data, portfolio)

        prompt = f"""Analyze this stock for a paper trading decision.

Ticker: {ticker}
Sector: {data.get('sector', 'Unknown')}

Price & Technicals:
- Last price: ${data.get('last', 0):.2f}
- SMA20: ${data.get('sma20', 0):.2f} | SMA50: ${data.get('sma50', 0):.2f} | SMA200: ${data.get('sma200', 0):.2f}
- RSI(14): {data.get('rsi', 50):.1f}
- Volume ratio vs 20d avg: {data.get('vol_ratio', 1):.2f}x
- % from 52w high: {data.get('pct_from_high', 0):.1%}
- % from 52w low: {data.get('pct_from_low', 0):.1%}

Momentum:
- 1 week: {data.get('mom_1w', 0):.1%}
- 1 month: {data.get('mom_1m', 0):.1%}
- 3 months: {data.get('mom_3m', 0):.1%}
- 6 months: {data.get('mom_6m', 0):.1%}

Fundamentals:
- P/E ratio: {data.get('pe', 'N/A')}
- ROE: {data.get('roe', 'N/A')}
- Revenue growth: {data.get('revenue_growth', 'N/A')}
- Profit margin: {data.get('profit_margin', 'N/A')}
- Debt/Equity: {data.get('debt_to_equity', 'N/A')}

Quantitative pre-score: {data.get('rule_score', 0):.2f}

Current portfolio context:
{json.dumps(portfolio.summary(), indent=2)}

Respond with JSON only:
{{
  "ticker": "{ticker}",
  "action": "BUY|SELL|HOLD|WATCH",
  "confidence": 0.0-1.0,
  "price": {data.get('last', 0):.2f},
  "reason": "one sentence explanation",
  "moat_assessment": "brief moat/business quality note",
  "risk": "main risk to this thesis",
  "suggested_position_pct": 0-15
}}"""

        try:
            resp = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            text = resp.content[0].text.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)
            result["analyzed_at"] = datetime.now().isoformat()
            return result
        except Exception as e:
            log.error(f"AI analysis failed for {ticker}: {e}")
            return {
                "ticker": ticker,
                "action": "WATCH",
                "confidence": 0.0,
                "price": data.get("last", 0),
                "reason": f"Analysis error: {str(e)[:50]}",
                "moat_assessment": "N/A",
                "risk": "N/A",
                "suggested_position_pct": 0,
                "analyzed_at": datetime.now().isoformat(),
            }

    def _fallback_analyze(self, ticker: str, data: dict, portfolio) -> dict:
        """Deterministic fallback so the agent can still run without an LLM key."""
        score = float(data.get("rule_score", 0))
        held = ticker in [p["ticker"] for p in portfolio.positions()]

        if held and score < 0.15:
            action = "SELL"
            confidence = min(0.85, max(0.70, 0.70 + abs(score)))
            reason = "Rule score deteriorated while already held; paper risk management says exit."
            suggested_pct = 0
        elif score >= 0.75:
            action = "BUY"
            confidence = min(0.90, score)
            reason = "Strong rule score across trend, momentum, quality, and price strength."
            suggested_pct = min(15, max(5, round(score * 12, 1)))
        elif score >= 0.45:
            action = "WATCH"
            confidence = min(0.69, score)
            reason = "Constructive setup, but not strong enough for a high-confidence alert."
            suggested_pct = 0
        else:
            action = "HOLD" if held else "WATCH"
            confidence = max(0.0, min(0.5, score))
            reason = "Signal is not strong enough to justify action."
            suggested_pct = 0

        return {
            "ticker": ticker,
            "action": action,
            "confidence": round(confidence, 3),
            "price": data.get("last", 0),
            "reason": reason,
            "moat_assessment": "Rule-only mode; add ANTHROPIC_API_KEY for qualitative moat analysis.",
            "risk": "Fallback analysis lacks LLM qualitative review.",
            "suggested_position_pct": suggested_pct,
            "analyzed_at": datetime.now().isoformat(),
        }

    def record_day(self, summary: dict):
        """Store daily outcome for learning."""
        self.history.append({
            "date": datetime.now().date().isoformat(),
            "type": "daily",
            **summary
        })
        self._save_history()

    def save_reflection(self, report: dict):
        reflections = self._load_json(REFLECTIONS_FILE, [])
        reflections.append(report)
        REFLECTIONS_FILE.write_text(json.dumps(reflections, indent=2))

    def history(self) -> list:
        return self.history[-90:]  # Last 90 days

    def maturity_score(self) -> float:
        """
        How mature is the agent? Based on:
        - Days of operation
        - Win rate
        - Sharpe estimate
        - Number of reflections completed
        """
        days = len([h for h in self.history if h.get("type") == "daily"])
        reflections = len(self._load_json(REFLECTIONS_FILE, []))

        if days < 10:
            return 0.0

        recent = [h for h in self.history[-20:] if h.get("type") == "daily"]
        win_rate = sum(1 for h in recent if h.get("day_pnl", 0) > 0) / max(len(recent), 1)

        portfolio_alpha = 0
        for h in reversed(self.history):
            if h.get("type") == "daily" and h.get("alpha") is not None:
                portfolio_alpha = h.get("alpha", 0)
                break

        # Score components
        days_score = min(days / 60, 1.0)           # Max at 60 days
        win_score = max(0, (win_rate - 0.40) / 0.30)  # Max at 70% win rate
        reflect_score = min(reflections / 8, 1.0)   # Max at 8 weekly reflections
        alpha_score = min(max(portfolio_alpha / 0.10, 0), 1.0)  # Max at +10% alpha

        maturity = (days_score * 0.30 + win_score * 0.30 + reflect_score * 0.20 + alpha_score * 0.20)
        return round(maturity, 3)

    def _load_history(self):
        self.history = self._load_json(HISTORY_FILE, [])

    def _save_history(self):
        HISTORY_FILE.parent.mkdir(exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(self.history, indent=2))

    def _load_json(self, path: Path, default):
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
