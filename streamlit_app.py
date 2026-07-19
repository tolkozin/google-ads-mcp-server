"""Google Ads dashboard — Search (W2A) + UAC, with optimization recommendations.

Live read-only data. Pick an account and a date range in the sidebar; every chart
and recommendation is scoped to that slice, so nothing is ever a stale window.

Run:  ~/.local/bin/uv run streamlit run streamlit_app.py
"""

from __future__ import annotations

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st
from google.ads.googleads.client import GoogleAdsClient

import ads_auth
import analysis_config
import creative_bank
from daily_analysis import EVENTS, bucket, is_blocked, neg_reason, usd
from translate import to_en

BRAND = analysis_config.get("brand", "Google Ads")
st.set_page_config(page_title=f"Google Ads — {BRAND}", layout="wide", page_icon="📊")

# --- validated palette (see dataviz reference; light surface #fcfcfb) -----------
S1, S2, S3 = "#2a78d6", "#1baf7a", "#eda100"        # categorical slots 1-3
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"  # status (never used as series)
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
FUNNEL_RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab"]  # ordinal, validated


def styled(chart, height: int = 260):
    """Recessive chrome: hairline grid, muted axes, no view border."""
    return (chart.properties(height=height)
            .configure_axis(grid=True, gridColor=GRID, gridWidth=1, domainColor="#c3c2b7",
                            tickColor="#c3c2b7", labelColor=MUTED, titleColor=MUTED,
                            labelFontSize=11, titleFontSize=11, titleFontWeight="normal")
            .configure_view(strokeWidth=0)
            .configure_legend(labelColor=INK, titleColor=MUTED, labelFontSize=11, titleFontSize=11))


# ============================== data layer ==============================
@st.cache_resource(show_spinner=False)
def client_for(account: str) -> GoogleAdsClient:
    cfg = ads_auth.load_credentials()
    cfg["login_customer_id"] = account  # each account is queried as its own login cid
    return GoogleAdsClient.load_from_dict(cfg, version="v23")


def q(account: str, query: str):
    ga = client_for(account).get_service("GoogleAdsService")
    out = []
    for b in ga.search_stream(customer_id=account, query=query):
        out.extend(b.results)
    return out


@st.cache_data(ttl=1800, show_spinner="Finding accounts…")
def accessible_accounts() -> list[tuple[str, str]]:
    """(id, label) for accounts we can actually query."""
    svc = client_for(ads_auth.get_account()).get_service("CustomerService")
    ids = [rn.split("/")[-1] for rn in svc.list_accessible_customers().resource_names]
    out = []
    for cid in ids:
        try:
            r = q(cid, "SELECT customer.id, customer.descriptive_name, customer.manager FROM customer LIMIT 1")
            c = r[0].customer
            if not c.manager:  # managers hold no campaigns
                out.append((cid, f"{c.descriptive_name or 'Unnamed'} · {cid}"))
        except Exception:
            continue  # deactivated or under a different manager
    return out


def _between(s: date, e: date) -> str:
    return f"segments.date BETWEEN '{s:%Y-%m-%d}' AND '{e:%Y-%m-%d}'"


@st.cache_data(ttl=600, show_spinner="Loading campaigns…")
def campaigns(account: str, channel: str, s: date, e: date):
    return [(x.campaign.id, x.campaign.name, x.campaign.status.name) for x in q(account, f"""
        SELECT campaign.id, campaign.name, campaign.status, metrics.cost_micros
        FROM campaign WHERE campaign.advertising_channel_type = '{channel}'
        AND {_between(s, e)} AND metrics.cost_micros > 0 ORDER BY metrics.cost_micros DESC""")]


