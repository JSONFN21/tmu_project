"""Data normalization and aggregation for the BST dashboard."""

from __future__ import annotations

import pandas as pd


CANONICAL_COLUMNS = [
    "number",
    "assignment_group",
    "sys_created_on",
    "business_service",
    "state",
    "resolved_at",
    "closed_at",
    "active",
]


def _display_value(value: object) -> object:
    """Unwrap a ServiceNow reference value when display values are not enabled."""
    if isinstance(value, dict):
        return value.get("display_value") or value.get("value")
    return value


def normalize_incidents(records: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """Return clean incident rows with a parsed creation timestamp."""
    frame = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    frame = frame.rename(columns={
        "Incident number": "number",
        "Assignment group": "assignment_group",
        "Created": "sys_created_on",
        "Created date": "sys_created_on",
        "Business service": "business_service",
        "State": "state",
        "Resolved": "resolved_at",
        "Closed": "closed_at",
        "Active": "active",
    })
    for column in CANONICAL_COLUMNS:
        if column not in frame:
            frame[column] = pd.NA
        if any(isinstance(value, dict) for value in frame[column].array[:1_000]):
            frame[column] = frame[column].map(_display_value)

    frame = frame[CANONICAL_COLUMNS]
    for column in ["sys_created_on", "resolved_at", "closed_at"]:
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True).dt.tz_convert(None)
    frame = frame.dropna(subset=["sys_created_on"])
    frame["business_service"] = (
        frame["business_service"].fillna("Unspecified").replace("", "Unspecified")
    )
    frame["assignment_group"] = (
        frame["assignment_group"].fillna("Unspecified").replace("", "Unspecified")
    )
    frame["state"] = frame["state"].fillna("Unspecified").replace("", "Unspecified")
    active_text = frame["active"].astype("string").str.strip().str.casefold()
    frame["active"] = active_text.eq("true").where(active_text.ne(""), pd.NA).astype("boolean")
    frame = frame.drop_duplicates(subset=["number"], keep="last")
    return frame.sort_values("sys_created_on", ascending=False).reset_index(drop=True)


def resolved_mask(frame: pd.DataFrame) -> pd.Series:
    """Identify incidents whose current state is Resolved or Closed."""
    return frame["state"].astype("string").str.strip().str.casefold().isin({"resolved", "closed"})


def filter_incidents(
    frame: pd.DataFrame,
    start_date: object,
    end_date: object,
    services: list[str] | None = None,
) -> pd.DataFrame:
    """Filter inclusively by calendar dates and optional services."""
    start = pd.Timestamp(start_date)
    end_exclusive = pd.Timestamp(end_date) + pd.offsets.Day(1)
    mask = frame["sys_created_on"].ge(start) & frame["sys_created_on"].lt(end_exclusive)
    if services:
        mask &= frame["business_service"].isin(services)
    return frame.loc[mask].copy()


def monthly_counts(frame: pd.DataFrame) -> pd.DataFrame:
    """Count incidents by month, inserting zeroes for missing months."""
    if frame.empty:
        return pd.DataFrame(columns=["month", "incidents"])
    counts = frame.set_index("sys_created_on").resample("MS").size()
    return counts.rename("incidents").rename_axis("month").reset_index()


def monthly_service_counts(frame: pd.DataFrame) -> pd.DataFrame:
    """Count incidents by month and Business Service."""
    if frame.empty:
        return pd.DataFrame(columns=["month", "business_service", "incidents"])
    grouped = (
        frame.assign(month=frame["sys_created_on"].dt.to_period("M").dt.to_timestamp())
        .groupby(["month", "business_service"], as_index=False)
        .size()
        .rename(columns={"size": "incidents"})
    )
    return grouped
