"""BigQuery snapshot storage for normalized ServiceNow incidents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

import pandas as pd

from analytics import CANONICAL_COLUMNS, normalize_incidents

try:
    from google.cloud import bigquery
except ModuleNotFoundError:  # Keeps local-only development and unit tests usable.
    bigquery = None  # type: ignore[assignment]


_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
_RESOURCE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")


class BigQueryStoreError(RuntimeError):
    """Raised when the configured BigQuery snapshot cannot be used."""


@dataclass(frozen=True)
class SnapshotInfo:
    """Metadata shown by the dashboard for the current snapshot."""

    modified: datetime | None
    rows: int


def table_id(project: str, dataset: str, table: str) -> str:
    """Build and validate a fully qualified BigQuery table identifier."""
    project = project.strip()
    dataset = dataset.strip()
    table = table.strip()
    if not _PROJECT_ID.fullmatch(project):
        raise ValueError("BQ_PROJECT is not a valid Google Cloud project ID.")
    if not _RESOURCE_ID.fullmatch(dataset):
        raise ValueError("BQ_DATASET is not a valid BigQuery dataset ID.")
    if not _RESOURCE_ID.fullmatch(table):
        raise ValueError("BQ_TABLE is not a valid BigQuery table ID.")
    return f"{project}.{dataset}.{table}"


def _client(project: str) -> Any:
    if bigquery is None:
        raise BigQueryStoreError(
            "BigQuery support is not installed. Install requirements-bigquery.txt."
        )
    return bigquery.Client(project=project)


def load_snapshot(
    project: str,
    dataset: str,
    table: str,
    *,
    client: Any | None = None,
) -> tuple[pd.DataFrame, SnapshotInfo]:
    """Download the current table snapshot without running a billed SQL query."""
    target = table_id(project, dataset, table)
    client = client or _client(project)
    try:
        resource = client.get_table(target)
        rows = client.list_rows(resource)
        frame = rows.to_dataframe(create_bqstorage_client=False)
    except Exception as exc:
        raise BigQueryStoreError(f"Could not read BigQuery table {target}: {exc}") from exc
    return normalize_incidents(frame), SnapshotInfo(
        modified=getattr(resource, "modified", None),
        rows=int(getattr(resource, "num_rows", len(frame))),
    )


def replace_snapshot(
    frame: pd.DataFrame,
    project: str,
    dataset: str,
    table: str,
    *,
    client: Any | None = None,
) -> SnapshotInfo:
    """Replace the incident table after a complete ServiceNow fetch succeeds."""
    target = table_id(project, dataset, table)
    normalized = normalize_incidents(frame)
    if normalized.empty:
        raise ValueError("Refusing to replace BigQuery with an empty incident snapshot.")
    client = client or _client(project)
    if bigquery is None:
        raise BigQueryStoreError("BigQuery support is not installed.")

    upload = normalized[CANONICAL_COLUMNS].copy()
    schema = [
        bigquery.SchemaField("number", "STRING"),
        bigquery.SchemaField("assignment_group", "STRING"),
        bigquery.SchemaField("sys_created_on", "TIMESTAMP"),
        bigquery.SchemaField("business_service", "STRING"),
        bigquery.SchemaField("state", "STRING"),
        bigquery.SchemaField("resolved_at", "TIMESTAMP"),
        bigquery.SchemaField("closed_at", "TIMESTAMP"),
        bigquery.SchemaField("active", "BOOLEAN"),
    ]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="sys_created_on",
        ),
        clustering_fields=["business_service", "assignment_group", "state"],
    )
    try:
        client.load_table_from_dataframe(upload, target, job_config=job_config).result()
        resource = client.get_table(target)
    except Exception as exc:
        raise BigQueryStoreError(f"Could not replace BigQuery table {target}: {exc}") from exc
    return SnapshotInfo(
        modified=getattr(resource, "modified", None),
        rows=int(getattr(resource, "num_rows", len(upload))),
    )