@st.cache_data(ttl=600, show_spinner="Loading metrics…")
def totals(account: str, ids: tuple, s: date, e: date) -> dict:
    if not ids:
        return {"cost": 0.0, "clicks": 0, **{ev: 0.0 for ev in EVENTS}}
    idstr = ",".join(map(str, ids))
    t = {"cost": 0.0, "clicks": 0, **{ev: 0.0 for ev in EVENTS}}
    for x in q(account, f"""SELECT metrics.cost_micros, metrics.clicks FROM campaign
        WHERE campaign.id IN ({idstr}) AND {_between(s, e)}"""):
        t["cost"] += usd(x.metrics.cost_micros)
        t["clicks"] += x.metrics.clicks
    for x in q(account, f"""SELECT segments.conversion_action_name, metrics.all_conversions
        FROM campaign WHERE campaign.id IN ({idstr}) AND {_between(s, e)}
        AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        if b:
            t[b] += x.metrics.all_conversions
    return t


@st.cache_data(ttl=600, show_spinner="Loading daily trend…")
def daily(account: str, ids: tuple, s: date, e: date) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    idstr = ",".join(map(str, ids))
    day = {}
    for x in q(account, f"""SELECT segments.date, metrics.cost_micros, metrics.clicks
        FROM campaign WHERE campaign.id IN ({idstr}) AND {_between(s, e)} ORDER BY segments.date"""):
        d = day.setdefault(x.segments.date, {"cost": 0.0, "clicks": 0, **{ev: 0.0 for ev in EVENTS}})
        d["cost"] += usd(x.metrics.cost_micros)
        d["clicks"] += x.metrics.clicks
    for x in q(account, f"""SELECT segments.date, segments.conversion_action_name,
        metrics.all_conversions FROM campaign WHERE campaign.id IN ({idstr}) AND {_between(s, e)}
        AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        if b and x.segments.date in day:
            day[x.segments.date][b] += x.metrics.all_conversions
    if not day:
        return pd.DataFrame()
    df = pd.DataFrame([{"date": pd.to_datetime(d), **v} for d, v in sorted(day.items())])
    for label, col in (("$/Signup", "signups"), ("$/Verif", "verifs"), ("$/Install", "installs")):
        df[label] = (df["cost"] / df[col]).where(df[col] > 0)
    return df


@st.cache_data(ttl=600, show_spinner="Loading campaign split…")
def campaign_split(account: str, ids: tuple, s: date, e: date) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    idstr = ",".join(map(str, ids))
    rowsd = {}
    for x in q(account, f"""SELECT campaign.name, metrics.cost_micros FROM campaign
        WHERE campaign.id IN ({idstr}) AND {_between(s, e)}"""):
        rowsd[x.campaign.name] = rowsd.get(x.campaign.name, 0.0) + usd(x.metrics.cost_micros)
    return pd.DataFrame([{"campaign": k, "cost": v} for k, v in rowsd.items()]).sort_values("cost", ascending=False)


@st.cache_data(ttl=600, show_spinner="Loading keywords…")
def keywords(account: str, ids: tuple, s: date, e: date) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    idstr = ",".join(map(str, ids))
    kc = {}
    for x in q(account, f"""SELECT ad_group_criterion.keyword.text,
        ad_group_criterion.keyword.match_type, ad_group_criterion.status,
        metrics.clicks, metrics.cost_micros FROM keyword_view WHERE campaign.id IN ({idstr})
        AND {_between(s, e)} AND metrics.cost_micros > 0"""):
        k = x.ad_group_criterion.keyword.text
        d = kc.setdefault(k, {"match": x.ad_group_criterion.keyword.match_type.name,
                              "status": x.ad_group_criterion.status.name,
                              "clicks": 0, "cost": 0.0, "signups": 0.0})
        d["clicks"] += x.metrics.clicks
        d["cost"] += usd(x.metrics.cost_micros)
    for x in q(account, f"""SELECT ad_group_criterion.keyword.text,
        segments.conversion_action_name, metrics.all_conversions FROM keyword_view
        WHERE campaign.id IN ({idstr}) AND {_between(s, e)} AND metrics.all_conversions > 0"""):
        if bucket(x.segments.conversion_action_name) == "signups":
            k = x.ad_group_criterion.keyword.text
            if k in kc:
                kc[k]["signups"] += x.metrics.all_conversions
    df = pd.DataFrame([{"keyword": k, **v} for k, v in kc.items()])
    if df.empty:
        return df
    df["$/signup"] = (df["cost"] / df["signups"]).where(df["signups"] > 0)
    return df.sort_values("cost", ascending=False)


@st.cache_data(ttl=600, show_spinner="Loading creatives…")
def uac_assets(account: str, ids: tuple, s: date, e: date) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    idstr = ",".join(map(str, ids))
    base = {}
    for x in q(account, f"""SELECT asset.resource_name, ad_group_ad_asset_view.field_type,
        asset.text_asset.text, asset.name, asset.youtube_video_asset.youtube_video_id,
        metrics.cost_micros FROM ad_group_ad_asset_view WHERE campaign.id IN ({idstr})
        AND {_between(s, e)} AND metrics.impressions > 0"""):
        a = x.asset
        d = base.setdefault(a.resource_name, {
            "field": x.ad_group_ad_asset_view.field_type.name,
            "text": a.text_asset.text or "",
            "creative": (a.text_asset.text or a.name or a.youtube_video_asset.youtube_video_id or "—")[:46],
            "cost": 0.0, "signups": 0.0, "verifs": 0.0})
        d["cost"] += usd(x.metrics.cost_micros)
    for x in q(account, f"""SELECT asset.resource_name, segments.conversion_action_name,
        metrics.all_conversions FROM ad_group_ad_asset_view WHERE campaign.id IN ({idstr})
        AND {_between(s, e)} AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        if b in ("signups", "verifs") and x.asset.resource_name in base:
            base[x.asset.resource_name][b] += x.metrics.all_conversions
    df = pd.DataFrame(base.values())
    if df.empty:
        return df
    df["$/verif"] = (df["cost"] / df["verifs"]).where(df["verifs"] > 0)
    return df.sort_values("cost", ascending=False)


# ============================== charts ==============================
def funnel(t: dict, stages: list[tuple]):
    df = pd.DataFrame([{"stage": lbl, "count": t[k]} for k, lbl in stages])
    top = df["count"].iloc[0] or 1
    df["pct"] = df["count"] / top * 100
    df["label"] = [f"{c:,.0f}   {p:.0f}%" for c, p in zip(df["count"], df["pct"])]
    order = [lbl for _, lbl in stages]
    base = alt.Chart(df).encode(y=alt.Y("stage:N", sort=order, title=None),
                                x=alt.X("count:Q", title=None, axis=None))
    bars = base.mark_bar(cornerRadiusEnd=4, height=26).encode(
        color=alt.Color("stage:N", sort=order, legend=None,
                        scale=alt.Scale(domain=order, range=FUNNEL_RAMP[:len(order)])),
        tooltip=[alt.Tooltip("stage:N", title="Stage"),
                 alt.Tooltip("count:Q", title="Count", format=",.0f"),
                 alt.Tooltip("pct:Q", title="% of top", format=".1f")])
    text = base.mark_text(align="left", dx=8, color=INK, fontSize=12).encode(text="label:N")
    return styled(bars + text, height=44 * len(order))


def trend(df: pd.DataFrame, col: str, title: str, color: str, money: bool):
    fmt = "$,.0f" if money else ",.0f"
    d = df[df[col].notna()]
    ch = alt.Chart(d).mark_line(color=color, strokeWidth=2, point=alt.OverlayMarkDef(
        size=45, filled=True, fill=color)).encode(
        x=alt.X("date:T", title=None), y=alt.Y(f"{col}:Q", title=title),
        tooltip=[alt.Tooltip("date:T", title="Day"), alt.Tooltip(f"{col}:Q", title=title, format=fmt)])
    return styled(ch)


def multi_trend(df: pd.DataFrame, cols: list[str], title: str):
    m = df.melt(id_vars="date", value_vars=cols, var_name="Event", value_name="count")
    ch = alt.Chart(m).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=45, filled=True)).encode(
        x=alt.X("date:T", title=None), y=alt.Y("count:Q", title=title),
        color=alt.Color("Event:N", title=None, scale=alt.Scale(domain=cols, range=[S1, S2, S3][:len(cols)])),
        tooltip=[alt.Tooltip("date:T", title="Day"), "Event:N",
                 alt.Tooltip("count:Q", title="Count", format=",.0f")])
    return styled(ch)


def hbar(df: pd.DataFrame, label_col: str, val_col: str, title: str, money=True, n=12):
    d = df.head(n)
    fmt = "$,.2f" if money else ",.0f"
    ch = alt.Chart(d).mark_bar(cornerRadiusEnd=4, color=S1, height=18).encode(
        y=alt.Y(f"{label_col}:N", sort="-x", title=None),
        x=alt.X(f"{val_col}:Q", title=title),
        tooltip=[alt.Tooltip(f"{label_col}:N", title=label_col.title()),
                 alt.Tooltip(f"{val_col}:Q", title=title, format=fmt)])
    return styled(ch, height=max(120, 26 * len(d)))


def status_bar(df: pd.DataFrame, label_col: str, val_col: str, title: str, n=12):
    """Efficiency bars — status colour PLUS an explicit Status label (never colour alone)."""
    d = df[df[val_col].notna()].head(n).copy()
    if d.empty:
        return None, d
    med = d[val_col].median()
    d["Status"] = ["⚠ Inefficient" if v > 1.8 * med else "✓ Efficient" for v in d[val_col]]
    ch = alt.Chart(d).mark_bar(cornerRadiusEnd=4, height=18).encode(
        y=alt.Y(f"{label_col}:N", sort="-x", title=None),
        x=alt.X(f"{val_col}:Q", title=title),
        color=alt.Color("Status:N", title=None,
                        scale=alt.Scale(domain=["✓ Efficient", "⚠ Inefficient"], range=[GOOD, CRIT])),
        tooltip=[alt.Tooltip(f"{label_col}:N", title="Creative"), "Status:N",
                 alt.Tooltip("cost:Q", title="Cost", format="$,.0f"),
                 alt.Tooltip(f"{val_col}:Q", title=title, format="$,.2f")])
    return styled(ch, height=max(140, 26 * len(d))), d


def kpis(cur: dict, prev: dict, keys: list[tuple]):
    """Delta semantics: outcomes up = good, cost-per up = bad, spend/clicks neutral."""
    neutral = {"cost", "clicks"}
    cols = st.columns(len(keys))
    for col, (k, label, money) in zip(cols, keys):
        v, p = cur.get(k, 0), prev.get(k, 0)
        val = f"${v:,.0f}" if money else f"{v:,.0f}"
        delta = f"{(v - p) / p * 100:+.0f}% vs prev" if p else None
        tone = "off" if k in neutral else ("inverse" if k.startswith("$") else "normal")
        col.metric(label, val, delta, delta_color=tone)


def cost_per(t: dict, ev: str) -> float | None:
    return t["cost"] / t[ev] if t.get(ev) else None


# ============================== sidebar ==============================
st.title(f"📊 Google Ads — {BRAND}")

default_account = ads_auth.get_account()
if not default_account:
    st.error("No Google Ads account configured.\n\n**Streamlit Cloud:** *App settings → Secrets* → "
             "add an `[ads]` section with `account = \"1234567890\"` and a `[google_ads]` section "
             "(see `.streamlit/secrets.toml.example`).\n\n**Locally:** set `ADS_ANALYSIS_ACCOUNT` in `.env`.")
    st.stop()
try:
    ads_auth.load_credentials()
except Exception as exc:
    st.error(f"Google Ads credentials are not configured: {exc}")
    st.stop()

with st.sidebar:
    st.header("Filters")
    try:
        accs = accessible_accounts()
    except Exception as exc:
        st.warning(f"Could not list accounts ({exc}). Using the configured one.")
        accs = [(default_account, default_account)]
    labels = {cid: lbl for cid, lbl in accs} or {default_account: default_account}
    ids_list = list(labels)
    idx = ids_list.index(default_account) if default_account in ids_list else 0
    account = st.selectbox("Account", ids_list, index=idx, format_func=lambda c: labels[c])

    preset = st.radio("Period", ["Last 7 days", "Last 14 days", "Last 30 days", "Custom"])
    today = date.today()
    if preset == "Custom":
        s = st.date_input("Start", today - timedelta(days=7))
        e = st.date_input("End", today)
    else:
        s = today - timedelta(days={"Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}[preset])
        e = today
    span = (e - s).days or 1
    ps, pe = s - timedelta(days=span), s - timedelta(days=1)  # previous equal-length period
    st.caption(f"**{s} → {e}**  ·  compared with {ps} → {pe}")
    if st.button("🔄 Refresh data", width="stretch"):
        st.cache_data.clear()

st.caption(f"Account {labels.get(account, account)} · live · read-only")
tab_s, tab_u, tab_o = st.tabs(["🔍 Search (W2A)", "📱 UAC / App", "💡 Optimization"])


def channel_block(channel: str, kind: str):
    camps = campaigns(account, channel, s, e)
    if not camps:
        st.info(f"No {kind} campaigns with spend in this period.")
        return None, None
    ids = tuple(c[0] for c in camps)
    cur, prev = totals(account, ids, s, e), totals(account, ids, ps, pe)
    ev = "verifs" if channel == "MULTI_CHANNEL" else "signups"
    cur["$/event"], prev["$/event"] = cost_per(cur, ev) or 0, cost_per(prev, ev) or 0
    kpis(cur, prev, [("cost", "Spend", True), ("clicks", "Clicks", False),
                     ("installs", "Installs", False), ("signups", "Signups", False),
                     ("verifs", "Verifs", False), ("deposits", "Deposits", False),
                     ("$/event", f"$/{ev[:-1].title()}", True)])
    df = daily(account, ids, s, e)
    stages = ([("installs", "Installs"), ("signups", "Signups"), ("verifs", "Verifs"), ("deposits", "Deposits")]
              if channel == "MULTI_CHANNEL" else
              [("clicks", "Clicks"), ("signups", "Signups"), ("verifs", "Verifs"), ("deposits", "Deposits")])
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Funnel**")
        st.altair_chart(funnel(cur, stages), width="stretch")
        with st.expander("Table"):
            st.dataframe(pd.DataFrame([{"stage": l, "count": cur[k]} for k, l in stages]),
                         width="stretch", hide_index=True)
    with c2:
        st.markdown("**Spend by day**")
        if not df.empty:
            st.altair_chart(trend(df, "cost", "Spend $", S1, True), width="stretch")
    if not df.empty:
        c3, c4 = st.columns(2)
        eff = "$/Verif" if channel == "MULTI_CHANNEL" else "$/Signup"
        with c3:
            st.markdown(f"**{eff} by day**")
            st.altair_chart(trend(df, eff, eff, S2, True), width="stretch")
        with c4:
            st.markdown("**Events by day**")
            st.altair_chart(multi_trend(df, ["signups", "verifs"], "Count"), width="stretch")
        with st.expander("Daily table"):
            st.dataframe(df, width="stretch", hide_index=True)
    split = campaign_split(account, ids, s, e)
    if len(split) > 1:
        st.markdown("**Spend by campaign**")
        st.altair_chart(hbar(split, "campaign", "cost", "Spend $"), width="stretch")
    return ids, camps


with tab_s:
    s_ids, _ = channel_block("SEARCH", "Search")
    if s_ids:
        kdf = keywords(account, s_ids, s, e)
        if not kdf.empty:
            st.markdown("**Top keywords by spend**")
            st.altair_chart(hbar(kdf, "keyword", "cost", "Spend $"), width="stretch")
            with st.expander("All keywords (by event)"):
                st.dataframe(kdf, width="stretch", hide_index=True,
                             column_config={"cost": st.column_config.NumberColumn(format="$%.2f"),
                                            "$/signup": st.column_config.NumberColumn(format="$%.2f")})

with tab_u:
    u_ids, _ = channel_block("MULTI_CHANNEL", "App")
    if u_ids:
        adf = uac_assets(account, u_ids, s, e)
        ch, marked = status_bar(adf, "creative", "$/verif", "$ per verification")
        if ch is not None:
            st.markdown("**Creative efficiency — cost per verification**")
            st.caption("Verification (`level_up`) is the campaign's optimization event.")
            st.altair_chart(ch, width="stretch")
            with st.expander("All creatives"):
                st.dataframe(adf, width="stretch", hide_index=True,
                             column_config={"cost": st.column_config.NumberColumn(format="$%.0f"),
                                            "$/verif": st.column_config.NumberColumn(format="$%.2f")})

# ============================== optimization ==============================
with tab_o:
    st.markdown("### Optimization recommendations")
    st.caption("Computed live for the selected account and period — nothing is applied. "
               "Approve items and they get pushed via the MCP write tools (dry-run → confirm → audit).")
    if not st.button("Generate recommendations", type="primary"):
        st.info("Press the button — these queries are heavier than the dashboard.")
        st.stop()

    search_ids = tuple(c[0] for c in campaigns(account, "SEARCH", s, e))
    app_ids = tuple(c[0] for c in campaigns(account, "MULTI_CHANNEL", s, e))

    # --- 1. wasted search terms not already blocked -------------------------
    st.markdown("#### 1 · Negative keywords to add")
    if search_ids:
        idstr = ",".join(map(str, search_ids))
        negs = [(x.campaign_criterion.keyword.text.lower(), x.campaign_criterion.keyword.match_type.name)
                for x in q(account, f"""SELECT campaign_criterion.keyword.text,
                    campaign_criterion.keyword.match_type FROM campaign_criterion
                    WHERE campaign.id IN ({idstr}) AND campaign_criterion.negative = TRUE
                    AND campaign_criterion.type = 'KEYWORD'""")]
        junk = analysis_config.get("junk_tokens", [])
        cand = []
        for x in q(account, f"""SELECT search_term_view.search_term, metrics.cost_micros,
            metrics.clicks, metrics.conversions FROM search_term_view
            WHERE campaign.id IN ({idstr}) AND {_between(s, e)}
            ORDER BY metrics.cost_micros DESC"""):
            term, cost = x.search_term_view.search_term, usd(x.metrics.cost_micros)
            if (x.metrics.conversions == 0 and cost >= 0.5
                    and any(j in term.lower() for j in junk) and not is_blocked(term, negs)):
                cand.append({"term": term, "EN": to_en(term), "why": neg_reason(term),
                             "cost": cost, "clicks": x.metrics.clicks,
                             "match": "EXACT" if len(term.split()) <= 1 else "PHRASE"})
        if cand:
            cdf = pd.DataFrame(cand)
            st.success(f"{len(cdf)} new wasteful terms — ${cdf['cost'].sum():,.2f} with zero conversions "
                       f"(already-blocked terms are excluded).")
            st.dataframe(cdf, width="stretch", hide_index=True,
                         column_config={"cost": st.column_config.NumberColumn(format="$%.2f")})
        else:
            st.success("No new waste — existing negatives already cover the junk. ✅")
    else:
        st.info("No Search campaigns in this period.")

    # --- 2. keywords to pause ----------------------------------------------
    st.markdown("#### 2 · Keywords to pause")
    kdf = keywords(account, search_ids, s, e) if search_ids else pd.DataFrame()
    if not kdf.empty:
        drop = kdf[(kdf["status"] == "ENABLED") & (kdf["signups"] == 0) & (kdf["cost"] >= 5)]
        if not drop.empty:
            st.warning(f"{len(drop)} enabled keywords spent ${drop['cost'].sum():,.2f} with **0 signups**.")
            st.dataframe(drop[["keyword", "match", "clicks", "cost"]], width="stretch", hide_index=True,
                         column_config={"cost": st.column_config.NumberColumn(format="$%.2f")})
        else:
            st.success("No enabled keyword is burning ≥$5 without a signup. ✅")

    # --- 3. creative proposals ---------------------------------------------
    st.markdown("#### 3 · Creatives to swap or rewrite")
    adf = uac_assets(account, app_ids, s, e) if app_ids else pd.DataFrame()
    if not adf.empty:
        have = adf[adf["$/verif"].notna()]
        med = have["$/verif"].median() if not have.empty else None
        weak = adf[(adf["cost"] >= 20) & ((adf["verifs"] == 0) |
                                          (med and adf["$/verif"] > 1.8 * med))]
        if not weak.empty:
            used = {creative_bank._norm(t) for t in adf["text"] if t}
            taken, out = set(), []
            for _, a in weak.iterrows():
                why = ("0 verifications" if a["verifs"] == 0
                       else f"${a['$/verif']:.2f}/verif (~{a['$/verif']/med:.1f}× median)")
                fix = "swap this creative"
                if a["field"] in ("HEADLINE", "DESCRIPTION") and a["text"]:
                    alt_txt = creative_bank.suggest(a["field"], used, taken)
                    fix = f"replace with: “{alt_txt}”" if alt_txt else "rewrite (bank exhausted)"
                out.append({"field": a["field"], "creative": a["creative"],
                            "cost": a["cost"], "why": why, "proposal": fix})
            st.warning(f"{len(out)} inefficient assets (median ${med:,.2f}/verif)." if med
                       else f"{len(out)} assets spending without verifications.")
            st.dataframe(pd.DataFrame(out), width="stretch", hide_index=True,
                         column_config={"cost": st.column_config.NumberColumn(format="$%.0f")})
        else:
            st.success("Every asset with real spend converts efficiently. ✅")
    else:
        st.info("No App campaigns in this period.")

    # --- 4. funnel health ---------------------------------------------------
    st.markdown("#### 4 · Funnel health")
    msgs = []
    for ids_, kind in ((search_ids, "Search"), (app_ids, "UAC")):
        if not ids_:
            continue
        t = totals(account, ids_, s, e)
        if t["cost"] >= 50 and (t["installs"] + t["signups"] + t["verifs"]) == 0:
            msgs.append(("error", f"**{kind}**: ${t['cost']:,.0f} spent with zero funnel events — pause or fix tracking."))
        elif t["signups"] and t["verifs"] / t["signups"] < 0.15:
            msgs.append(("warning", f"**{kind}**: signup→verification drop — {t['verifs']:.0f}/{t['signups']:.0f} "
                                    f"({t['verifs']/t['signups']*100:.0f}%). Onboarding friction or low-quality traffic."))
        elif t["verifs"]:
            msgs.append(("success", f"**{kind}**: {t['verifs']:.0f} verifications at ${t['cost']/t['verifs']:,.2f} each."))
    for kind, text in msgs or [("info", "Not enough data in this period.")]:
        getattr(st, kind)(text)
