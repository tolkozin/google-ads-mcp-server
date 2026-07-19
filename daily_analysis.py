"""Daily read-only Google Ads analysis -> TWO proposal reports (NO changes applied):
one for Search (W2A) and one for UAC/App. Each report has a 7-day snapshot broken
out by funnel EVENTS (never bare "conversions"), a daily trend chart, creative
analysis by deep events, and proposals. Applied only after you approve, via the
MCP write tools (dry-run -> confirm -> audit).

Config via env / .env: GOOGLE_ADS_CREDENTIALS, ADS_ANALYSIS_ACCOUNT (required),
ADS_ANALYSIS_LOGIN_CID (default = account).
"""

from __future__ import annotations

import os
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml
from google.ads.googleads.client import GoogleAdsClient

import analysis_config
import charts
import report_html
from translate import to_en


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (gitignored) so account id / paths stay out of the code."""
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(Path(__file__).parent / ".env")

ACCOUNT = os.getenv("ADS_ANALYSIS_ACCOUNT", "")  # set in gitignored .env
LOGIN_CID = os.getenv("ADS_ANALYSIS_LOGIN_CID", ACCOUNT)
CRED = os.getenv("GOOGLE_ADS_CREDENTIALS", str(Path(__file__).parent / "google-ads.yaml"))
if not ACCOUNT:
    raise SystemExit("Set ADS_ANALYSIS_ACCOUNT in .env or the environment.")
REPORTS = Path(__file__).parent / "reports"
# Market/vocabulary config lives in gitignored config.json (see config.example.json)
GEO = analysis_config.get("geo_target_constant")
LANG = analysis_config.get("language_constant")
JUNK = analysis_config.get("junk_tokens", [])
EVENTS = ["installs", "signups", "verifs", "dep_att", "deposits"]
EVENT_HDR = "Install | Signup | Verif | DepAtt | Deposit"


def get_client() -> GoogleAdsClient:
    cfg = yaml.safe_load(open(CRED))
    cfg["login_customer_id"] = LOGIN_CID
    return GoogleAdsClient.load_from_dict(cfg, version="v23")


def rows(client, q):
    ga = client.get_service("GoogleAdsService")
    out = []
    for b in ga.search_stream(customer_id=ACCOUNT, query=q):
        out.extend(b.results)
    return out


def usd(micros):
    return int(micros) / 1e6


def _norm(s: str) -> str:
    """Lowercase + strip accents, so 'Café' == 'cafe' when matching negatives."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn")


def existing_negatives(client, ids):
    """(normalized_text, match_type) for the campaigns' current negative keywords."""
    idstr = ",".join(str(i) for i in ids)
    out = []
    for x in rows(client, f"""SELECT campaign_criterion.keyword.text,
        campaign_criterion.keyword.match_type FROM campaign_criterion
        WHERE campaign.id IN ({idstr}) AND campaign_criterion.negative = TRUE
        AND campaign_criterion.type = 'KEYWORD'"""):
        out.append((_norm(x.campaign_criterion.keyword.text),
                    x.campaign_criterion.keyword.match_type.name))
    return out


def is_blocked(term: str, negs) -> bool:
    """True if `term` is already blocked by an existing negative (EXACT equality,
    PHRASE substring, or BROAD all-tokens-present)."""
    t = _norm(term)
    words = set(t.split())
    for et, em in negs:
        if not et:
            continue
        if em == "EXACT" and et == t:
            return True
        if em == "PHRASE" and et in t:
            return True
        if em == "BROAD" and set(et.split()) <= words:
            return True
    return False


def bucket(name: str) -> str | None:
    n = (name or "").lower()
    if "first_open" in n or "first-open" in n:
        return "installs"
    if "sign_up" in n or "signup_w2a" in n:
        return "signups"
    if "kyc" in n or "level_up" in n:  # level_up = KYC/verification in this account
        return "verifs"
    if "depattempt" in n or "add_payment_info" in n:
        return "dep_att"
    if "activation-deposited" in n:  # canonical deposit (avoids double-count)
        return "deposits"
    return None


def channel_campaigns(client, channel: str):
    """(id, name, status) for campaigns of a channel with spend in the last 7 days."""
    return [(x.campaign.id, x.campaign.name, x.campaign.status.name) for x in rows(client, f"""
        SELECT campaign.id, campaign.name, campaign.status, metrics.cost_micros
        FROM campaign
        WHERE campaign.advertising_channel_type = '{channel}'
              AND segments.date DURING LAST_7_DAYS AND metrics.cost_micros > 0
        ORDER BY metrics.cost_micros DESC""")]


