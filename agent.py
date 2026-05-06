"""
BuffetBot — AI Paper Trading Research Agent
Runs 24/7, learns daily, alerts you when it's confident enough to act.
"""

import schedule
import time
import logging
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from core.scanner import StockScanner
from core.portfolio import PaperPortfolio
from core.brain import AgentBrain
from core.reflection import WeeklyReflection
from notifications.notifier import Notifier

load_dotenv()
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)
Path("reports").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("BuffetBot")


def morning_scan():
    """Runs at market open — scan, score, decide."""
    log.info("=== MORNING SCAN STARTING ===")
    try:
        scanner = StockScanner()
        portfolio = PaperPortfolio()
        brain = AgentBrain()
        notifier = Notifier()

        # 1. Pull fresh market data
        candidates = scanner.scan_universe()
        log.info(f"Scanned {len(candidates)} symbols")

        # 2. Score each candidate
        signals = brain.score_candidates(candidates, portfolio)
        strong = [s for s in signals if abs(s["confidence"]) >= 0.70]

        # 3. Execute paper trades
        for sig in strong:
            if sig["action"] in ("BUY", "SELL"):
                portfolio.execute(sig)
                log.info(f"Paper {sig['action']}: {sig['ticker']} @ ${sig['price']:.2f} | confidence {sig['confidence']:.0%}")

        # 4. Notify if anything is worth telling you
        if strong:
            notifier.send_signals(strong, portfolio.summary())
        else:
            log.info("No high-confidence signals today — holding.")

        # 5. Save daily snapshot
        portfolio.save_snapshot()
        portfolio.write_status()
        log.info("=== MORNING SCAN COMPLETE ===")

    except Exception as e:
        log.error(f"Morning scan failed: {e}", exc_info=True)


def midday_check():
    """Runs midday — check stops, update prices, risk management."""
    log.info("--- Midday check ---")
    try:
        portfolio = PaperPortfolio()
        brain = AgentBrain()
        notifier = Notifier()

        alerts = portfolio.check_stops_and_targets()
        if alerts:
            for a in alerts:
                log.warning(f"ALERT: {a['ticker']} hit {a['type']} at ${a['price']:.2f}")
            notifier.send_alerts(alerts)

        # Update unrealized P&L
        portfolio.refresh_prices()
        portfolio.save_snapshot()
        portfolio.write_status()

    except Exception as e:
        log.error(f"Midday check failed: {e}", exc_info=True)


def evening_review():
    """Runs at close — summarize the day, update learning log."""
    log.info("--- Evening review ---")
    try:
        portfolio = PaperPortfolio()
        brain = AgentBrain()
        notifier = Notifier()

        portfolio.refresh_prices()
        summary = portfolio.daily_summary()
        brain.record_day(summary)

        msg = (
            f"Day complete. NAV: ${summary['nav']:,.0f} | "
            f"Day P&L: {summary['day_pnl']:+.1%} | "
            f"Alpha vs {summary.get('benchmark_symbol', 'SPY')}: {summary.get('alpha') or 0:+.1%} | "
            f"Positions: {summary['positions']}"
        )
        log.info(msg)
        notifier.send_eod(summary)

    except Exception as e:
        log.error(f"Evening review failed: {e}", exc_info=True)


def weekly_reflection():
    """Every Friday — agent writes a self-critique and decides if it's ready to guide you."""
    log.info("=== WEEKLY REFLECTION ===")
    try:
        brain = AgentBrain()
        portfolio = PaperPortfolio()
        notifier = Notifier()
        reflection = WeeklyReflection()

        report = reflection.generate(brain.history(), portfolio.weekly_stats())
        brain.save_reflection(report)

        # The maturity check — is the agent ready to guide real trades?
        maturity = brain.maturity_score()
        log.info(f"Maturity score: {maturity:.0%}")

        notifier.send_weekly_report(report, maturity)

        stats = portfolio.weekly_stats()
        has_positive_alpha = stats.get("alpha") is not None and stats["alpha"] > 0

        if maturity >= 0.80 and has_positive_alpha:
            log.info("MATURITY THRESHOLD REACHED — notifying user")
            notifier.send_mature_alert(maturity, report)
        elif maturity >= 0.80:
            log.info("Maturity threshold reached, but alpha is not positive — suppressing mature alert")

    except Exception as e:
        log.error(f"Weekly reflection failed: {e}", exc_info=True)


def setup_schedule():
    # Los Angeles local market times for U.S. equities:
    # 06:35 PT = 09:35 ET, 09:30 PT = 12:30 ET,
    # 13:05 PT = 16:05 ET, 13:30 PT = 16:30 ET.
    for day_name in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        getattr(schedule.every(), day_name).at("06:35").do(morning_scan)
        getattr(schedule.every(), day_name).at("09:30").do(midday_check)
        getattr(schedule.every(), day_name).at("13:05").do(evening_review)

    schedule.every().friday.at("13:30").do(weekly_reflection)

    log.info("Schedule armed in America/Los_Angeles market time. BuffetBot is running day and night.")


if __name__ == "__main__":
    log.info("BuffetBot starting up...")
    log.info(f"Paper capital: ${os.getenv('PAPER_CAPITAL', '50000')}")

    # Run once immediately on startup
    morning_scan()

    setup_schedule()
    while True:
        schedule.run_pending()
        time.sleep(30)
