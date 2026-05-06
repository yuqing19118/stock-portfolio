"""
Notifier — sends alerts via Telegram, Twilio SMS, email, or logs.
Set notification environment variables in .env to activate.
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
        self.twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.twilio_api_key_sid = os.getenv("TWILIO_API_KEY_SID")
        self.twilio_api_key_secret = os.getenv("TWILIO_API_KEY_SECRET")
        self.twilio_from = os.getenv("TWILIO_FROM_NUMBER")
        self.twilio_to = os.getenv("TWILIO_TO_NUMBER")

        if self.tg_token and self.tg_chat:
            log.info("Telegram notifications active")
        elif self._twilio_ready():
            log.info("Twilio SMS notifications active")
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

    def send_digest(
        self,
        status: dict,
        research_feed: dict = None,
        memory_summary: dict = None,
        dashboard_url: str = None,
    ):
        """Every few hours: dashboard link, prices, paper portfolio, and research context."""
        research_feed = research_feed or {}
        memory_summary = memory_summary or {}
        summary = status.get("summary", {})
        positions = status.get("positions", [])

        lines = [
            "*BuffetBot — 3-Hour Research Digest*",
            f"Dashboard: {dashboard_url or 'local dashboard'}",
            f"Updated: {status.get('updated_at', '—')}",
            "",
            f"Paper NAV: ${summary.get('nav', 0):,.0f}",
            f"Paper return: {self._fmt_pct(summary.get('total_return_pct'))}",
            f"Benchmark ({summary.get('benchmark_symbol', 'SPY')}): {self._fmt_pct(summary.get('benchmark_return_pct'))}",
            f"Alpha: {self._fmt_pct(summary.get('alpha_pct'))}",
            f"Beta: {summary.get('portfolio_beta') if summary.get('portfolio_beta') is not None else '—'}",
            f"Beta-adjusted alpha: {self._fmt_pct(summary.get('beta_adjusted_alpha_pct'))}",
            "",
            "Top paper positions / latest prices:",
        ]

        if positions:
            for p in positions[:12]:
                last_price = p.get("current_price", p.get("last_price", 0)) or 0
                avg_price = p.get("avg_price", p.get("avg_cost", 0)) or 0
                pnl_pct = p.get("unrealized_pnl_pct")
                if pnl_pct is None and avg_price:
                    pnl_pct = (last_price - avg_price) / avg_price
                lines.append(
                    f"- {p.get('ticker', '—')}: last ${last_price:.2f}, "
                    f"avg ${avg_price:.2f}, "
                    f"P&L {self._fmt_pct(pnl_pct)}, "
                    f"stop ${p.get('stop_loss', 0):.2f}, target ${p.get('take_profit', 0):.2f}"
                )
        else:
            lines.append("- No open paper positions.")

        takeaways = research_feed.get("takeaways", [])
        if takeaways:
            lines.extend(["", "Latest research takeaways:"])
            lines.extend(f"- {item}" for item in takeaways[:5])

        risk_flags = research_feed.get("risk_flags", [])
        if risk_flags:
            lines.extend(["", "Do Not Trade Yet / risk flags:"])
            lines.extend(f"- {item}" for item in risk_flags[:5])

        counts = memory_summary.get("counts_by_type", {})
        if counts:
            memory_line = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())[:8])
            lines.extend(["", f"Agent memory counts: {memory_line}"])

        lines.extend([
            "",
            "Research only. No real trade is placed unless you decide and approve it.",
        ])
        self._send("\n".join(lines))

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

        if not sent and self._twilio_ready() and REQUESTS_OK:
            sent = self._send_twilio_sms(message)

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

    def _twilio_ready(self) -> bool:
        has_auth = bool(self.twilio_auth_token) or bool(self.twilio_api_key_sid and self.twilio_api_key_secret)
        return bool(self.twilio_account_sid and has_auth and self.twilio_from and self.twilio_to)

    def _send_twilio_sms(self, text: str) -> bool:
        try:
            plain = self._plain_text(text)
            if len(plain) > 1500:
                plain = plain[:1490] + "\n...[truncated]"

            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_account_sid}/Messages.json"
            if self.twilio_api_key_sid and self.twilio_api_key_secret:
                auth = (self.twilio_api_key_sid, self.twilio_api_key_secret)
            else:
                auth = (self.twilio_account_sid, self.twilio_auth_token)

            resp = __import__("requests").post(url, data={
                "From": self.twilio_from,
                "To": self.twilio_to,
                "Body": plain,
            }, auth=auth, timeout=10)

            if 200 <= resp.status_code < 300:
                log.info("Twilio SMS sent")
                return True

            log.warning(f"Twilio SMS failed: {resp.status_code} {resp.text[:300]}")
            return False
        except Exception as e:
            log.error(f"Twilio SMS error: {e}")
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

    def _plain_text(self, text: str) -> str:
        return (
            text.replace("*", "")
            .replace("_", "")
            .replace("✅", "[OK]")
            .replace("❌", "[FAIL]")
            .replace("🔄", "[ADJUST]")
            .replace("📊", "[STATS]")
            .replace("🧠", "[BRAIN]")
            .replace("🎓", "[MATURE]")
            .replace("⚠️", "[WARN]")
            .replace("🟢", "[BUY]")
            .replace("🔴", "[SELL]")
            .replace("🟡", "[WATCH]")
            .replace("🛑", "[STOP]")
        )

    def _fmt_pct(self, value) -> str:
        if value is None:
            return "—"
        return f"{value:+.2%}"
