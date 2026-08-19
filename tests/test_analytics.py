import pandas as pd

from analytics import filter_incidents, monthly_counts, normalize_incidents, resolved_mask


def sample():
    return normalize_incidents([
        {"number": "INC1", "sys_created_on": "2025-01-01 10:00:00", "business_service": "Email"},
        {"number": "INC2", "sys_created_on": "2025-03-31 23:00:00", "business_service": "Accounts"},
        {"number": "INC2", "sys_created_on": "2025-03-31 23:00:00", "business_service": "Accounts"},
    ])


def test_normalize_deduplicates_and_parses_dates():
    frame = sample()
    assert len(frame) == 2
    assert pd.api.types.is_datetime64_ns_dtype(frame["sys_created_on"])


def test_date_filter_is_inclusive():
    frame = filter_incidents(sample(), "2025-03-31", "2025-03-31", ["Accounts"])
    assert frame["number"].tolist() == ["INC2"]


def test_monthly_counts_includes_empty_months():
    result = monthly_counts(sample())
    assert result["incidents"].tolist() == [1, 0, 1]


def test_resolved_mask_counts_resolved_and_closed_states():
    frame = normalize_incidents([
        {"number": "INC1", "sys_created_on": "2025-01-01", "state": "Resolved"},
        {"number": "INC2", "sys_created_on": "2025-01-02", "state": "Closed"},
        {"number": "INC3", "sys_created_on": "2025-01-03", "state": "In Progress"},
    ])
    assert resolved_mask(frame).tolist() == [False, True, True]
