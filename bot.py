"""Telegram bot entrypoint for tracking Ashby jobs."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ashby import AshbyClient, AshbyError
from classify import classify_job
from db import Database
from ui import (
    companies_keyboard,
    company_detail_keyboard,
    format_alert,
    format_company_list,
    format_jobs,
    main_menu_keyboard,
)
from utils.chunking import chunk_text, write_report_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADD_COMPANY_INPUT = 1


def get_admin_user_id() -> int:
    return int(os.getenv("ADMIN_USER_ID", "0"))


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == get_admin_user_id())


def parse_company_and_url(payload: str) -> tuple[str, str]:
    parts = payload.strip().split()
    if len(parts) < 2:
        raise ValueError("Usage: <company_name> <ashby_url>")
    url = parts[-1]
    name = " ".join(parts[:-1])
    if not name.strip():
        raise ValueError("Company name is missing")
    return name.strip(), url.strip()


def filter_and_classify_jobs(raw_jobs: list, company_name: str) -> list[dict]:
    normalized: list[dict] = []
    for j in raw_jobs:
        category = classify_job(j.title, j.team)
        if category == "ignore":
            continue
        normalized.append(
            {
                "job_id": j.job_id,
                "title": j.title,
                "url": j.url,
                "location": j.location,
                "team": j.team,
                "posted_at": j.posted_at,
                "raw_category": j.raw_category,
                "category": category,
                "company_name": company_name,
            }
        )
    return normalized


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Welcome to the BD Job Tracker Bot. Use /help or buttons below.",
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "\n".join(
            [
                "/start - open main menu",
                "/help - show commands",
                "/add <company_name> <ashby_board_url>",
                "/remove <company_name>",
                "/list",
                "/jobs <company_name> [eng|product|all]",
                "/jobs_all [eng|product|all]",
                "/refresh <company_name>",
                "/refresh_all (admin)",
                "/set_alert_channel (admin)",
            ]
        )
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    ashby: AshbyClient = context.application.bot_data["ashby"]

    try:
        name, url = parse_company_and_url(" ".join(context.args))
        slug = ashby.derive_org_slug_from_url(url)
        db.add_company(name, ashby.normalize_board_url(url), slug)
    except Exception as exc:
        await update.effective_message.reply_text(f"Failed to add company: {exc}")
        return

    await update.effective_message.reply_text(f"Added/updated {name} ({slug}).")


async def add_company_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Send: Company Name https://jobs.ashbyhq.com/<org>")
    return ADD_COMPANY_INPUT


async def add_company_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db: Database = context.application.bot_data["db"]
    ashby: AshbyClient = context.application.bot_data["ashby"]
    try:
        name, url = parse_company_and_url(update.effective_message.text)
        slug = ashby.derive_org_slug_from_url(url)
        db.add_company(name, ashby.normalize_board_url(url), slug)
        await update.effective_message.reply_text(f"Added {name} ({slug}).", reply_markup=main_menu_keyboard())
    except Exception as exc:
        await update.effective_message.reply_text(f"Could not parse input: {exc}")
    return ConversationHandler.END


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if not context.args:
        await update.effective_message.reply_text("Usage: /remove <company_name>")
        return
    deleted = db.remove_company(" ".join(context.args))
    await update.effective_message.reply_text("Removed." if deleted else "Company not found.")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    companies = db.list_companies()
    await update.effective_message.reply_text(
        format_company_list(companies),
        reply_markup=companies_keyboard(companies),
        disable_web_page_preview=True,
    )


async def run_company_refresh(company: dict, app: Application, bypass_cache: bool = True) -> tuple[list[dict], list[dict]]:
    db: Database = app.bot_data["db"]
    ashby: AshbyClient = app.bot_data["ashby"]
    slug = company["ashby_org_slug"] or ashby.derive_org_slug_from_url(company["careers_url"])
    raw_jobs = ashby.fetch_open_jobs(org_slug=slug, bypass_cache=bypass_cache)
    filtered = filter_and_classify_jobs(raw_jobs, company["name"])
    alerted, _active = db.upsert_jobs(company["id"], filtered)
    return alerted, filtered


async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if not context.args:
        await update.effective_message.reply_text("Usage: /jobs <company_name> [eng|product|all]")
        return

    category = "all"
    if context.args[-1].lower() in ("eng", "product", "all"):
        category = context.args[-1].lower()
        company_name = " ".join(context.args[:-1])
    else:
        company_name = " ".join(context.args)

    company = db.get_company_by_name(company_name)
    if not company:
        await update.effective_message.reply_text("Company not found.")
        return

    rows = db.query_jobs(company_id=company["id"], category=category)
    text = format_jobs(rows, title=f"{company['name']} jobs ({category})")
    for chunk in chunk_text(text):
        await update.effective_message.reply_text(chunk, disable_web_page_preview=True)


async def jobs_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    category = context.args[0].lower() if context.args and context.args[0].lower() in ("eng", "product", "all") else "all"
    rows = db.query_jobs(company_id=None, category=category)
    text = format_jobs(rows, title=f"All companies jobs ({category})")
    chunks = chunk_text(text)

    if len(chunks) > 8:
        path = write_report_file(text, base_name="jobs_all")
        await update.effective_message.reply_document(path.open("rb"), filename=path.name)
        path.unlink(missing_ok=True)
        return

    for chunk in chunks:
        await update.effective_message.reply_text(chunk, disable_web_page_preview=True)


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if not context.args:
        await update.effective_message.reply_text("Usage: /refresh <company_name>")
        return
    company = db.get_company_by_name(" ".join(context.args))
    if not company:
        await update.effective_message.reply_text("Company not found.")
        return

    try:
        alerted, filtered = await run_company_refresh(company, context.application, bypass_cache=True)
        await update.effective_message.reply_text(
            f"Refreshed {company['name']}. Active filtered jobs: {len(filtered)}. New/reactivated: {len(alerted)}"
        )
    except Exception as exc:
        await update.effective_message.reply_text(f"Refresh failed: {exc}")


async def refresh_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.effective_message.reply_text("Admin only.")
        return
    count = await refresh_all_internal(context.application, bypass_cache=True)
    await update.effective_message.reply_text(f"Refresh all done for {count} companies.")


async def set_alert_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.effective_message.reply_text("Admin only.")
        return

    db: Database = context.application.bot_data["db"]
    chat_id = update.effective_chat.id
    db.set_state("alert_chat_id", str(chat_id))
    await update.effective_message.reply_text(f"Alert chat set to {chat_id}")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    query = update.callback_query
    db: Database = context.application.bot_data["db"]
    await query.answer()
    data = query.data or ""

    if data == "menu:home":
        await query.edit_message_text("Main menu", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    if data == "menu:list":
        companies = db.list_companies()
        await query.edit_message_text(format_company_list(companies), reply_markup=companies_keyboard(companies))
        return ConversationHandler.END

    if data == "menu:refresh_all":
        if not is_admin(update):
            await query.edit_message_text("Admin only.")
            return ConversationHandler.END
        count = await refresh_all_internal(context.application, bypass_cache=True)
        await query.edit_message_text(f"Refresh all complete for {count} companies.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    if data == "menu:add":
        return await add_company_prompt(update, context)

    if data.startswith("company:"):
        company_id = int(data.split(":", 1)[1])
        company = db.get_company_by_id(company_id)
        if not company:
            await query.edit_message_text("Company not found")
            return ConversationHandler.END
        await query.edit_message_text(
            f"{company['name']}\n{company['careers_url']}",
            reply_markup=company_detail_keyboard(company_id),
            disable_web_page_preview=True,
        )
        return ConversationHandler.END

    if data.startswith("jobs:"):
        _prefix, cid, category = data.split(":")
        rows = db.query_jobs(company_id=int(cid), category=category)
        text = format_jobs(rows, title=f"Jobs ({category})")
        await query.edit_message_text(chunk_text(text)[0], disable_web_page_preview=True, reply_markup=company_detail_keyboard(int(cid)))
        return ConversationHandler.END

    if data.startswith("refresh:"):
        cid = int(data.split(":", 1)[1])
        company = db.get_company_by_id(cid)
        if not company:
            await query.edit_message_text("Company not found")
            return ConversationHandler.END
        alerted, filtered = await run_company_refresh(company, context.application, bypass_cache=True)
        await query.edit_message_text(
            f"Refreshed {company['name']}. Active filtered jobs: {len(filtered)}. New/reactivated: {len(alerted)}",
            reply_markup=company_detail_keyboard(cid),
        )
        return ConversationHandler.END

    if data.startswith("remove:"):
        cid = int(data.split(":", 1)[1])
        company = db.get_company_by_id(cid)
        if not company:
            await query.edit_message_text("Company not found")
            return ConversationHandler.END
        db.remove_company(company["name"])
        await query.edit_message_text(f"Removed {company['name']}", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    return ConversationHandler.END


async def refresh_all_internal(app: Application, bypass_cache: bool) -> int:
    db: Database = app.bot_data["db"]
    companies = db.list_companies()
    for c in companies:
        try:
            alerted, _filtered = await run_company_refresh(c, app, bypass_cache=bypass_cache)
            if alerted:
                await send_alerts(app, c["name"], alerted)
        except AshbyError as exc:
            logger.warning("Ashby refresh failure for %s: %s", c["name"], exc)
        except Exception as exc:
            logger.exception("Unexpected refresh error for %s: %s", c["name"], exc)
    return len(companies)


async def send_alerts(app: Application, company_name: str, jobs: list[dict]) -> None:
    db: Database = app.bot_data["db"]
    alert_chat = db.get_state("alert_chat_id") or os.getenv("ALERT_CHAT_ID")
    if not alert_chat:
        return

    text = format_alert(company_name, jobs)
    if not text:
        return

    for chunk in chunk_text(text):
        await app.bot.send_message(chat_id=int(alert_chat), text=chunk, disable_web_page_preview=True)


async def poller(context: ContextTypes.DEFAULT_TYPE) -> None:
    await refresh_all_internal(context.application, bypass_cache=False)


def build_app() -> Application:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    db_path = os.getenv("DB_PATH", "./db.sqlite3")
    cache_ttl = int(os.getenv("CACHE_TTL_SECONDS", "600"))

    app = Application.builder().token(token).build()
    app.bot_data["db"] = Database(db_path)
    app.bot_data["ashby"] = AshbyClient(cache_ttl_seconds=cache_ttl)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("jobs", jobs_command))
    app.add_handler(CommandHandler("jobs_all", jobs_all_command))
    app.add_handler(CommandHandler("refresh", refresh_command))
    app.add_handler(CommandHandler("refresh_all", refresh_all_command))
    app.add_handler(CommandHandler("set_alert_channel", set_alert_channel))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_company_prompt, pattern=r"^menu:add$")],
        states={
            ADD_COMPANY_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_company_input)],
        },
        fallbacks=[],
        per_chat=True,
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(on_button))

    poll_seconds = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
    app.job_queue.run_repeating(poller, interval=poll_seconds, first=20)
    return app


def main() -> None:
    app = build_app()
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
