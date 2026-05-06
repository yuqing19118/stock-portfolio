"""
WeeklyReflection — the agent writes a structured self-critique every Friday.
Uses Claude API to reason about its own performance and adapt its strategy.
"""

import json
import os
import logging
from datetime import datetime
import anthropic

log = logging.getLogger("Reflection")

REFLECTION_PROMPT = """You are BuffetBot, an AI investment research agent. You have just completed another week of paper trading.

Here is your performance data for this week:

Weekly stats:
{stats}

Trade history this week:
{trades}

Daily performance log (last 30 days):
{history}

Write a structured weekly self-reflection. Be honest and self-critical. Think like Charlie Munger — invert the problem, look for your own errors.

Respond with JSON only:
{{
  "week_ending": "{date}",
  "headline": "one-line summary of the week",
  "what_worked": "2-3 sentences on what went well and why",
  "what_failed": "2-3 sentences on mistakes, missed signals, or bad reasoning",
  "strategy_adjustment": "specific change to make next week",
  "market_observations": "broader market patterns noticed this week",
  "buffett_principle_applied": "which Buffett/Munger principle was most relevant this week",
  "confidence_in_strategy": 0.0-1.0,
  "ready_to_guide_user": true/false,
  "readiness_reasoning": "why you are or are not ready to guide real trades"
}}"""


class WeeklyReflection:

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else None
        if not self.client:
            log.warning("ANTHROPIC_API_KEY not set — weekly reflection will use fallback template")

    def generate(self, history: list, weekly_stats: dict) -> dict:
        """Generate a weekly reflection using Claude."""
        log.info("Generating weekly self-reflection...")
        if not self.client:
            return self._fallback_reflection(history, weekly_stats)

        # Pull this week's trades from history
        recent_trades = [h for h in history if h.get("type") == "daily"][-7:]

        prompt = REFLECTION_PROMPT.format(
            stats=json.dumps(weekly_stats, indent=2),
            trades=json.dumps(recent_trades, indent=2),
            history=json.dumps(history[-30:], indent=2),
            date=datetime.now().date().isoformat(),
        )

        try:
            resp = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}]
            )
            text = resp.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)
            log.info(f"Reflection: {result.get('headline', '—')}")
            return result
        except Exception as e:
            log.error(f"Reflection generation failed: {e}")
            return {
                "week_ending": datetime.now().date().isoformat(),
                "headline": "Reflection unavailable this week",
                "error": str(e),
                "ready_to_guide_user": False,
            }

    def _fallback_reflection(self, history: list, weekly_stats: dict) -> dict:
        alpha = weekly_stats.get("alpha")
        alpha_text = "unknown" if alpha is None else f"{alpha:+.2%}"
        total_return = weekly_stats.get("total_return", 0)
        ready = (
            weekly_stats.get("total_trades", 0) >= 20
            and weekly_stats.get("win_rate", 0) >= 0.55
            and alpha is not None
            and alpha > 0
            and total_return > 0
        )
        return {
            "week_ending": datetime.now().date().isoformat(),
            "headline": f"Rule-only reflection: alpha vs benchmark is {alpha_text}",
            "what_worked": "The agent preserved a measurable record of decisions, NAV, and benchmark-relative performance.",
            "what_failed": "No LLM key is configured, so qualitative self-critique and moat analysis are limited.",
            "strategy_adjustment": "Keep paper trading, require positive alpha and enough closed trades before sending stronger trade guidance.",
            "market_observations": "Benchmark comparison is active; judge the agent by alpha, not just absolute returns.",
            "buffett_principle_applied": "Circle of competence: do not overstate confidence when the evidence base is thin.",
            "confidence_in_strategy": 0.35,
            "ready_to_guide_user": ready,
            "readiness_reasoning": "Fallback mode requires more evidence before real-money guidance." if not ready else "Paper record is positive, but user must still make final decisions.",
        }
