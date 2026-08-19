from pathlib import Path

from streamlit.testing.v1 import AppTest

from analytics import normalize_incidents
from bigquery_store import SnapshotInfo


def test_servicenow_dashboard_renders_from_snapshot(tmp_path):
    cache = tmp_path / "incidents.parquet"
    normalize_incidents(
        [
            {
                "number": "INC001",
                "assignment_group": "Service Desk",
                "sys_created_on": "2025-01-05 10:00:00",
                "business_service": "Two Factor Authentication (2FA)",
                "state": "Closed",
                "resolved_at": "2025-01-06 10:00:00",
                "closed_at": "2025-01-07 10:00:00",
                "active": "false",
            },
            {
                "number": "INC002",
                "assignment_group": "Service Desk",
                "sys_created_on": "2025-02-05 10:00:00",
                "business_service": "Two Factor Authentication (2FA)",
                "state": "Resolved",
                "resolved_at": "2025-02-06 10:00:00",
                "active": "false",
            },
            {
                "number": "INC003",
                "assignment_group": "Applications",
                "sys_created_on": "2025-03-05 10:00:00",
                "business_service": "Learning Systems",
                "state": "In Progress",
                "active": "true",
            },
        ]
    ).to_parquet(cache, index=False)

    app = AppTest.from_file(Path(__file__).parents[1] / "app.py", default_timeout=30)
    app.secrets = {
        "SN_USERNAME": "test-user",
        "SN_PASSWORD": "test-password",
        "SN_ENDPOINT": "https://help.example/api/now/table/incident",
        "SN_CACHE_PATH": str(cache),
    }
    app.run()

    assert not app.exception
    assert len(app.radio) == 0
    assert len(app.get("file_uploader")) == 0
    assert [metric.label for metric in app.metric] == [
        "Total incidents",
        "Resolved incidents",
        "Resolution rate",
        "Top Business Service",
        "Peak month",
    ]
    assert app.metric[3].value == "Two Factor Authentication (2FA)"
    assert [tab.label for tab in app.tabs] == ["Overview", "Service detail", "Operations"]
    assert len(app.get("plotly_chart")) == 6

    prepare = next(button for button in app.button if button.label == "Prepare filtered CSV")
    prepare.click().run()
    assert not app.exception
    assert len(app.get("download_button")) == 1


def test_missing_credentials_stops_before_dashboard(tmp_path):
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py", default_timeout=30)
    app.secrets = {
        "SN_USERNAME": "",
        "SN_PASSWORD": "",
        "SN_ENDPOINT": "",
        "SN_CACHE_PATH": str(tmp_path / "missing.parquet"),
    }
    app.run()

    assert not app.exception
    assert app.error
    assert "credentials are not configured" in app.error[0].value
    assert len(app.metric) == 0


def test_bigquery_backend_does_not_require_servicenow_credentials(monkeypatch):
    frame = normalize_incidents(
        [
            {
                "number": "INC100",
                "assignment_group": "Service Desk",
                "sys_created_on": "2026-08-01 10:00:00",
                "business_service": "Accounts",
                "state": "Closed",
                "active": "false",
            }
        ]
    )

    monkeypatch.setattr(
        "bigquery_store.load_snapshot",
        lambda project, dataset, table: (frame, SnapshotInfo(modified=None, rows=1)),
    )
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py", default_timeout=30)
    app.secrets = {
        "DATA_BACKEND": "bigquery",
        "BQ_PROJECT": "ccs-data",
        "BQ_DATASET": "ccs_analytics",
        "BQ_TABLE": "incidents",
        "SN_USERNAME": "",
        "SN_PASSWORD": "",
    }
    app.run()

    assert not app.exception
    assert len(app.metric) == 5
    assert app.metric[0].value == "1"
    assert not any(button.label == "↻  Refresh ServiceNow" for button in app.button)
