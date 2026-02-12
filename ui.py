"""UI formatting and keyboard builders."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Add company", callback_data="menu:add")],
            [InlineKeyboardButton("Company list", callback_data="menu:list")],
            [InlineKeyboardButton("Refresh all", callback_data="menu:refresh_all")],
        ]
    )


def companies_keyboard(companies: Iterable[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(c["name"], callback_data=f"company:{c['id']}")] for c in companies]
    rows.append([InlineKeyboardButton("Back", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def company_detail_keyboard(company_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Show Eng", callback_data=f"jobs:{company_id}:eng"),
                InlineKeyboardButton("Show Product", callback_data=f"jobs:{company_id}:product"),
            ],
            [InlineKeyboardButton("Show All", callback_data=f"jobs:{company_id}:all")],
            [InlineKeyboardButton("Refresh", callback_data=f"refresh:{company_id}")],
            [InlineKeyboardButton("Remove", callback_data=f"remove:{company_id}")],
            [InlineKeyboardButton("Back", callback_data="menu:list")],
        ]
    )


def format_company_list(companies: Iterable[dict]) -> str:
    companies = list(companies)
    if not companies:
        return "No companies tracked yet."
    lines = ["Tracked companies:"]
    for c in companies:
        lines.append(f"• {c['name']} — {c['careers_url']}")
    return "\n".join(lines)


def format_jobs(rows: Iterable[dict], title: str = "Jobs") -> str:
    rows = list(rows)
    if not rows:
        return f"{title}\nNo active jobs found."

    lines = [title]
    for r in rows:
        company = r.get("company_name")
        prefix = f"[{company}] " if company else ""
        lines.append(
            f"• {prefix}{r['title']} | {r.get('location') or 'Unknown'} | {r.get('url') or '-'}"
        )
    return "\n".join(lines)


def format_alert(company_name: str, jobs: Iterable[dict]) -> str:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for job in jobs:
        grouped[job["category"]].append(job)

    blocks: list[str] = []
    if grouped.get("eng"):
        lines = [f"New Engineering jobs at {company_name}:"]
        for j in grouped["eng"]:
            lines.append(f"• {j['title']} | {j.get('location','Unknown')} | {j['url']}")
        blocks.append("\n".join(lines))

    if grouped.get("product"):
        lines = [f"New Product jobs at {company_name}:"]
        for j in grouped["product"]:
            lines.append(f"• {j['title']} | {j.get('location','Unknown')} | {j['url']}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)
