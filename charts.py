"""Dependency-free inline-SVG sparkline panels for the daily report.

daily_panel() renders a stack of small line charts (one metric per row, each with
its own y-scale) as a single-line SVG string that embeds directly in the HTML
report. `None` values render as gaps (e.g. CPL on a day with 0 signups).
"""

from __future__ import annotations

import html

COLORS = ["#1a73e8", "#0f9d58", "#f4b400", "#db4437", "#9334e6", "#00acc1"]


def _fmt(v: float | None, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "money":
        return f"${v:,.0f}"
    if kind == "money2":
        return f"${v:,.2f}"
    return f"{v:,.0f}"


def daily_panel(title: str, dates: list[str], series: list[tuple]) -> str:
    """series: list of (label, values, kind) where kind in money|money2|int."""
    n = len(dates)
    if n < 2:
        return f"<div class='chart'><b>{html.escape(title)}</b><br><small>not enough days yet</small></div>"
    W, LEFT, RIGHT, ROW, PAD = 860, 165, 96, 60, 12
    plot_w = W - LEFT - RIGHT
    H = ROW * len(series) + 34
    xs = [LEFT + (plot_w * i / (n - 1)) for i in range(n)]
    parts = [f"<svg viewBox='0 0 {W} {H}' width='100%' xmlns='http://www.w3.org/2000/svg' "
             f"font-family='-apple-system,Segoe UI,Roboto,sans-serif'>"]
    parts.append(f"<text x='0' y='18' font-size='14' font-weight='600' fill='currentColor'>"
                 f"{html.escape(title)}</text>")
    # date axis labels (first / mid / last)
    for idx in (0, n // 2, n - 1):
        parts.append(f"<text x='{xs[idx]:.0f}' y='{H-4}' font-size='10' fill='#999' "
                     f"text-anchor='middle'>{html.escape(dates[idx][5:])}</text>")
    for r, (label, vals, kind) in enumerate(series):
        top = 34 + r * ROW
        base, height = top + ROW - 16, ROW - 22
        color = COLORS[r % len(COLORS)]
        nums = [v for v in vals if v is not None]
        lo, hi = (min(nums), max(nums)) if nums else (0, 1)
        rng = (hi - lo) or 1
        def y(v):
            return base - (v - lo) / rng * height
        # gridline baseline
        parts.append(f"<line x1='{LEFT}' y1='{base:.0f}' x2='{LEFT+plot_w}' y2='{base:.0f}' "
                     f"stroke='#e4e6e9' stroke-width='1'/>")
        # polyline with gaps for None
        seg = []
        for i, v in enumerate(vals):
            if v is None:
                if len(seg) >= 2:
                    parts.append(f"<polyline points='{' '.join(seg)}' fill='none' "
                                 f"stroke='{color}' stroke-width='2'/>")
                seg = []
            else:
                seg.append(f"{xs[i]:.1f},{y(v):.1f}")
        if len(seg) >= 2:
            parts.append(f"<polyline points='{' '.join(seg)}' fill='none' stroke='{color}' stroke-width='2'/>")
        for i, v in enumerate(vals):
            if v is not None:
                parts.append(f"<circle cx='{xs[i]:.1f}' cy='{y(v):.1f}' r='2.4' fill='{color}'/>")
        parts.append(f"<text x='0' y='{top+ROW/2:.0f}' font-size='12' fill='currentColor'>"
                     f"{html.escape(label)}</text>")
        last = next((v for v in reversed(vals) if v is not None), None)
        parts.append(f"<text x='{W}' y='{top+ROW/2:.0f}' font-size='12' font-weight='600' "
                     f"fill='{color}' text-anchor='end'>{_fmt(last, kind)}</text>")
        parts.append(f"<text x='{W}' y='{top+ROW/2+14:.0f}' font-size='9' fill='#999' "
                     f"text-anchor='end'>min {_fmt(lo, kind)} · max {_fmt(hi, kind)}</text>")
    parts.append("</svg>")
    return "<div class='chart'>" + "".join(parts) + "</div>"
