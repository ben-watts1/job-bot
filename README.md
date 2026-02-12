# Telegram Ashby Job Tracker Bot

Production-ready Telegram bot for BD tracking of companies and monitoring live jobs from **Ashby** job boards using structured JSON endpoints.

## Features
- Track companies and their Ashby careers URLs.
- API-first Ashby retrieval (structured JSON endpoints).
- Filters jobs to only **Engineering** and **Product**.
- Explicitly excludes GTM jobs (Sales/Marketing/CS/RevOps/etc.).
- Inline button UX for add/list/refresh and per-company views.
- Background poller with instant alerts for new/reactivated jobs.
- SQLite persistence (`db.sqlite3`) and configurable environment variables.

## Project layout
- `bot.py` – telegram handlers, wiring, poller
- `db.py` – sqlite schema and CRUD
- `ashby.py` – Ashby API client + URL normalization + cache
- `classify.py` – role classification + GTM exclusion
- `ui.py` – formatting and inline keyboards
- `utils/http.py` – timeout/retry/backoff HTTP helper
- `utils/chunking.py` – telegram-safe chunking/report fallback
- `tests/` – pytest unit tests
- `deploy/bot.service` – systemd service template

## Environment variables
Copy `.env.example` to `.env` and set values:

- `TELEGRAM_BOT_TOKEN=...`
- `ADMIN_USER_ID=...`
- `ALERT_CHAT_ID=...` (optional; can set via command)
- `DB_PATH=./db.sqlite3` (optional)
- `POLL_INTERVAL_SECONDS=300`
- `CACHE_TTL_SECONDS=600`

## Local run
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env
python bot.py
```

## Ubuntu VPS deployment
```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv

cd /opt
sudo mkdir -p job-bot
sudo chown -R $USER:$USER /opt/job-bot
# copy repo files into /opt/job-bot

cd /opt/job-bot
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
# edit .env
```

Run manually once:
```bash
source /opt/job-bot/venv/bin/activate
python /opt/job-bot/bot.py
```

## systemd setup
1. Copy template:
```bash
sudo cp deploy/bot.service /etc/systemd/system/bot.service
```
2. Edit values (`User`, `WorkingDirectory`, `EnvironmentFile`, `ExecStart`) if needed.
3. Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable bot.service
sudo systemctl start bot.service
sudo systemctl status bot.service
```
4. Logs:
```bash
journalctl -u bot.service -f
```

## Bot commands
- `/start` – main menu
- `/help` – command list
- `/add <company_name> <ashby_board_url>`
- `/remove <company_name>`
- `/list`
- `/jobs <company_name> [eng|product|all]`
- `/jobs_all [eng|product|all]`
- `/refresh <company_name>`
- `/refresh_all` (admin only)
- `/set_alert_channel` (admin only; sets current chat as alert destination)

## Setting alert channel
As admin, open the desired Telegram chat and send:
```text
/set_alert_channel
```
This stores chat id in `bot_state` and overrides `ALERT_CHAT_ID`.

## Notes on Ashby API usage
The bot prefers known public structured JSON endpoints and does not scrape HTML job cards. If Ashby changes their endpoint shape, the bot returns a clear error to help you update endpoint configuration.
