#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Build docs/SlicerSwap-Guide.pdf (attached to every GitHub release) from README, HOW_IT_WORKS and CHANGELOG.

    pip install markdown playwright && python3 -m playwright install chromium
    python3 tools/make_guide_pdf.py
"""
import os
import re
import sys

import markdown
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from slicerswap import __build_date__, __version__  # noqa: E402

CSS = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
body { font-family: "DejaVu Sans", Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1d1d1f; }
h1 { font-size: 20pt; margin: 0 0 6pt; } h2 { font-size: 14pt; margin: 16pt 0 6pt; border-bottom: 1px solid #ccc; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; } code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.8pt;
background: #f2f2f2; padding: 0 2px; } pre { background: #f2f2f2; padding: 6pt; white-space: pre-wrap; font-size: 8.5pt; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 6pt 0; } td, th { border: 1px solid #ccc;
padding: 3pt 5pt; vertical-align: top; } th { background: #f2f2f2; } img { max-width: 100%; height: auto; }
.wip { background: #b00020; color: #fff; font-weight: bold; padding: 5pt 8pt; text-align: center; margin-bottom: 10pt; }
.part { page-break-before: always; } a { color: #0a58ca; text-decoration: none; }
"""


def md(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        text = fh.read()
    html = markdown.markdown(text, extensions=["tables", "fenced_code"])
    # images are relative to the repo; GitHub-only badges and the centred <p> wrappers stay as they are
    return re.sub(r'src="(?!https?:)([^"]+)"', lambda m: f'src="file://{os.path.join(ROOT, m.group(1))}"', html)


def main():
    out = os.path.join(ROOT, "docs", "SlicerSwap-Guide.pdf")
    body = (f'<div class="wip">WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN · v{__version__} · built {__build_date__}</div>'
            + md("README.md") + '<div class="part"></div>' + md("HOW_IT_WORKS.md")
            + '<div class="part"></div>' + md("CHANGELOG.md"))
    page_html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    tmp = os.path.join(ROOT, "docs", ".guide.html")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(page_html)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto("file://" + tmp)
            pg.wait_for_load_state("networkidle")
            pg.pdf(path=out, format="A4", print_background=True, display_header_footer=True,
                   header_template="<span></span>",
                   footer_template=f'<div style="font-size:7pt;width:100%;text-align:center;color:#666">SlicerSwap {__version__} · '
                                   '<span class="pageNumber"></span> / <span class="totalPages"></span></div>',
                   margin={"top": "16mm", "bottom": "18mm", "left": "15mm", "right": "15mm"})
            b.close()
    finally:
        os.remove(tmp)
    print(out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
