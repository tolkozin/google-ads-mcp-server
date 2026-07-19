"""Tiny, dependency-free Markdown -> styled HTML renderer for the daily report.

Handles exactly the subset the analyzer emits: #/## headings, | tables |,
- bullets, > blockquotes, --- rules, **bold**, `code`. Self-contained HTML
(inline CSS) so it opens straight in a browser.
"""

from __future__ import annotations

import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+?)`")


def _inline(text: str) -> str:
    text = html.escape(text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _CODE.sub(r"<code>\1</code>", text)
    return text


def _is_sep(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c.strip() or "") for c in cells)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def to_html(md: str, title: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if ln.startswith("<div class='chart'>"):  # inline SVG chart — pass through raw
            out.append(ln); i += 1; continue
        if ln.startswith("| "):  # table block
            block = []
            while i < n and lines[i].startswith("|"):
                block.append(lines[i]); i += 1
            header = _cells(block[0])
            body = [b for b in block[1:] if not _is_sep(_cells(b))]
            out.append("<div class='tw'><table>")
            out.append("<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in header) + "</tr></thead>")
            out.append("<tbody>")
            for row in body:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(row)) + "</tr>")
            out.append("</tbody></table></div>")
            continue
        if ln.startswith("# "):
            out.append(f"<h1>{_inline(ln[2:])}</h1>")
        elif ln.startswith("## "):
            out.append(f"<h2>{_inline(ln[3:])}</h2>")
        elif ln.startswith("> "):
            out.append(f"<blockquote>{_inline(ln[2:])}</blockquote>")
        elif ln.startswith("- "):
            items = []
            while i < n and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>"); i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.strip():
            out.append(f"<p>{_inline(ln)}</p>")
        i += 1

    body = "\n".join(out)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; background: #f6f7f9; color: #1c1e21; }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 28px 20px 80px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 17px; margin: 30px 0 12px; padding-left: 10px;
    border-left: 4px solid #1a73e8; }}
  p {{ margin: 8px 0; }}
  code {{ background: #eceef1; padding: 1px 5px; border-radius: 4px; font-size: 13px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  blockquote {{ margin: 10px 0; padding: 8px 14px; background: #fff8e1;
    border-left: 4px solid #f4b400; border-radius: 4px; font-size: 14px; }}
  ul {{ margin: 8px 0; padding-left: 22px; }}
  li {{ margin: 3px 0; }}
  hr {{ border: 0; border-top: 1px solid #dcdfe3; margin: 26px 0; }}
  .tw {{ overflow-x: auto; margin: 10px 0; }}
  .chart {{ background: #fff; border-radius: 8px; padding: 14px 16px; margin: 12px 0;
    box-shadow: 0 1px 3px rgba(0,0,0,.08); overflow-x: auto; color: #1c1e21; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 14px;
    border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th {{ background: #1a73e8; color: #fff; text-align: left; padding: 8px 11px; font-weight: 600; }}
  td {{ padding: 7px 11px; border-top: 1px solid #eceef1; }}
  tr:nth-child(even) td {{ background: #fafbfc; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #17181a; color: #e3e5e8; }}
    table, blockquote, .chart {{ background: #202224; }}
    .chart {{ color: #e3e5e8; }}
    code {{ background: #2a2c2f; }} td {{ border-color: #303235; }}
    tr:nth-child(even) td {{ background: #1b1d1f; }}
    blockquote {{ background: #2a2410; }}
  }}
</style></head><body><div class="wrap">
{body}
</div></body></html>"""
