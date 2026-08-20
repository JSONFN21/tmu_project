import inspect

import pytest

from servicenow import fetch_incidents, normalize_endpoint


def test_normalize_endpoint_removes_embedded_query_parameters():
    endpoint = normalize_endpoint(
        "https://help.example/api/now/table/incident?sysparm_limit=1000000&sysparm_fields=number"
    )
    assert endpoint == "https://help.example/api/now/table/incident"


def test_normalize_endpoint_rejects_relative_urls():
    try:
        normalize_endpoint("/api/now/table/incident")
    except ValueError as exc:
        assert "complete HTTP(S) URL" in str(exc)
    else:
        raise AssertionError("Expected a ValueError")


def test_fetch_incidents_rejects_unsafe_page_size_before_network_call():
    with pytest.raises(ValueError, match="page size"):
        fetch_incidents("user", "password", page_size=0)


def test_fetch_incidents_uses_maximum_safe_page_size_by_default():
    assert inspect.signature(fetch_incidents).parameters["page_size"].default == 10_000
