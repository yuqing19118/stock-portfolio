"""
Notifier — sends alerts via Telegram (primary) and email (fallback).
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env to activate.
"""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

log = logging.getLogger("Notifier")

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False


class Notifier:

    def __init__(self):
        self.tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.tg_chat = os.getenv("TELEGRAM_CHAT_ID")
        self.email_from = os.getenv("ALERT_EMAIL_FROM")
        self.email_to = os.getenv("ALERT_EMAIL_TO")
        self.smtp_pass = os.getenv("SMTP_PASSWORD")

        if self.tg_token and self.tg_chat:
            log.info("Telegram notifications active")
        elif self.email_to:
            log.info("Email notifications active")
        else:
            log.warning("No notification channel configured — set env vars in .env")

    # ── Public send methods ───────────────────────────────────────

    def send_signals(self, signals: list[dict], portfolio_summary: dict):
        """Morning: high-confidence trade signals."""
        lines = ["*BuffetBot — Morning Signals*", f"NAV: ${portfolio_summary['nav']:,.0f}\n"]
        for s in signals:
            emoji = "🟢" if s["action"] == "BUY" else "🔴" if s["action"] == "SELL" else "🟡"
            lines.append(
                f"{emoji} *{s['ticker']}* — {s['action']} @ ${s['price']:.2f}\n"
                f"Confidence: {s['confidence']:.0%}\n"
                f"Reason: {s['reason']}\n"
                f"Risk: {s.get('risk', 'N/A')}\n"
            )
        self._send("\n".join(lines))

    def send_alerts(self, alerts: list[dict]):
        """Midday: stop-loss or take-profit triggered."""
        lines = ["*BuffetBot — Risk Alert*"]
        for a in alerts:
            t = "STOP LOSS" if a["type"] == "STOP_LOSS" else "TAKE PROFIT"
            emoji = "🛑" if a["type"] == "STOP_LOSS" else "✅"
            lines.append(f"{emoji} {a['ticker']} hit {t} @ ${a['price']:.2f}")
        self._send("\n".join(lines))

    def send_eod(self, summary: dict):
        """End of day summary."""
        pnl = summary["day_pnl"]
        arrow = "▲" if pnl >= 0 else "▼"
        msg = (
            f"*BuffetBot — EOD Summary*\n"
            f"NAV: ${summary['nav']:,.0f}\n"
            f"Day P&L: {arrow} {abs(pnl):.2%}\n"
            f"Total return: {summary['total_return']:+.2%}\n"
            f"Benchmark ({summary.get('benchmark_symbol', 'SPY')}): {summary.get('benchmark_return') or 0:+.2%}\n"
            f"Alpha: {summary.get('alpha') or 0:+.2%}\n"
            f"Beta: {summary.get('portfolio_beta') if summary.get('portfolio_beta') is not None else '—'}\n"
            f"Beta-adjusted alpha: {summary.get('beta_adjusted_alpha') or 0:+.2%}\n"
            f"Positions: {summary['positions']} ({', '.join(summary['tickers'][:5])})"
        )
        self._send(msg)

    def send_weekly_report(self, report: dict, maturity: float):
        """Friday: weekly reflection report."""
        msg = (
            f"*BuffetBot — Weekly Reflection*\n\n"
            f"Week ending: {report.get('week_ending', '—')}\n"
            f"_{report.get('headline', '—')}_\n\n"
            f"✅ *What worked:* {report.get('what_worked', '—')}\n\n"
            f"❌ *What failed:* {report.get('what_failed', '—')}\n\n"
            f"🔄 *Adjustment:* {report.get('strategy_adjustment', '—')}\n\n"
            f"📊 Strategy confidence: {report.get('confidence_in_strategy', 0):.0%}\n"
            f"🧠 Maturity score: {maturity:.0%}"
        )
        self._send(msg)

    def send_mature_alert(self, maturity: float, report: dict):
        """Special alert: agent thinks it's ready to guide real trades."""
        msg = (
            f"🎓 *BuffetBot — MATURITY THRESHOLD REACHED*\n\n"
            f"Maturity score: {maturity:.0%}\n\n"
            f"The agent believes it is ready to guide real trading decisions.\n\n"
            f"Reasoning: {report.get('readiness_reasoning', '—')}\n\n"
            f"⚠️ *Reminder: This is research only. All trades are your decision.*\n"
            f"Review the full weekly report and consult a licensed advisor before acting."
        )
        self._send(msg)

    # ── Transport ─────────────────────────────────────────────────

    def _send(self, message: str):
        sent = False

        if self.tg_token and self.tg_chat and REQUESTS_OK:
            sent = self._send_telegram(message)

        if not sent and self.email_to:
            self._send_email(message)

        if not sent:
            # Fallback: just log it
            log.info(f"[NOTIFICATION]\n{message}")

    def _send_telegram(self, text: str) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            resp = __import__("requests").post(url, json={
                "chat_id": self.tg_chat,
                "text": text,
                "parse_mode": "Markdown",
            }, timeout=10)
            if resp.status_code == 200:
                log.info("Telegram notification sent")
                return True
            else:
                log.warning(f"Telegram failed: {resp.text}")
                return False
        except Exception as e:
            log.error(f"Telegram error: {e}")
            return False

    def _send_email(self, text: str):
        try:
            plain = text.replace("*", "").replace("_", "")
            msg = MIMEText(plain)
            msg["Subject"] = f"BuffetBot Alert — {datetime.now().strftime('%b %d %H:%M')}"
            msg["From"] = self.email_from
            msg["To"] = self.email_to

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(self.email_from, self.smtp_pass)
                s.send_message(msg)
            log.info("Email notification sent")
        except Exception as e:
            log.error(f"Email error: {e}")
