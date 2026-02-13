import csv
import logging
import os
from dataclasses import dataclass
from typing import Iterable

import requests


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


TITLE_KEYWORDS = (
    "engineer",
    "developer",
    "programmer",
    "architect",
    "scientist",
    "analyst",
    "devops",
    "sre",
    "machine learning",
    "ml",
    "data",
    "security",
    "platform",
    "infrastructure",
)

ASHBY_ENDPOINT_PATHS = (
    "/api/non-user-graphql?op=apiJobsBoardWithTeams",
    "/api/non-user-graphql?op=apiJobsBoard",
)


@dataclass
class Job:
    company: str
    title: str
    location: str
    url: str



def normalize_base_url(url: str) -> str:
    return url.rstrip("/")



def load_companies(path: str = "companies.csv") -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    required_cols = {"company", "ashby_base_url"}
    missing = required_cols - set(rows[0].keys() if rows else [])
    if missing:
        raise ValueError(f"Missing required columns in companies.csv: {sorted(missing)}")

    return rows



def ashby_payload(base_url: str) -> dict:
    return {
        "operationName": "apiJobsBoardWithTeams",
        "variables": {"organizationHostedJobsPageName": base_url.rsplit("/", 1)[-1]},
        "query": "query apiJobsBoardWithTeams($organizationHostedJobsPageName: String!) {"
        "\n  jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {"
        "\n    teams {"
        "\n      id"
        "\n      name"
        "\n      parentTeamId"
        "\n      jobs {"
        "\n        id"
        "\n        title"
        "\n        location"
        "\n        secondaryLocations"
        "\n        workplaceType"
        "\n        employmentType"
        "\n        isListed"
        "\n      }"
        "\n    }"
        "\n  }"
        "\n}",
    }



def fetch_from_endpoint(base_url: str, endpoint_path: str, timeout: int = 25) -> tuple[list[dict], dict[str, str]]:
    endpoint = f"{normalize_base_url(base_url)}{endpoint_path}"
    payload = ashby_payload(base_url)

    response = requests.post(
        endpoint,
        json=payload,
        timeout=timeout,
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    data = response.json()

    teams = (
        data.get("data", {})
        .get("jobBoard", {})
        .get("teams", [])
    )

    team_by_id = {team.get("id"): team.get("name", "") for team in teams}

    jobs: list[dict] = []
    for team in teams:
        for raw_job in team.get("jobs", []):
            if raw_job.get("isListed") is False:
                continue
            job = dict(raw_job)
            job["team_name"] = team.get("name", "")
            parent_id = team.get("parentTeamId")
            job["parent_team_name"] = team_by_id.get(parent_id, "")
            jobs.append(job)

    return jobs, {"endpoint": endpoint, "teams": str(len(teams))}



def fetch_jobs_for_company(company: str, ashby_base_url: str) -> list[dict]:
    errors: list[str] = []
    for path in ASHBY_ENDPOINT_PATHS:
        try:
            jobs, meta = fetch_from_endpoint(ashby_base_url, path)
            logging.info(
                "Fetched %s jobs for %s using %s (teams=%s)",
                len(jobs),
                company,
                meta["endpoint"],
                meta["teams"],
            )
            return jobs
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {exc}")
            logging.warning("Failed endpoint for %s -> %s", company, errors[-1])

    logging.error("All Ashby endpoints failed for %s (%s): %s", company, ashby_base_url, " | ".join(errors))
    return []



def title_matches_keywords(title: str, keywords: Iterable[str] = TITLE_KEYWORDS) -> bool:
    normalized_title = (title or "").lower()
    return any(keyword in normalized_title for keyword in keywords)



def is_technical_job(job: dict) -> bool:
    return title_matches_keywords(job.get("title", ""))



def format_location(job: dict) -> str:
    location = (job.get("location") or "").strip()
    workplace = (job.get("workplaceType") or "").strip()

    if workplace and workplace.lower() == "remote":
        return "Remote"
    if location:
        return location
    if workplace:
        return workplace
    return "Location not specified"



def format_job_url(base_url: str, job: dict) -> str:
    job_id = job.get("id")
    if job_id:
        return f"{normalize_base_url(base_url)}/job/{job_id}"
    return normalize_base_url(base_url)



def build_digest(companies: list[dict[str, str]]) -> list[str]:
    sections: list[str] = []

    for row in companies:
        company = row["company"].strip()
        base_url = row["ashby_base_url"].strip()

        if not company or not base_url:
            logging.warning("Skipping invalid company row: %s", row)
            continue

        raw_jobs = fetch_jobs_for_company(company, base_url)
        filtered_jobs = [job for job in raw_jobs if is_technical_job(job)]

        if not filtered_jobs:
            continue

        lines = [f"🏢 {company}"]
        for job in filtered_jobs:
            title = job.get("title", "Untitled role").strip()
            location = format_location(job)
            job_url = format_job_url(base_url, job)
            lines.append(f"• {title} — {location}\n  {job_url}")

        sections.append("\n".join(lines))

    return sections



def chunk_sections_for_telegram(sections: list[str], max_len: int = 3800) -> list[str]:
    if not sections:
        return ["No matching Engineering/Data jobs found today."]

    messages: list[str] = []
    current = "🌅 Daily Engineering/Data Job Digest\n"

    for section in sections:
        candidate = f"{current}\n\n{section}" if current.strip() else section

        if len(candidate) <= max_len:
            current = candidate
            continue

        if current.strip():
            messages.append(current.strip())

        if len(section) > max_len:
            message = section
            while len(message) > max_len:
                split_at = message.rfind("\n", 0, max_len)
                if split_at <= 0:
                    split_at = max_len
                messages.append(message[:split_at].strip())
                message = message[split_at:].strip()
            current = message
        else:
            current = section

    if current.strip():
        messages.append(current.strip())

    return messages



def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=25,
    )
    response.raise_for_status()



def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variables")

    companies = load_companies()
    sections = build_digest(companies)
    messages = chunk_sections_for_telegram(sections)

    for idx, message in enumerate(messages, start=1):
        send_telegram_message(token, chat_id, message)
        logging.info("Sent Telegram message chunk %s/%s", idx, len(messages))


if __name__ == "__main__":
    main()
