# BuffetBot — AI Paper Trading Research Agent

> Runs day and night. Learns from the market. Alerts you when it's confident.
> Trained on Buffett & Munger principles. Paper trades only — no real money.

---

## What it does

- **Scans** 70+ stocks every morning at market open using real data (yfinance)
- **Scores** each candidate with 4 strategies: momentum, quality value, earnings drift, mean reversion
- **Reasons** about each signal using Claude AI — thinks like Buffett/Munger
- **Paper trades** with $50k simulated capital by default — tracks P&L, stops, and targets
- **Compares itself to SPY** every day — records benchmark return and alpha
- **Alerts you** via Telegram (or email) with morning signals, midday risk alerts, and EOD summaries
- **Reflects** every Friday — writes a self-critique, adjusts strategy, and only escalates when maturity and alpha are both strong
- **Tracks maturity** — only claims readiness after 60+ days, 70%+ win rate, and 8 weeks of reflection

---

## Setup (5 minutes)

### 1. Install Python dependencies

```bash
cd buffet-agent
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

**Strongly recommended:**
- `ANTHROPIC_API_KEY` — get from [console.anthropic.com](https://console.anthropic.com)

If no Anthropic key is set, BuffetBot still runs in rule-only mode, but its moat analysis and reflections are less intelligent.

**For Telegram alerts (recommended):**
1. Message `@BotFather` on Telegram → `/newbot` → copy the token
2. Message `@userinfobot` on Telegram → copy your Chat ID
3. Paste both into `.env`

### 3. Run the agent

```bash
# Load env and start
source .env && python agent.py

# Or with dotenv:
python -c "from dotenv import load_dotenv; load_dotenv()" && python agent.py
```

### 4. Run 24/7 (keep alive on your machine or server)

**macOS/Linux — using screen:**
```bash
screen -S buffetbot
source .env && python agent.py
# Ctrl+A then D to detach
# screen -r buffetbot to reattach
```

**Linux server — using systemd:**
```bash
# Create /etc/systemd/system/buffetbot.service:
[Unit]
Description=BuffetBot Trading Agent
After=network.target

[Service]
WorkingDirectory=/path/to/buffet-agent
EnvironmentFile=/path/to/buffet-agent/.env
ExecStart=/usr/bin/python3 agent.py
Restart=always

[Install]
WantedBy=multi-user.target

# Then:
sudo systemctl enable buffetbot
sudo systemctl start buffetbot
```

**Cheap cloud server (~$5/mo):**
- DigitalOcean Droplet (1GB RAM is enough)
- Hetzner CX11
- Oracle Cloud Free Tier (completely free)

---

## Phone dashboard with GitHub Pages

The dashboard is a static GitHub Pages site:

- `index.html` is the dashboard UI
- `data/status.json` is the latest paper portfolio status
- `.github/workflows/pages.yml` deploys the site after each push

After creating a GitHub repo, connect and publish:

```bash
git init
git branch -M main
git remote add origin git@github.com:YOUR_USER/YOUR_REPO.git
git add .
git commit -m "Publish BuffetBot dashboard"
git push -u origin main
```

Then enable GitHub Pages in the repo settings:

- Settings → Pages
- Source: GitHub Actions

To update the phone dashboard after the agent writes new status:

```bash
./publish_dashboard.sh
```

Your phone URL will usually be:

```text
https://YOUR_USER.github.io/YOUR_REPO/
```

---

## Schedule

These are Los Angeles local times for U.S. market hours.

| Time (PT) | What happens |
|-----------|-------------|
| 06:35 Mon–Fri | Morning scan — scores all stocks, executes paper trades |
| 09:30 Mon–Fri | Midday check — stop-loss/take-profit monitoring |
| 13:05 Mon–Fri | EOD summary — daily P&L, SPY comparison, portfolio snapshot |
| 13:30 Friday | Weekly reflection — self-critique, strategy adjustment |

### Stock Research Queue rules

The dashboard research queue refreshes from the agent's local status after each run.

A ticker enters the queue when:

- it becomes an active paper holding
- it appears in the top rule-score scan
- it triggers a high-confidence paper BUY/SELL signal
- it needs review because alpha, stop-loss risk, target progress, or thesis quality changed
- it is a cleaner ETF/options expression of a current single-stock thesis

Queue membership is dynamic. A ticker can move up, move down, or leave:

- **Move up:** confidence improves, trend strengthens, thesis is confirmed, or it contributes positive alpha
- **Move down:** confidence weakens, valuation/risk worsens, or market regime shifts against the setup
- **Leave:** stop-loss is hit, confidence falls below 55%, the thesis is invalidated, data quality is poor, or a cleaner ETF/options expression replaces the stock

The queue is not a trade instruction. It means: "research this before considering more risk."

---

## Maturity system

The agent tracks its own readiness to guide real trades:

| Factor | Weight | Max at |
|--------|--------|--------|
| Days of operation | 40% | 60 days |
| Win rate | 40% | 70% win rate |
| Reflections completed | 20% | 8 weeks |

When maturity hits **80%**, you get a special Telegram alert:
> 🎓 BuffetBot — MATURITY THRESHOLD REACHED

This alert is now suppressed unless the paper portfolio is also beating SPY. The goal is not just to make money in a rising market; it has to show alpha.

**Remember:** Even at 80% maturity, these are research signals — not financial advice. You make all final decisions.

---

## File structure

```
buffet-agent/
├── agent.py              ← Main runner (start here)
├── core/
│   ├── scanner.py        ← Pulls market data, computes indicators
│   ├── brain.py          ← AI reasoning engine (Claude API)
│   ├── portfolio.py      ← Paper portfolio tracker
│   └── reflection.py     ← Weekly self-critique generator
├── notifications/
│   └── notifier.py       ← Telegram + email alerts
├── data/                 ← Auto-created, stores state
│   ├── portfolio.json    ← Live portfolio state
│   ├── brain_history.json
│   ├── reflections.json
│   ├── snapshots.json    ← NAV, SPY return, and alpha history
│   └── status.json       ← Local dashboard status for index.html
├── logs/
│   └── agent.log         ← Full activity log
├── .env.example          ← Config template
└── requirements.txt
```

---

## Disclaimer

This is a research and learning tool. It does not give financial advice.
Paper trading results do not guarantee real trading performance.
Always consult a licensed financial advisor before making real investment decisions.
