"""Ashby public job board client (API-first, structured JSON)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover
    httpx = None

from utils.http import HttpError, request_json


ASHBY_HOST = "jobs.ashbyhq.com"


@dataclass
class Job:
    job_id: str
    title: str
    url: str
    location: str
    team: str | None = None
    posted_at: str | None = None
    raw_category: str | None = None


class AshbyError(RuntimeError):
    pass


class AshbyClient:
    def __init__(self, cache_ttl_seconds: int = 600, min_interval_seconds: float = 1.0) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self.min_interval_seconds = min_interval_seconds
        self._cache: dict[str, tuple[float, list[Job]]] = {}
        self._last_request_at = 0.0
        self._client = httpx.Client(timeout=20, follow_redirects=True) if httpx else None

    def close(self) -> None:
        if self._client:
            self._client.close()

    def normalize_board_url(self, url: str) -> str:
        slug = self.derive_org_slug_from_url(url)
        return f"https://{ASHBY_HOST}/{slug}"

    def derive_org_slug_from_url(self, url: str) -> str:
        if not url:
            raise AshbyError("Ashby URL is empty")

        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.netloc.lower()
        path = parsed.path.strip("/")

        if "ashbyhq.com" not in host:
            raise AshbyError("URL does not look like an Ashby board")

        if not path:
            raise AshbyError("Unable to derive organization slug from URL")

        slug = path.split("/")[0]
        slug = re.sub(r"[^a-zA-Z0-9_-]", "", slug).lower()
        if not slug:
            raise AshbyError("Invalid Ashby org slug")
        return slug

    def fetch_open_jobs(self, org_slug: str | None = None, board_url: str | None = None, bypass_cache: bool = False) -> list[Job]:
        if not org_slug and not board_url:
            raise AshbyError("org_slug or board_url is required")
        slug = org_slug or self.derive_org_slug_from_url(board_url or "")

        if not bypass_cache and slug in self._cache:
            fetched_at, data = self._cache[slug]
            if time.time() - fetched_at < self.cache_ttl_seconds:
                return data

        self._rate_limit_wait()

        # API-first: try public posting JSON endpoints.
        payload = self._fetch_jobs_payload(slug)
        jobs = self._parse_jobs_payload(slug, payload)
        self._cache[slug] = (time.time(), jobs)
        return jobs

    def _rate_limit_wait(self) -> None:
        delta = time.time() - self._last_request_at
        if delta < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - delta)
        self._last_request_at = time.time()

    def _fetch_jobs_payload(self, slug: str) -> Any:
        errors: list[str] = []

        candidates: list[tuple[str, dict[str, Any]]] = [
            (
                "https://jobs.ashbyhq.com/api/non-user-graphql",
                {
                    "method": "POST",
                    "json": {
                        "operationName": "ApiJobBoardWithTeams",
                        "variables": {"organizationHostedJobsPageName": slug},
                        "query": "query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {\n  jobBoard: organization(hostedJobsPageName: $organizationHostedJobsPageName) {\n    name\n    hostedJobsPageName\n    jobs {\n      id\n      title\n      locationName\n      teamName\n      employmentType\n      isListed\n      applyUrl\n      publishedDate\n    }\n  }\n}",
                    },
                },
            ),
            (
                f"https://jobs.ashbyhq.com/api/job-board/{slug}",
                {"method": "GET"},
            ),
        ]

        for url, req in candidates:
            try:
                return request_json(req.get("method", "GET"), url, client=self._client, json=req.get("json"))
            except Exception as exc:
                errors.append(f"{url}: {exc}")

        raise AshbyError(
            "Unable to fetch Ashby jobs from known public JSON endpoints. "
            f"The endpoint may have changed. Details: {' | '.join(errors)}"
        )

    def _parse_jobs_payload(self, slug: str, payload: Any) -> list[Job]:
        jobs_raw: list[dict[str, Any]] = []

        if isinstance(payload, dict):
            if payload.get("data", {}).get("jobBoard", {}).get("jobs"):
                jobs_raw = payload["data"]["jobBoard"]["jobs"]
            elif payload.get("jobs") and isinstance(payload["jobs"], list):
                jobs_raw = payload["jobs"]
            elif payload.get("jobPostings") and isinstance(payload["jobPostings"], list):
                jobs_raw = payload["jobPostings"]

        jobs: list[Job] = []
        for item in jobs_raw:
            job_id = str(item.get("id") or item.get("jobId") or item.get("slug") or "")
            title = item.get("title") or item.get("name")
            if not job_id or not title:
                continue
            apply_url = item.get("applyUrl") or item.get("url") or f"https://{ASHBY_HOST}/{slug}/job/{job_id}"
            jobs.append(
                Job(
                    job_id=job_id,
                    title=title,
                    url=apply_url,
                    location=item.get("locationName") or item.get("location") or "Unknown",
                    team=item.get("teamName") or item.get("department") or item.get("team"),
                    posted_at=item.get("publishedDate") or item.get("postedAt"),
                    raw_category=item.get("employmentType") or item.get("category"),
                )
            )
        return jobs
