"""Interactive Google Ads dashboard (Search + UAC) with relevant charts.

Live data, pick any date range — recommendations always reflect the current state.

Run:  ~/.local/bin/uv run streamlit run streamlit_app.py
"""

from __future__ import annotations

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import analysis_config
from daily_analysis import ACCOUNT, bucket, get_client, rows, usd

BRAND = analysis_config.get("brand", "Google Ads")

st.set_page_config(page_title=f"Google Ads — {BRAND}", layout="wide", page_icon="📊")
EVENTS = ["installs", "signups", "verifs", "dep_att", "deposits"]
BLUE, GREEN, RED, AMBER, GREY = "#1a73e8", "#0f9d58", "#d93025", "#f4b400", "#9aa0a6"


# ------------------------------------------------------------------ data
@st.cache_resource
def client():
    return get_client()


def _between(s: date, e: date) -> str:
    return f"segments.date BETWEEN '{s:%Y-%m-%d}' AND '{e:%Y-%m-%d}'"


@st.cache_data(ttl=600, show_spinner="Loading campaigns…")
def campaigns(channel: str, s: date, e: date):
    return [(x.campaign.id, x.campaign.name, x.campaign.status.name) for x in rows(client(), f"""
        SELECT campaign.id, campaign.name, campaign.status, metrics.cost_micros
        FROM campaign WHERE campaign.advertising_channel_type = '{channel}'
        AND {_between(s, e)} AND metrics.cost_micros > 0 ORDER BY metrics.cost_micros DESC""")]


