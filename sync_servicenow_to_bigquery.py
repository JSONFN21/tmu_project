"""Fetch ServiceNow incidents and publish a complete BigQuery snapshot."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from analytics import normalize_incidents
from bigquery_store import replace_snapshot
from servicenow import DEFAULT_ENDPOINT, fetch_incidents


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Required environment variable {name} is not set.")
    return value


def source_frame(parquet_path: Path | None) -> pd.DataFrame:
    if parquet_path is not None:
        if not parquet_path.is_file():
            raise SystemExit(f"Parquet snapshot does not exist: {parquet_path}")
        return normalize_incidents(pd.read_parquet(parquet_path))

    username = required_environment("SN_USERNAME")
    password = required_environment("SN_PASSWORD")
    endpoint = os.environ.get("SN_ENDPOINT", DEFAULT_ENDPOINT).strip() or DEFAULT_ENDPOINT
    return normalize_incidents(
        fetch_incidents(
            username,
            password,
            endpoint=endpoint,
            progress=lambda count: print(f"Fetched {count:,} incidents", flush=True),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace the BigQuery incident snapshot from ServiceNow."
    )
    parser.add_argument(
        "--from-parquet",
        type=Path,
        help="Bootstrap BigQuery from an existing normalized Parquet snapshot.",
    )
    args = parser.parse_args()

    project = required_environment("BQ_PROJECT")
    dataset = os.environ.get("BQ_DATASET", "ccs_analytics").strip()
    table = os.environ.get("BQ_TABLE", "incidents").strip()
    frame = source_frame(args.from_parquet)
    info = replace_snapshot(frame, project, dataset, table)
    modified = info.modified.isoformat() if info.modified else "now"
    print(f"Published {info.rows:,} incidents to {project}.{dataset}.{table} at {modified}")


if __name__ == "__main__":
    main()
