"""Business Service Monthly Trends Streamlit dashboard."""

from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import (
    CANONICAL_COLUMNS,
    filter_incidents,
    monthly_counts,
    monthly_service_counts,
    normalize_incidents,
    resolved_mask,
)
from bigquery_store import BigQueryStoreError, SnapshotInfo, load_snapshot
from servicenow import DEFAULT_ENDPOINT, ServiceNowError, fetch_incidents


st.set_page_config(
    page_title="CCS | Business Service Trends",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAVY = "#07111F"
BLUE = "#3B82F6"
CYAN = "#22D3EE"
SLATE = "#A8B3C7"
GRID = "rgba(148, 163, 184, 0.16)"
PALETTE = [CYAN, "#A78BFA", "#FBBF24", "#34D399", "#FB7185", "#60A5FA", "#F97316", "#2DD4BF"]


st.markdown(
    """
    <style>
    .stApp { background: #07111F; color: #E8EEF8; }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #050B14 0%, #0A1728 100%);
        border-right: 1px solid #1C2C42;
    }
    [data-testid="stSidebar"] * { color: #E8EEF8; }
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] [data-baseweb="input"] > div {
        background-color: rgba(255,255,255,.08);
    }
    .block-container { padding-top: 3.25rem; padding-bottom: 3rem; max-width: 1500px; }
    .hero {
        padding: 1.65rem 1.8rem;
        border-radius: 30px;
        background: radial-gradient(circle at 88% 18%, rgba(34,211,238,.23), transparent 26%),
                    linear-gradient(120deg, #0C1B30 0%, #12375F 72%, #0B5368 100%);
        color: white;
        border: 1px solid #21466A;
        box-shadow: 0 18px 42px rgba(0, 0, 0, .30);
        overflow: hidden;
        margin-bottom: 1.15rem;
    }
    .hero-kicker { color: #67E8F9; font-size: .77rem; letter-spacing: .13em; font-weight: 750; }
    .hero h1 { margin: .25rem 0 .25rem; font-size: clamp(1.8rem, 4vw, 2.65rem); line-height: 1.08; }
    .hero p { color: #DCE8F7; margin: 0; font-size: 1.02rem; }
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #101D30, #0D1828);
        border: 1px solid #21324A;
        border-radius: 16px;
        padding: 1rem 1.05rem;
        box-shadow: 0 8px 24px rgba(0, 0, 0, .20);
        min-height: 150px;
    }
    [data-testid="stMetricLabel"] { color: #9AA8BE; }
    [data-testid="stMetricValue"] {
        color: #F8FAFC;
        font-weight: 760;
        width: 100%;
        min-width: 0;
        overflow: visible !important;
    }
    [data-testid="stMetricValue"] > div,
    [data-testid="stMetricValue"] p {
        font-size: clamp(1.55rem, 2.15vw, 2.65rem);
        line-height: 1.05;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: clip !important;
        overflow-wrap: anywhere !important;
        word-break: normal !important;
        max-width: 100% !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4)
    [data-testid="stMetricValue"] > div,
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4)
    [data-testid="stMetricValue"] p {
        font-size: clamp(1.4rem, 1.8vw, 2.2rem);
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: #0D1828;
        border-color: #21324A;
        border-radius: 18px;
        box-shadow: 0 8px 26px rgba(0, 0, 0, .18);
    }
    h1, h2, h3, p, label { color: #E8EEF8; }
    h2, h3 { letter-spacing: -.015em; }
    .section-label { color: #F8FAFC; font-size: 1.08rem; font-weight: 720; margin-bottom: -.3rem; }
    .section-note { color: #91A0B6; font-size: .87rem; margin-bottom: .3rem; }
    .status-chip {
        display: inline-flex; align-items: center; gap: .4rem;
        background: rgba(255,255,255,.12); color: #E6F9FF;
        border: 1px solid rgba(255,255,255,.20); border-radius: 999px;
        padding: .34rem .68rem; font-size: .78rem; margin-top: .85rem;
    }
    .dot { width: .48rem; height: .48rem; border-radius: 50%; background: #22D3EE; display: inline-block; }
    .footer { color: #6F819A; text-align: center; font-size: .78rem; margin-top: 2rem; }
    div[data-testid="stDataFrame"] { border: 1px solid #21324A; border-radius: 12px; overflow: hidden; }
    [data-baseweb="tab-list"] { gap: .4rem; }
    [data-baseweb="tab"] { background: #0D1828; border-radius: 10px 10px 0 0; padding: .55rem 1rem; }
    [data-baseweb="tab"][aria-selected="true"] { background: #14243A; }
    [data-testid="stExpander"] { background: #0D1828; border-color: #21324A; }
    @media (max-width: 900px) {
        [data-testid="stMetric"] { min-height: 125px; }
        [data-testid="stMetricValue"] > div { font-size: 1.55rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name)
    except FileNotFoundError:
        value = None
    if value is None or str(value).strip() == "":
        value = os.environ.get(name, default)
    return str(value).strip()


DATA_CACHE = Path(secret("SN_CACHE_PATH", ".data/servicenow_incidents.parquet"))
DATA_BACKEND = secret("DATA_BACKEND", "local").casefold()
BQ_PROJECT = secret("BQ_PROJECT", secret("GOOGLE_CLOUD_PROJECT"))
BQ_DATASET = secret("BQ_DATASET", "ccs_analytics")
BQ_TABLE = secret("BQ_TABLE", "incidents")


def fetch_from_servicenow(username: str, password: str, endpoint: str) -> pd.DataFrame:
    return normalize_incidents(fetch_incidents(username, password, endpoint=endpoint))


@st.cache_resource(show_spinner=False)
def load_local_cache(path: str, modified_ns: int) -> pd.DataFrame:
    """Load one shared snapshot; modified_ns invalidates it after a refresh."""
    del modified_ns
    frame = pd.read_parquet(path)
    if list(frame.columns) == CANONICAL_COLUMNS and all(
        pd.api.types.is_datetime64_ns_dtype(frame[column])
        for column in ("sys_created_on", "resolved_at", "closed_at")
    ):
        return frame
    return normalize_incidents(frame)


def save_local_cache(frame: pd.DataFrame) -> None:
    """Atomically replace the private local ServiceNow snapshot."""
    DATA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_CACHE.with_suffix(DATA_CACHE.suffix + ".tmp")
    try:
        frame.to_parquet(temporary, index=False)
        temporary.chmod(0o600)
        temporary.replace(DATA_CACHE)
    finally:
        if temporary.exists():
            temporary.unlink()


def cached_incidents() -> pd.DataFrame:
    return load_local_cache(str(DATA_CACHE), DATA_CACHE.stat().st_mtime_ns)


@st.cache_resource(show_spinner=False, ttl=300)
def load_bigquery_cache(
    project: str, dataset: str, table: str
) -> tuple[pd.DataFrame, SnapshotInfo]:
    """Cache the durable snapshot briefly so dashboard reruns stay responsive."""
    return load_snapshot(project, dataset, table)


def source_panel() -> tuple[pd.DataFrame | None, str]:
    st.sidebar.markdown("## CCS Analytics")
    st.sidebar.caption("BUSINESS SERVICE TRENDS")
    st.sidebar.markdown("---")
    if DATA_BACKEND == "bigquery":
        st.sidebar.markdown("### BigQuery")
        if not BQ_PROJECT:
            st.error("BigQuery is selected, but BQ_PROJECT is not configured.")
            return None, "BigQuery • configuration required"
        try:
            with st.spinner("Loading the BigQuery incident snapshot…"):
                frame, info = load_bigquery_cache(BQ_PROJECT, BQ_DATASET, BQ_TABLE)
            if info.modified:
                updated = info.modified.astimezone().replace(tzinfo=None)
                st.sidebar.caption(f"Snapshot updated {updated:%b %d, %Y at %I:%M %p}")
            st.sidebar.caption(f"{info.rows:,} incidents • refreshes automatically")
            return frame, "BigQuery • scheduled snapshot"
        except (BigQueryStoreError, ValueError) as exc:
            st.error(f"BigQuery data could not be loaded: {exc}")
            return None, "BigQuery • unavailable"
    if DATA_BACKEND != "local":
        st.error("DATA_BACKEND must be either 'local' or 'bigquery'.")
        return None, "Data source • configuration required"

    configured = bool(secret("SN_USERNAME") and secret("SN_PASSWORD"))
    if not configured:
        st.error(
            "ServiceNow credentials are not configured. Add SN_USERNAME and SN_PASSWORD to "
            ".streamlit/secrets.toml, then restart the application."
        )
        return None, "ServiceNow API • configuration required"

    st.sidebar.markdown("### ServiceNow")
    refresh = st.sidebar.button("↻  Refresh ServiceNow", type="primary", width="stretch")
    cache_available = DATA_CACHE.exists()
    if cache_available:
        updated = datetime.fromtimestamp(DATA_CACHE.stat().st_mtime)
        st.sidebar.caption(f"Snapshot updated {updated:%b %d, %Y at %I:%M %p}")
    else:
        st.sidebar.caption("First import takes about 2 minutes")

    if cache_available and not refresh:
        try:
            return cached_incidents(), "ServiceNow API • live snapshot"
        except Exception:
            st.warning("The local snapshot could not be read and will be rebuilt from ServiceNow.")

    try:
        with st.spinner("Refreshing the ServiceNow snapshot • this can take about 2 minutes…"):
            frame = fetch_from_servicenow(
                secret("SN_USERNAME"),
                secret("SN_PASSWORD"),
                secret("SN_ENDPOINT", DEFAULT_ENDPOINT),
            )
            save_local_cache(frame)
            load_local_cache.clear()
            st.toast(f"ServiceNow snapshot updated • {len(frame):,} incidents")
            return frame, "ServiceNow API • refreshed"
    except (ServiceNowError, ValueError, OSError) as exc:
        if DATA_CACHE.exists():
            st.warning("Refresh failed; the last successful ServiceNow snapshot remains in use.")
            return cached_incidents(), "ServiceNow API • previous snapshot"
        st.error(f"ServiceNow data could not be loaded: {exc}")
        return None, "ServiceNow API • unavailable"


def style_figure(figure: go.Figure, *, height: int = 355) -> go.Figure:
    figure.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, ui-sans-serif, system-ui", color=SLATE, size=12),
        hoverlabel=dict(bgcolor=NAVY, font_color="white", bordercolor=NAVY),
        margin=dict(l=10, r=10, t=18, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    figure.update_xaxes(showgrid=False, linecolor=GRID, tickfont_color=SLATE)
    figure.update_yaxes(gridcolor=GRID, zeroline=False, tickfont_color=SLATE)
    return figure


def title_block(title: str, note: str) -> None:
    st.markdown(f'<div class="section-label">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="section-note">{note}</div>', unsafe_allow_html=True)


incidents, source_name = source_panel()
st.markdown(
    f"""
    <div class="hero">
      <div class="hero-kicker">TORONTO METROPOLITAN UNIVERSITY • CCS</div>
      <h1>Business Service Trends</h1>
      <p>A clear view of incident demand, service patterns, and operational workload.</p>
      <div class="status-chip"><span class="dot"></span>{source_name}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if incidents is None or incidents.empty:
    st.stop()

minimum = incidents["sys_created_on"].min().date()
maximum = incidents["sys_created_on"].max().date()
st.sidebar.markdown("---")
st.sidebar.markdown("### Filters")
date_range = st.sidebar.date_input(
    "Created date",
    value=(minimum, maximum),
    min_value=minimum,
    max_value=max(maximum, date.today()),
)
all_services = sorted(incidents["business_service"].unique().tolist())
default_services = incidents["business_service"].value_counts().head(10).index.tolist()
services = st.sidebar.multiselect("Business Service", all_services, default=default_services)
st.sidebar.caption("Showing the 10 highest-volume services by default • all services remain available")
all_groups = sorted(incidents["assignment_group"].unique().tolist())
groups = st.sidebar.multiselect("Assignment group", all_groups, default=all_groups)
st.sidebar.markdown("---")
st.sidebar.caption(f"Latest incident in dataset  •  {maximum:%b %d, %Y}")

if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
    st.warning("Choose both a start date and an end date.")
    st.stop()
if not services or not groups:
    st.warning("Select at least one Business Service and one assignment group.")
    st.stop()

filtered = filter_incidents(incidents, date_range[0], date_range[1], services)
if len(groups) != len(all_groups):
    filtered = filtered[filtered["assignment_group"].isin(groups)].copy()
if filtered.empty:
    st.warning("No incidents match the selected date, service, and assignment-group filters.")
    st.stop()

period_start, period_end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
period_days = (period_end - period_start).days + 1
previous_end = period_start - pd.offsets.Day(1)
previous_start = previous_end - pd.offsets.Day(period_days - 1)
previous = filter_incidents(incidents, previous_start, previous_end, services)
if len(groups) != len(all_groups):
    previous = previous[previous["assignment_group"].isin(groups)]
delta = len(filtered) - len(previous) if not previous.empty else None
monthly = monthly_counts(filtered)
top_service = filtered["business_service"].value_counts().index[0]
peak_row = monthly.loc[monthly["incidents"].idxmax()]
resolved_count = int(resolved_mask(filtered).sum())
resolution_rate = resolved_count / len(filtered)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns([1, 1, 1, 1.35, 1])
kpi1.metric("Total incidents", f"{len(filtered):,}", delta=delta, help="Change versus the preceding period of equal length")
kpi2.metric("Resolved incidents", f"{resolved_count:,}")
kpi3.metric("Resolution rate", f"{resolution_rate:.1%}")
kpi4.metric("Top Business Service", top_service)
kpi5.metric("Peak month", pd.Timestamp(peak_row["month"]).strftime("%b %Y"), f"{int(peak_row['incidents']):,} incidents")

def render_overview() -> None:
    left, right = st.columns([1.35, 1])
    with left:
        with st.container(border=True):
            title_block("Monthly incident volume", "All selected services • automatically expands as new months arrive")
            chart_data = monthly.assign(year=monthly["month"].dt.year.astype(str))
            volume = px.bar(
                chart_data, x="month", y="incidents", color="year", color_discrete_sequence=PALETTE,
                labels={"month": "", "incidents": "Incidents", "year": "Year"},
            )
            volume.update_traces(marker_line_width=0, hovertemplate="%{x|%B %Y}<br><b>%{y:,} incidents</b><extra></extra>")
            st.plotly_chart(style_figure(volume), width="stretch", config={"displayModeBar": False})
    with right:
        with st.container(border=True):
            title_block("Incident status", "Current state of incidents in the selected period")
            status_totals = filtered.groupby("state", as_index=False).size().rename(columns={"size": "incidents"})
            donut = px.pie(status_totals, names="state", values="incidents", hole=.68, color_discrete_sequence=PALETTE)
            donut.update_traces(
                textposition="none", domain=dict(x=[0.08, 0.92], y=[0.28, 1]),
                hovertemplate="%{label}<br><b>%{value:,}</b> • %{percent}<extra></extra>",
            )
            donut.add_annotation(
                x=0.5, y=0.64, xref="paper", yref="paper",
                text=f"<b>{resolved_count:,}</b><br><span style='font-size:11px'>resolved</span>",
                showarrow=False, font_color="#F8FAFC",
            )
            donut = style_figure(donut, height=420)
            donut.update_layout(
                legend=dict(
                    orientation="h", yanchor="top", y=0.14, xanchor="center", x=0.5,
                    font=dict(size=11),
                ),
                margin=dict(l=10, r=10, t=18, b=18),
            )
            st.plotly_chart(donut, width="stretch", config={"displayModeBar": False})

    with st.container(border=True):
        title_block("Monthly mix by Business Service", "Stacked colors show each service; the tallest bar is the month with the most incidents")
        timeline = monthly_service_counts(filtered)
        service_mix = px.bar(
            timeline, x="month", y="incidents", color="business_service", barmode="stack",
            color_discrete_sequence=PALETTE,
            labels={"month": "", "incidents": "Incidents", "business_service": "Business Service"},
        )
        service_mix.update_traces(marker_line_width=0, hovertemplate="%{x|%B %Y}<br><b>%{y:,} incidents</b><extra>%{fullData.name}</extra>")
        st.plotly_chart(style_figure(service_mix, height=420), width="stretch", config={"displayModeBar": False})


def render_service_detail() -> None:
    with st.container(border=True):
        title_block("Business Service ranking", "Total incident volume and share of the selected period")
        ranking = (
            filtered.groupby("business_service", as_index=False).size().rename(columns={"size": "incidents"})
            .sort_values("incidents", ascending=False)
        )
        ranking["share"] = ranking["incidents"] / ranking["incidents"].sum()
        bars = px.bar(
            ranking, x="business_service", y="incidents", color="business_service",
            color_discrete_sequence=PALETTE, custom_data=["share"],
            labels={"incidents": "Incidents", "business_service": ""},
        )
        bars.update_traces(marker_line_width=0, hovertemplate="<b>%{x}</b><br>%{y:,} incidents • %{customdata[0]:.1%}<extra></extra>")
        bars.update_layout(showlegend=False)
        bars.update_xaxes(categoryorder="array", categoryarray=ranking["business_service"].tolist(), tickangle=-25)
        st.plotly_chart(style_figure(bars, height=430), width="stretch", config={"displayModeBar": False})

    st.dataframe(
        ranking, hide_index=True, width="stretch",
        column_config={
            "business_service": st.column_config.TextColumn("Business Service"),
            "incidents": st.column_config.NumberColumn("Incidents", format="localized"),
            "share": st.column_config.ProgressColumn("Share", min_value=0, max_value=1, format="percent"),
        },
    )


def render_operations() -> None:
    left, right = st.columns([1.15, 1])
    with left:
        with st.container(border=True):
            title_block("Assignment-group workload", "How selected incidents are distributed across support groups")
            workload = (
                filtered.groupby("assignment_group", as_index=False).size().rename(columns={"size": "incidents"})
                .sort_values("incidents", ascending=True)
            )
            workload_chart = px.bar(
                workload, x="incidents", y="assignment_group", orientation="h", color="assignment_group",
                color_discrete_sequence=PALETTE, labels={"incidents": "Incidents", "assignment_group": ""},
            )
            workload_chart.update_traces(hovertemplate="<b>%{y}</b><br>%{x:,} incidents<extra></extra>")
            workload_chart.update_layout(showlegend=False)
            st.plotly_chart(style_figure(workload_chart), width="stretch", config={"displayModeBar": False})
    with right:
        with st.container(border=True):
            title_block("Data completeness", "Required reporting fields present in the selected incidents")
            quality_rows = pd.DataFrame(
                {
                    "Check": ["Incident number", "Business Service", "Assignment group", "Created date"],
                    "Complete": [
                        filtered["number"].notna().mean(),
                        filtered["business_service"].ne("Unspecified").mean(),
                        filtered["assignment_group"].ne("Unspecified").mean(),
                        filtered["sys_created_on"].notna().mean(),
                    ],
                }
            )
            quality = px.bar(
                quality_rows, x="Complete", y="Check", orientation="h", range_x=[0, 1], color="Check",
                color_discrete_sequence=PALETTE,
            )
            quality.update_xaxes(tickformat=".0%")
            quality.update_traces(hovertemplate="<b>%{y}</b><br>%{x:.1%} complete<extra></extra>")
            quality.update_layout(showlegend=False)
            st.plotly_chart(style_figure(quality), width="stretch", config={"displayModeBar": False})

    with st.expander("View incident records"):
        st.caption(
            "For security and performance, short descriptions are not retrieved. "
            "The table preview is limited to the 1,000 newest matching incidents."
        )
        display = filtered.head(1_000).rename(
            columns={
                "number": "Incident", "assignment_group": "Assignment group",
                "sys_created_on": "Created", "business_service": "Business Service",
                "state": "State", "resolved_at": "Resolved", "closed_at": "Closed", "active": "Active",
            }
        )
        st.dataframe(display, hide_index=True, width="stretch", height=420)
        if st.button("Prepare filtered CSV", help="Builds the export only when requested"):
            export = filtered.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download filtered records", export,
                file_name=f"bst_incidents_{date_range[0]}_{date_range[1]}.csv", mime="text/csv",
                on_click="ignore",
            )


trend_tab, service_tab, operations_tab = st.tabs(
    ["Overview", "Service detail", "Operations"], key="dashboard_tab", on_change="rerun"
)
if trend_tab.open:
    with trend_tab:
        render_overview()
elif service_tab.open:
    with service_tab:
        render_service_detail()
elif operations_tab.open:
    with operations_tab:
        render_operations()

st.markdown(
    '<div class="footer">CCS Business Service Trends • Secure internal reporting • Built with Streamlit</div>',
    unsafe_allow_html=True,
)
