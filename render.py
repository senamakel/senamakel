#!/usr/bin/env python3
"""Rasterize header.svg -> header.png at 2x using headless Chromium.

Chromium honours the SVG's embedded @font-face (JetBrains Mono) and the embedded
portrait, so the PNG is pixel-consistent everywhere it is displayed. Run after
today.py has refreshed the stat values.

    pip install playwright
    playwright install chromium
    python render.py
"""
import os
import re

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "header.svg")
PNG = os.path.join(HERE, "header.png")
SCALE = 2  # retina

svg = open(SVG, encoding="utf-8").read()
w = int(re.search(r'width="(\d+)px"', svg).group(1))
h = int(re.search(r'height="(\d+)px"', svg).group(1))

html = (
    "<!doctype html><html><head><style>"
    "html,body{margin:0;padding:0;background:transparent}svg{display:block}"
    "</style></head><body>" + svg + "</body></html>"
)

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--force-color-profile=srgb"])
    page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=SCALE)
    page.set_content(html, wait_until="networkidle")
    page.locator("svg").screenshot(path=PNG, omit_background=True)
    browser.close()

print(f"wrote {PNG} at {w * SCALE}x{h * SCALE} ({os.path.getsize(PNG) / 1024:.0f} KB)")
