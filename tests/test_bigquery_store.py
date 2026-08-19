from datetime import datetime, timezone

import pandas as pd
import pytest

from bigquery_store import load_snapshot, table_id


class FakeRows:
    def to_dataframe(self, *, create_bqstorage_client):
        assert create_bqstorage_client is False
        return pd.DataFrame(
            [
                {
                    "number": "INC001",
                    "assignment_group": "Service Desk",
                    "sys_created_on": "2026-08-01 10:00:00+00:00",
                    "business_service": "Accounts",
                    "state": "Closed",
                    "active": False,
                }
            ]
        )


class FakeClient:
    table = type(
        "Table",
        (),
        {"modified": datetime(2026, 8, 2, tzinfo=timezone.utc), "num_rows": 1},
    )()

    def get_table(self, target):
        assert target == "ccs-data.ccs_analytics.incidents"
        return self.table

    def list_rows(self, resource):
        assert resource is self.table
        return FakeRows()


def test_table_id_validates_each_component():
    assert table_id("ccs-data", "ccs_analytics", "incidents") == "ccs-data.ccs_analytics.incidents"
    with pytest.raises(ValueError, match="BQ_DATASET"):
        table_id("ccs-data", "not-valid!", "incidents")


def test_load_snapshot_normalizes_rows_and_returns_metadata():
    frame, info = load_snapshot(
        "ccs-data", "ccs_analytics", "incidents", client=FakeClient()
    )
    assert frame["number"].tolist() == ["INC001"]
    assert str(frame["sys_created_on"].dtype) == "datetime64[ns]"
    assert info.rows == 1
    assert info.modified == datetime(2026, 8, 2, tzinfo=timezone.utc)
