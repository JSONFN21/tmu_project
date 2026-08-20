"""Small, testable ServiceNow Table API client."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_ENDPOINT = "https://help.torontomu.ca/api/now/table/incident"
FIELDS = [
    "sys_created_on",
    "number",
    "assignment_group",
    "business_service",
    "state",
    "resolved_at",
    "closed_at",
    "active",
]


class ServiceNowError(RuntimeError):
    """Raised when ServiceNow returns an unusable response."""


def normalize_endpoint(endpoint: str) -> str:
    """Return only the API endpoint, ignoring query parameters saved in secrets."""
    parts = urlsplit(endpoint.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("ServiceNow endpoint must be a complete HTTP(S) URL.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def fetch_incidents(
    username: str,
    password: str,
    endpoint: str = DEFAULT_ENDPOINT,
    page_size: int = 10_000,
    timeout: int = 60,
    progress: Callable[[int], None] | None = None,
) -> list[dict]:
    """Fetch all incidents using stable, bounded Table API pagination."""
    if not username or not password:
        raise ValueError("ServiceNow username and password are required.")
    if not 1 <= page_size <= 10_000:
        raise ValueError("ServiceNow page size must be between 1 and 10,000.")
    endpoint = normalize_endpoint(endpoint)

    rows: list[dict] = []
    offset = 0
    with requests.Session() as session:
        session.auth = (username, password)
        session.headers.update({"Accept": "application/json"})
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
        while True:
            params = {
                "sysparm_display_value": "true",
                "sysparm_exclude_reference_link": "true",
                "sysparm_fields": ",".join(FIELDS),
                "sysparm_limit": page_size,
                "sysparm_offset": offset,
                "sysparm_query": "ORDERBYsys_created_on^ORDERBYsys_id",
            }
            try:
                response = session.get(endpoint, params=params, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise ServiceNowError(f"ServiceNow request failed: {exc}") from exc
            if not isinstance(payload, dict):
                raise ServiceNowError("ServiceNow response was not a JSON object.")
            if payload.get("error"):
                error = payload["error"]
                message = error.get("message", "Unknown ServiceNow error") if isinstance(error, dict) else str(error)
                raise ServiceNowError(f"ServiceNow returned an error: {message}")
            batch = payload.get("result")
            if not isinstance(batch, list):
                raise ServiceNowError("ServiceNow response did not contain a result list.")
            rows.extend(batch)
            if progress:
                progress(len(rows))
            if len(batch) < page_size:
                break
            offset += len(batch)
    return rows