def totals_7d(client, ids):
    """Per-campaign cost/clicks + event counts over the last 7 days."""
    idstr = ",".join(str(i) for i in ids)
    base = {i: {"cost": 0.0, "clicks": 0, **{e: 0.0 for e in EVENTS}} for i in ids}
    for x in rows(client, f"""SELECT campaign.id, metrics.cost_micros, metrics.clicks
        FROM campaign WHERE campaign.id IN ({idstr}) AND segments.date DURING LAST_7_DAYS"""):
        base[x.campaign.id]["cost"] += usd(x.metrics.cost_micros)
        base[x.campaign.id]["clicks"] += x.metrics.clicks
    for x in rows(client, f"""SELECT campaign.id, segments.conversion_action_name,
        metrics.all_conversions FROM campaign WHERE campaign.id IN ({idstr})
        AND segments.date DURING LAST_7_DAYS AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        if b:
            base[x.campaign.id][b] += x.metrics.all_conversions
    return base


def daily_series(client, ids):
    """(dates, {metric: [per-day values]}) over the last 7 days for a set of campaigns."""
    idstr = ",".join(str(i) for i in ids)
    day = {}
    for x in rows(client, f"""SELECT segments.date, metrics.cost_micros FROM campaign
        WHERE campaign.id IN ({idstr}) AND segments.date DURING LAST_7_DAYS ORDER BY segments.date"""):
        d = day.setdefault(x.segments.date, {"cost": 0.0, **{e: 0.0 for e in EVENTS}})
        d["cost"] += usd(x.metrics.cost_micros)
    for x in rows(client, f"""SELECT segments.date, segments.conversion_action_name,
        metrics.all_conversions FROM campaign WHERE campaign.id IN ({idstr})
        AND segments.date DURING LAST_7_DAYS AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        if b and x.segments.date in day:
            day[x.segments.date][b] += x.metrics.all_conversions
    dates = sorted(day)
    cost = [day[d]["cost"] for d in dates]
    ins = [day[d]["installs"] for d in dates]
    sig = [day[d]["signups"] for d in dates]
    dep_att = [day[d]["dep_att"] for d in dates]
    cpi = [(day[d]["cost"] / day[d]["installs"]) if day[d]["installs"] else None for d in dates]
    cpl = [(day[d]["cost"] / day[d]["signups"]) if day[d]["signups"] else None for d in dates]
    return dates, {"cost": cost, "cpi": cpi, "cpl": cpl, "dep_att": dep_att,
                   "installs": ins, "signups": sig}


def _ev_cells(t):
    return f"{t['installs']:.0f} | {t['signups']:.0f} | {t['verifs']:.0f} | {t['dep_att']:.0f} | {t['deposits']:.0f}"


# ============================ SEARCH REPORT ============================

def build_search(client, stamp):
    md = [f"# Search (W2A) — {stamp:%Y-%m-%d}",
          f"Account `{ACCOUNT}` · last 7 days · read-only · **no changes applied**\n"]
    camps = channel_campaigns(client, "SEARCH")
    if not camps:
        md.append("_No Search campaigns with spend in the last 7 days._")
        return "\n".join(md), {}
    ids = [c[0] for c in camps]
    tot = totals_7d(client, ids)

    md.append("## 1. Snapshot by event (7 days)\n")
    md.append(f"| Campaign | Status | Cost | Clicks | {EVENT_HDR} |")
    md.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    focus = {}
    for cid_, name, st in camps:
        t = tot[cid_]
        md.append(f"| {name} | {st} | ${t['cost']:.0f} | {t['clicks']} | {_ev_cells(t)} |")
        if not focus:
            focus = {"name": name, "cost": round(t["cost"], 2), "clicks": t["clicks"],
                     "signups": round(t["signups"], 0), "deposits": round(t["deposits"], 0)}
    md.append("")

    md.append("## 2. Daily trend\n")
    dates, s = daily_series(client, ids)
    md.append(charts.daily_panel("Search — cost / CPL(signup) / CPI(first-open) / deposit-attempts", dates,
              [("Cost/day", s["cost"], "money"), ("CPL signup", s["cpl"], "money2"),
               ("CPI first-open", s["cpi"], "money2"), ("Deposit-attempts", s["dep_att"], "int")]))
    md.append("")

    md.append("## 3. Creatives by deep events\n")
    md.append("> Signups = primary deep event. Clicks without signups = weak creative.\n")
    idstr = ",".join(str(i) for i in ids)
    ads = rows(client, f"""SELECT ad_group.name, ad_group_ad.ad.id, ad_group_ad.ad_strength,
        metrics.clicks, metrics.cost_micros, metrics.conversions,
        metrics.conversions_from_interactions_rate FROM ad_group_ad
        WHERE campaign.id IN ({idstr}) AND ad_group_ad.status != 'REMOVED'
        AND segments.date DURING LAST_7_DAYS ORDER BY metrics.cost_micros DESC""")
    n_flag = 0
    if ads:
        md.append("| Ad group | Ad id | Strength | Clicks | Cost | Signups | $/Signup | CvR |")
        md.append("|---|--:|---|--:|--:|--:|--:|--:|")
        flags = []
        for x in ads:
            s_, cost, conv = x.ad_group_ad.ad_strength.name, usd(x.metrics.cost_micros), x.metrics.conversions
            cps = f"${cost/conv:.2f}" if conv else "—"
            md.append(f"| {x.ad_group.name} | {x.ad_group_ad.ad.id} | {s_} | {x.metrics.clicks} "
                      f"| ${cost:.2f} | {conv:.0f} | {cps} | "
                      f"{x.metrics.conversions_from_interactions_rate*100:.1f}% |")
            if s_ in ("POOR", "AVERAGE"):
                flags.append(f"- Ad {x.ad_group_ad.ad.id} in `{x.ad_group.name}` is **{s_}** strength → add unique headlines/descriptions.")
            if cost >= 20 and conv == 0:
                flags.append(f"- 🔴 Ad {x.ad_group_ad.ad.id} in `{x.ad_group.name}` spent ${cost:.0f} with **0 signups** → rewrite/pause.")
        n_flag = len(flags)
        if flags:
            md.append("\n**Creative proposals:**"); md.extend(flags)
    else:
        md.append("_No ads with delivery._")
    md.append("")

    md.append("## 4. Keyword performance by event\n")
    kcost = {}
    for x in rows(client, f"""SELECT ad_group_criterion.keyword.text, metrics.clicks, metrics.cost_micros
        FROM keyword_view WHERE campaign.id IN ({idstr}) AND segments.date DURING LAST_7_DAYS
        AND metrics.cost_micros > 0 ORDER BY metrics.cost_micros DESC"""):
        k = x.ad_group_criterion.keyword.text
        kcost.setdefault(k, {"clicks": 0, "cost": 0.0, "signups": 0.0})
        kcost[k]["clicks"] += x.metrics.clicks
        kcost[k]["cost"] += usd(x.metrics.cost_micros)
    for x in rows(client, f"""SELECT ad_group_criterion.keyword.text, segments.conversion_action_name,
        metrics.all_conversions FROM keyword_view WHERE campaign.id IN ({idstr})
        AND segments.date DURING LAST_7_DAYS AND metrics.all_conversions > 0"""):
        if bucket(x.segments.conversion_action_name) == "signups":
            k = x.ad_group_criterion.keyword.text
            if k in kcost:
                kcost[k]["signups"] += x.metrics.all_conversions
    top = sorted(kcost.items(), key=lambda kv: -kv[1]["cost"])[:15]
    if top:
        md.append("| Keyword | Clicks | Cost | Signups | $/Signup |")
        md.append("|---|--:|--:|--:|--:|")
        for k, v in top:
            cps = f"${v['cost']/v['signups']:.2f}" if v["signups"] else "—"
            md.append(f"| {k} | {v['clicks']} | ${v['cost']:.2f} | {v['signups']:.0f} | {cps} |")
    md.append("")

    md.append("## 5. Proposed new negatives (14d search terms)\n")
    n_neg = _negatives(client, md, ids)
    md.append("## 6. Proposed keywords to add (planner)\n")
    n_add = _keyword_ideas(client, md, ids)

    md.append("---\n*Reply with what you approve; applied via MCP (validate_only → confirm → audit).*")
    focus.update({"neg": n_neg, "add": n_add, "flags": n_flag})
    return "\n".join(md), focus


_NEG_REASONS = [(r["tokens"], r["label"]) for r in analysis_config.get("negative_reasons", [])]


def neg_reason(term: str) -> str:
    t = f" {term.lower()} "
    for toks, label in _NEG_REASONS:
        if any(k in t for k in toks):
            return label
    return "Low intent"


def _negatives(client, md, ids):
    idstr = ",".join(str(i) for i in ids)
    negs = existing_negatives(client, ids)  # skip terms already blocked
    r = rows(client, f"""SELECT search_term_view.search_term, metrics.cost_micros, metrics.clicks,
        metrics.conversions FROM search_term_view WHERE campaign.id IN ({idstr})
        AND segments.date DURING LAST_14_DAYS ORDER BY metrics.cost_micros DESC""")
    cand = [(x.search_term_view.search_term.lower(), usd(x.metrics.cost_micros), x.metrics.clicks)
            for x in r if x.metrics.conversions == 0 and usd(x.metrics.cost_micros) >= 0.75
            and any(j in x.search_term_view.search_term.lower() for j in JUNK)
            and not is_blocked(x.search_term_view.search_term, negs)]
    md.append(f"> Only terms **not already blocked** by the campaign's "
              f"{len(negs)} existing negatives are shown.\n")
    if not cand:
        md.append("_No new waste — existing negatives already cover the junk. ✅_\n"); return 0
    md.append("| Search term | EN | Why | Cost | Clicks | Suggested |")
    md.append("|---|---|---|--:|--:|---|")
    for t, c, cl in cand[:25]:
        md.append(f"| {t} | {to_en(t)} | {neg_reason(t)} | ${c:.2f} | {cl} "
                  f"| negative {'EXACT' if len(t.split())<=1 else 'PHRASE'} |")
    md.append("")
    return len(cand)


def _keyword_ideas(client, md, ids):
    idstr = ",".join(str(i) for i in ids)
    cur = {x.ad_group_criterion.keyword.text.lower() for x in
           rows(client, f"SELECT ad_group_criterion.keyword.text FROM keyword_view WHERE campaign.id IN ({idstr})")}
    try:
        svc = client.get_service("KeywordPlanIdeaService")
        req = client.get_type("GenerateKeywordIdeasRequest")
        req.customer_id = ACCOUNT
        req.language = LANG
        req.geo_target_constants.append(GEO)
        req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        for s in analysis_config.get("keyword_seeds", []):
            req.keyword_seed.keywords.append(s)
        resp = svc.generate_keyword_ideas(request=req)
    except Exception as e:
        md.append(f"_Planner unavailable: {e}_\n"); return 0
    comp = {0: "?", 1: "LOW", 2: "MED", 3: "HIGH"}
    intent = analysis_config.get("intent_tokens", [])
    ideas = []
    for i in resp:
        t, m = i.text.lower(), i.keyword_idea_metrics
        v = m.avg_monthly_searches or 0
        if t in cur or v < 50 or any(j in t for j in JUNK) or not any(k in t for k in intent):
            continue
        ideas.append((t, v, comp.get(int(m.competition), "?"), usd(m.high_top_of_page_bid_micros or 0)))
    ideas.sort(key=lambda x: -x[1])
    if not ideas:
        md.append("_No fresh high-intent ideas._\n"); return 0
    md.append("| Keyword | EN | Vol/mo | Comp | HiBid | Suggested |")
    md.append("|---|---|--:|---|--:|---|")
    for t, v, c, hb in ideas[:20]:
        md.append(f"| {t} | {to_en(t)} | {v} | {c} | ${hb:.2f} | add PHRASE |")
    md.append("")
    return len(ideas)


# ============================ UAC REPORT ============================

def build_uac(client, stamp):
    md = [f"# UAC / App — {stamp:%Y-%m-%d}",
          f"Account `{ACCOUNT}` · last 7 days · read-only · **no changes applied**\n"]
    camps = channel_campaigns(client, "MULTI_CHANNEL")
    if not camps:
        md.append("_No App campaigns with spend in the last 7 days._")
        return "\n".join(md), {}
    ids = [c[0] for c in camps]
    tot = totals_7d(client, ids)

    md.append("## 1. Funnel by event (7 days)\n")
    md.append("> **Verif** (`level_up`) is the campaign's optimization event — watch $/Verif.\n")
    md.append(f"| Campaign | Status | Cost | {EVENT_HDR} | CPI | $/Signup | **$/Verif** | $/Deposit |")
    md.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    recs, focus = [], {}
    for cid_, name, st in camps:
        t = tot[cid_]
        cpi = f"${t['cost']/t['installs']:.2f}" if t["installs"] else "—"
        cps = f"${t['cost']/t['signups']:.2f}" if t["signups"] else "—"
        cpv = f"${t['cost']/t['verifs']:.2f}" if t["verifs"] else "—"
        cpd = f"${t['cost']/t['deposits']:.2f}" if t["deposits"] else "—"
        md.append(f"| {name} | {st} | ${t['cost']:.0f} | {_ev_cells(t)} | {cpi} | {cps} | {cpv} | {cpd} |")
        if not focus:
            focus = {"name": name, "cost": round(t["cost"], 2),
                     "signups": round(t["signups"], 0), "deposits": round(t["deposits"], 0)}
        if t["cost"] >= 50 and (t["installs"] + t["signups"] + t["verifs"]) == 0:
            recs.append(f"🔴 **Pause `{name}`** — ${t['cost']:.0f} spent, zero funnel events.")
        elif t["cost"] >= 100 and t["verifs"] == 0:
            recs.append(f"🟡 `{name}` — ${t['cost']:.0f} spent, **0 verifications** (opt. event); review targeting/creatives.")
        elif t["signups"] and t["verifs"] / t["signups"] < 0.15:
            recs.append(f"🟡 `{name}` — signup→verif drop: {t['verifs']:.0f}/{t['signups']:.0f} "
                        f"({t['verifs']/t['signups']*100:.0f}%). Onboarding/KYC friction or low-quality traffic.")
    md.append("")
    if recs:
        md.append("**Recommendations:**"); md.extend(f"- {r}" for r in recs); md.append("")

    md.append("## 2. Daily trend\n")
    dates, s = daily_series(client, ids)
    md.append(charts.daily_panel("UAC — cost / CPI / CPL(signup) / deposit-attempts", dates,
              [("Cost/day", s["cost"], "money"), ("CPI install", s["cpi"], "money2"),
               ("CPL signup", s["cpl"], "money2"), ("Deposit-attempts", s["dep_att"], "int")]))
    md.append("")

    md.append("## 3. Creatives by event (last 30 days)\n")
    md.append("> Judged on **$/Verif — the campaign's optimization event — not Google's asset "
              "label**. Inefficient text assets get a replacement suggestion.\n")
    _uac_assets(client, md, ids)

    md.append("---\n*Reply with what you approve; applied via MCP (validate_only → confirm → audit).*")
    return "\n".join(md), focus


def _uac_assets(client, md, ids):
    import creative_bank
    idstr = ",".join(str(i) for i in ids)
    base = {}
    for x in rows(client, f"""SELECT asset.resource_name, ad_group_ad_asset_view.field_type,
        asset.type, asset.text_asset.text, asset.name, asset.youtube_video_asset.youtube_video_id,
        metrics.cost_micros, metrics.clicks FROM ad_group_ad_asset_view
        WHERE campaign.id IN ({idstr}) AND segments.date DURING LAST_30_DAYS
        AND metrics.impressions > 0"""):
        rn = x.asset.resource_name
        a = x.asset
        d = base.setdefault(rn, {"field": x.ad_group_ad_asset_view.field_type.name,
                                 "type": a.type.name, "text": a.text_asset.text or "",
                                 "label": a.text_asset.text or a.name
                                          or a.youtube_video_asset.youtube_video_id or a.type.name,
                                 "cost": 0.0, "clicks": 0, "installs": 0.0, "signups": 0.0,
                                 "verifs": 0.0, "deposits": 0.0})
        d["cost"] += usd(x.metrics.cost_micros)
        d["clicks"] += x.metrics.clicks
    for x in rows(client, f"""SELECT asset.resource_name, segments.conversion_action_name,
        metrics.all_conversions FROM ad_group_ad_asset_view WHERE campaign.id IN ({idstr})
        AND segments.date DURING LAST_30_DAYS AND metrics.all_conversions > 0"""):
        b = bucket(x.segments.conversion_action_name)
        rn = x.asset.resource_name
        if b in ("installs", "signups", "verifs", "deposits") and rn in base:
            base[rn][b] += x.metrics.all_conversions
    if not base:
        md.append("_No serving assets with data._\n"); return
    ranked = sorted(base.values(), key=lambda a: -a["cost"])

    md.append("| Field | Creative | Cost | Clicks | Signups | Verifs | $/Verif | Deposits |")
    md.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for a in ranked[:15]:
        cpv = f"${a['cost']/a['verifs']:.2f}" if a["verifs"] else "—"
        md.append(f"| {a['field']} | {a['label'][:38]} | ${a['cost']:.0f} | {a['clicks']} "
                  f"| {a['signups']:.0f} | {a['verifs']:.0f} | {cpv} | {a['deposits']:.0f} |")
    md.append("")

    # Underperformers by the OPTIMIZATION event (verifs): 0 verifs on real spend, OR
    # $/verif far above the asset median — not Google's label.
    cpv_list = sorted(a["cost"] / a["verifs"] for a in ranked if a["verifs"] and a["cost"] >= 20)
    median = cpv_list[len(cpv_list) // 2] if cpv_list else None
    used = {creative_bank._norm(a["text"]) for a in ranked if a["text"]}
    taken, props = set(), []

    def why(a):
        if a["verifs"] == 0:
            return f"${a['cost']:.0f}, **0 verifs**"
        return f"${a['cost']:.0f}, $/verif ${a['cost']/a['verifs']:.2f} (~{a['cost']/a['verifs']/median:.1f}× median)"

    weak = [a for a in ranked if a["cost"] >= 20 and
            (a["verifs"] == 0 or (median and a["cost"] / a["verifs"] > 1.8 * median))]
    for a in sorted(weak, key=lambda a: -a["cost"]):
        if a["field"] in ("HEADLINE", "DESCRIPTION") and a["text"]:
            repl = creative_bank.suggest(a["field"], used, taken)
            repl_txt = f" → replace with: **“{repl}”**" if repl else " → rewrite (bank exhausted)."
            props.append(f"- 🔴 {a['field']} “{a['text'][:50]}” — {why(a)}{repl_txt}")
        else:
            props.append(f"- 🔴 {a['field']} ({a['type']}) `{a['label'][:34]}` — {why(a)} → swap this creative.")
    if props:
        med_txt = f"${median:.2f}" if median else "n/a"
        md.append(f"**Creative proposals — {len(props)} inefficient assets** (median $/verif {med_txt}):")
        md.extend(props[:20])
    else:
        md.append("_Every asset with real spend converts efficiently. ✅_")
    md.append("")


# ============================ MAIN ============================

def main():
    stamp = datetime.now(timezone.utc).astimezone()
    client = get_client()
    REPORTS.mkdir(exist_ok=True)
    outputs = {}
    for key, builder, title in [("search", build_search, "Search (W2A)"),
                                ("uac", build_uac, "UAC / App")]:
        md_text, focus = builder(client, stamp)
        (REPORTS / f"{stamp:%Y-%m-%d}-{key}.md").write_text(md_text, encoding="utf-8")
        html_path = REPORTS / f"{stamp:%Y-%m-%d}-{key}.html"
        html_path.write_text(report_html.to_html(md_text, f"{title} — {stamp:%Y-%m-%d}"), encoding="utf-8")
        outputs[key] = focus
        print(f"Wrote {key}: {html_path}")

    # delivery (best-effort)
    try:
        import notify
        se, ua = outputs.get("search", {}), outputs.get("uac", {})
        push = (
            f"*Google Ads — {stamp:%Y-%m-%d}*\n"
            f"🔍 Search `{se.get('name', 'n/a')}`: ${se.get('cost', 0)} · "
            f"{se.get('signups', 0):.0f} signups · {se.get('deposits', 0):.0f} dep\n"
            f"📱 UAC `{ua.get('name', 'n/a')}`: ${ua.get('cost', 0)} · "
            f"{ua.get('signups', 0):.0f} signups · {ua.get('deposits', 0):.0f} dep\n"
            f"Search proposals: ➕{se.get('add', 0)} kw · ⛔{se.get('neg', 0)} neg · ⚠️{se.get('flags', 0)} creatives\n"
            f"Reports: reports/{stamp:%Y-%m-%d}-search.html · -uac.html"
        )
        sent = notify.send_telegram(push)
        row = [f"{stamp:%Y-%m-%d}", se.get("name", ""), se.get("cost", 0), se.get("signups", 0),
               se.get("deposits", 0), ua.get("name", ""), ua.get("cost", 0),
               ua.get("signups", 0), ua.get("deposits", 0)]
        appended = notify.append_sheet(row)
        print(f"telegram sent: {sent} | sheet appended: {appended}")
    except Exception as e:
        print(f"[notify] delivery skipped: {e}")


if __name__ == "__main__":
    main()