@st.cache_data(ttl=600, show_spinner="Loading metrics…")
def totals(ids: tuple, s: date, e: date) -> dict:
    idstr = ",".join(map(str, ids))
    t = {"cost": 0.0, "clicks": 0, **{ev: 0.0 for ev in EVENTS}}
    for x in rows(client(), f"""SELECT metrics.cost_micros, metrics.clicks FROM campaign
        WHERE campaign.id IN ({idstr}) AND {_between(s, e)}"""):
        t["cost"] += usd(x.metrics.cost_micros)
        t["clicks"] += x.metrics.clicks
    for x in rows(client(), f"""SELECT segments.conversion_action_name, metrics.all_conversions
        FROM campaign WHERE campaign.id IN ({idstr}) AND {_between(s, e)}
        AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        if b:
            t[b] += x.metrics.all_conversions
    return t


@st.cache_data(ttl=600, show_spinner="Loading daily trend…")
def daily(ids: tuple, s: date, e: date) -> pd.DataFrame:
    idstr = ",".join(map(str, ids))
    day = {}
    for x in rows(client(), f"""SELECT segments.date, metrics.cost_micros FROM campaign
        WHERE campaign.id IN ({idstr}) AND {_between(s, e)} ORDER BY segments.date"""):
        day.setdefault(x.segments.date, {"cost": 0.0, **{ev: 0.0 for ev in EVENTS}})["cost"] += usd(x.metrics.cost_micros)
    for x in rows(client(), f"""SELECT segments.date, segments.conversion_action_name,
        metrics.all_conversions FROM campaign WHERE campaign.id IN ({idstr}) AND {_between(s, e)}
        AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        if b and x.segments.date in day:
            day[x.segments.date][b] += x.metrics.all_conversions
    if not day:
        return pd.DataFrame()
    df = pd.DataFrame([{"date": pd.to_datetime(d), **v} for d, v in sorted(day.items())])
    df["$/Verif"] = (df["cost"] / df["verifs"]).where(df["verifs"] > 0)
    df["$/Signup"] = (df["cost"] / df["signups"]).where(df["signups"] > 0)
    return df


@st.cache_data(ttl=600, show_spinner="Loading keywords…")
def keywords(ids: tuple, s: date, e: date) -> pd.DataFrame:
    idstr = ",".join(map(str, ids))
    kc = {}
    for x in rows(client(), f"""SELECT ad_group_criterion.keyword.text,
        ad_group_criterion.keyword.match_type, ad_group_criterion.status,
        metrics.clicks, metrics.cost_micros FROM keyword_view WHERE campaign.id IN ({idstr})
        AND {_between(s, e)} AND metrics.cost_micros > 0"""):
        k = x.ad_group_criterion.keyword.text
        d = kc.setdefault(k, {"match": x.ad_group_criterion.keyword.match_type.name,
                              "status": x.ad_group_criterion.status.name,
                              "clicks": 0, "cost": 0.0, "signups": 0.0})
        d["clicks"] += x.metrics.clicks
        d["cost"] += usd(x.metrics.cost_micros)
    for x in rows(client(), f"""SELECT ad_group_criterion.keyword.text,
        segments.conversion_action_name, metrics.all_conversions FROM keyword_view
        WHERE campaign.id IN ({idstr}) AND {_between(s, e)} AND metrics.all_conversions > 0"""):
        if bucket(x.segments.conversion_action_name) == "signups":
            k = x.ad_group_criterion.keyword.text
            if k in kc:
                kc[k]["signups"] += x.metrics.all_conversions
    df = pd.DataFrame([{"keyword": k, **v} for k, v in kc.items()])
    if not df.empty:
        df["$/signup"] = (df["cost"] / df["signups"]).where(df["signups"] > 0)
    return df.sort_values("cost", ascending=False) if not df.empty else df


@st.cache_data(ttl=600, show_spinner="Loading creatives…")
def uac_assets(ids: tuple, s: date, e: date) -> pd.DataFrame:
    idstr = ",".join(map(str, ids))
    base = {}
    for x in rows(client(), f"""SELECT asset.resource_name, ad_group_ad_asset_view.field_type,
        asset.text_asset.text, asset.name, asset.youtube_video_asset.youtube_video_id,
        metrics.cost_micros FROM ad_group_ad_asset_view WHERE campaign.id IN ({idstr})
        AND {_between(s, e)} AND metrics.impressions > 0"""):
        rn, a = x.asset.resource_name, x.asset
        d = base.setdefault(rn, {"field": x.ad_group_ad_asset_view.field_type.name,
                                 "creative": (a.text_asset.text or a.name
                                 or a.youtube_video_asset.youtube_video_id or "—")[:44],
                                 "cost": 0.0, "signups": 0.0, "verifs": 0.0})
        d["cost"] += usd(x.metrics.cost_micros)
    for x in rows(client(), f"""SELECT asset.resource_name, segments.conversion_action_name,
        metrics.all_conversions FROM ad_group_ad_asset_view WHERE campaign.id IN ({idstr})
        AND {_between(s, e)} AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        if b in ("signups", "verifs") and x.asset.resource_name in base:
            base[x.asset.resource_name][b] += x.metrics.all_conversions
    df = pd.DataFrame(base.values())
    if not df.empty:
        df["$/verif"] = (df["cost"] / df["verifs"]).where(df["verifs"] > 0)
    return df.sort_values("cost", ascending=False) if not df.empty else df


# ------------------------------------------------------------------ charts
def funnel_chart(t: dict, stages: list[tuple]):
    df = pd.DataFrame([{"stage": lbl, "count": t[k]} for k, lbl in stages])
    top = df["count"].iloc[0] or 1
    df["pct"] = df["count"] / top * 100
    df["label"] = df.apply(lambda r: f"{r['count']:.0f}  ({r['pct']:.0f}%)", axis=1)
    order = [lbl for _, lbl in stages]
    base = alt.Chart(df).encode(
        y=alt.Y("stage:N", sort=order, title=None),
        x=alt.X("count:Q", title=None, axis=None))
    bars = base.mark_bar(cornerRadius=3, color=BLUE)
    text = base.mark_text(align="left", dx=6, color=GREY).encode(text="label:N")
    return (bars + text).properties(height=42 * len(stages))


def daily_cost_eff(df: pd.DataFrame, eff_col: str):
    base = alt.Chart(df).encode(x=alt.X("date:T", title=None))
    bars = base.mark_bar(color=BLUE, opacity=0.35, size=18).encode(
        y=alt.Y("cost:Q", title="Cost $"), tooltip=["date:T", alt.Tooltip("cost:Q", format="$.0f")])
    line = base.mark_line(color=RED, point=True, strokeWidth=2).encode(
        y=alt.Y(f"{eff_col}:Q", title=eff_col),
        tooltip=["date:T", alt.Tooltip(f"{eff_col}:Q", format="$.2f")])
    return alt.layer(bars, line).resolve_scale(y="independent").properties(height=280)


def daily_events(df: pd.DataFrame, cols: list[str]):
    m = df.melt(id_vars="date", value_vars=cols, var_name="event", value_name="count")
    return alt.Chart(m).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("date:T", title=None), y=alt.Y("count:Q", title=None),
        color=alt.Color("event:N", title=None,
                        scale=alt.Scale(range=[GREEN, AMBER, BLUE, RED])),
        tooltip=["date:T", "event:N", "count:Q"]).properties(height=280)


def efficiency_bars(df: pd.DataFrame, val_col: str, n: int = 15):
    d = df[df[val_col].notna()].head(n).copy()
    if d.empty:
        return None
    med = d[val_col].median()
    d["status"] = d[val_col].apply(lambda v: "inefficient" if v > 1.8 * med else "ok")
    label = "creative" if "creative" in d.columns else "keyword"
    return alt.Chart(d).mark_bar(cornerRadius=2).encode(
        y=alt.Y(f"{label}:N", sort="-x", title=None),
        x=alt.X(f"{val_col}:Q", title=val_col),
        color=alt.Color("status:N", scale=alt.Scale(domain=["ok", "inefficient"], range=[GREEN, RED]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[label, alt.Tooltip("cost:Q", format="$.0f"), alt.Tooltip(f"{val_col}:Q", format="$.2f")],
    ).properties(height=28 * len(d))


def kpis(t: dict):
    c = st.columns(6)
    c[0].metric("Cost", f"${t['cost']:,.0f}")
    c[1].metric("Installs", f"{t['installs']:.0f}")
    c[2].metric("Signups", f"{t['signups']:.0f}")
    c[3].metric("Verifs", f"{t['verifs']:.0f}")
    c[4].metric("Deposits", f"{t['deposits']:.0f}")
    c[5].metric("$/Verif", f"${t['cost']/t['verifs']:.2f}" if t["verifs"] else "—")


# ------------------------------------------------------------------ UI
st.title(f"📊 Google Ads — {BRAND}")
st.caption(f"Account {ACCOUNT} · live data · read-only")

with st.sidebar:
    st.header("📅 Date range")
    preset = st.radio("Preset", ["Last 7 days", "Last 14 days", "Last 30 days", "Custom"])
    today = date.today()
    if preset == "Custom":
        s = st.date_input("Start", today - timedelta(days=7))
        e = st.date_input("End", today)
    else:
        s = today - timedelta(days={"Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}[preset])
        e = today
    st.info(f"**{s} → {e}**")
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()

tab_s, tab_u = st.tabs(["🔍 Search (W2A)", "📱 UAC / App"])

with tab_s:
    camps = campaigns("SEARCH", s, e)
    if not camps:
        st.info("No Search campaigns with spend in this range.")
    else:
        ids = tuple(c[0] for c in camps)
        st.subheader("  ·  ".join(f"{n} ({st_})" for _, n, st_ in camps))
        t = totals(ids, s, e)
        kpis(t)
        df = daily(ids, s, e)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Funnel**")
            st.altair_chart(funnel_chart(t, [("clicks", "Clicks"), ("signups", "Signups"),
                                             ("verifs", "Verifs"), ("deposits", "Deposits")]),
                            width="stretch")
        with c2:
            st.markdown("**Cost vs $/Signup by day**")
            if not df.empty:
                st.altair_chart(daily_cost_eff(df, "$/Signup"), width="stretch")
        st.markdown("**Signups & clicks by day**")
        if not df.empty:
            st.altair_chart(daily_events(df, ["signups", "installs"]), width="stretch")
        st.markdown("**Keyword performance by event**")
        kdf = keywords(ids, s, e)
        if not kdf.empty:
            st.dataframe(kdf, width="stretch", hide_index=True,
                         column_config={"cost": st.column_config.NumberColumn(format="$%.2f"),
                                        "$/signup": st.column_config.NumberColumn(format="$%.2f")})

with tab_u:
    camps = campaigns("MULTI_CHANNEL", s, e)
    if not camps:
        st.info("No App campaigns with spend in this range.")
    else:
        ids = tuple(c[0] for c in camps)
        st.subheader("  ·  ".join(f"{n} ({st_})" for _, n, st_ in camps))
        st.caption("Verif (`level_up`) is the optimization event — watch $/Verif.")
        t = totals(ids, s, e)
        kpis(t)
        df = daily(ids, s, e)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Funnel**")
            st.altair_chart(funnel_chart(t, [("installs", "Installs"), ("signups", "Signups"),
                                             ("verifs", "Verifs"), ("deposits", "Deposits")]),
                            width="stretch")
        with c2:
            st.markdown("**Cost vs $/Verif by day**")
            if not df.empty:
                st.altair_chart(daily_cost_eff(df, "$/Verif"), width="stretch")
        st.markdown("**Verifs & signups by day**")
        if not df.empty:
            st.altair_chart(daily_events(df, ["verifs", "signups"]), width="stretch")
        st.markdown("**Creative efficiency — $/Verif (green ok · red inefficient)**")
        adf = uac_assets(ids, s, e)
        ch = efficiency_bars(adf, "$/verif")
        if ch is not None:
            st.altair_chart(ch, width="stretch")
        if not adf.empty:
            with st.expander("All creatives (table)"):
                st.dataframe(adf, width="stretch", hide_index=True,
                             column_config={"cost": st.column_config.NumberColumn(format="$%.0f"),
                                            "$/verif": st.column_config.NumberColumn(format="$%.2f")})
