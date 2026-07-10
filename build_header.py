#!/usr/bin/env python3
"""Regenerate the header.svg *template* from image.png + the embedded font.

Run this only when the layout, portrait, or copy changes:

    python build_header.py

An open monospace font (JetBrains Mono, OFL) is embedded as a base64 @font-face
so character metrics are identical in every renderer. JetBrains Mono has a 0.6em
advance, so at font-size 15px every glyph is exactly 9px wide and the dotted
leaders right-align every value to a single column (RC).

The generated SVG carries element ids (repo_data, star_data, ...) with
placeholder values. today.py rewrites those on each run; render.py rasterizes
the result to header.png (the image embedded in the README).
"""
import base64
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "image.png"), "rb") as f:
    raw = f.read()
portrait = base64.b64encode(raw).decode("ascii")
IMG_W, IMG_H = struct.unpack(">II", raw[16:24])  # PNG intrinsic size from IHDR

with open(os.path.join(HERE, "fonts", "JetBrainsMono-Regular.woff2"), "rb") as f:
    font_b64 = base64.b64encode(f.read()).decode("ascii")

BG = "#16171b"
FONT_SIZE = 15
CHAR_W = FONT_SIZE * 0.6                 # JetBrains Mono advance = 0.6em -> 9.0px

H = 646
V_MARGIN = 30
PH = H - 2 * V_MARGIN
PW = round(PH * IMG_W / IMG_H)
PX = 24
PY = V_MARGIN

X = PX + PW + 26                         # right column origin (px)
Y0 = 40
STEP = 22
RC = 56                                  # right-align column for values (chars); matches today.py
RULE_END = X + RC * CHAR_W


def col_px(chars):
    return X + chars * CHAR_W


lines = []   # <line> rule elements (siblings of the <text>)


def leader(key, value):
    """Dotted leader so `value` right-aligns to column RC."""
    n = RC - 3 - len(key) - len(value)   # ". " + key + ":" + leader + value == RC
    n = max(n, 2)
    return " " + ("." * (n - 2)) + " "


def kv(y, key, value, dots_id=None, value_id=None, value_cls="value"):
    dots = leader(key, value)
    did = f' id="{dots_id}"' if dots_id else ""
    vid = f' id="{value_id}"' if value_id else ""
    return (
        f'<tspan x="{X}" y="{y}"><tspan class="cc">. </tspan>'
        f'<tspan class="key">{key}</tspan>:'
        f'<tspan class="cc"{did}>{dots}</tspan>'
        f'<tspan class="{value_cls}"{vid}>{value}</tspan></tspan>'
    )


def section(y, label):
    start = col_px(len(label) + 1)
    lines.append(f'<line x1="{start:.0f}" y1="{y - 5}" x2="{RULE_END:.0f}" y2="{y - 5}" stroke="#30363d" stroke-width="1"/>')
    return f'<tspan x="{X}" y="{y}" fill="#8b949e">{label}</tspan>'


rows = []
y = Y0

start = col_px(len("steven@enamakel") + 1)
lines.append(f'<line x1="{start:.0f}" y1="{y - 5}" x2="{RULE_END:.0f}" y2="{y - 5}" stroke="#30363d" stroke-width="1"/>')
rows.append(f'<tspan x="{X}" y="{y}" fill="#c9d1d9">steven@enamakel</tspan>'); y += STEP

rows.append(kv(y, "OS", "macOS, Linux, Rust")); y += STEP
rows.append(kv(y, "Uptime", "XX years, XX months, XX days", "age_data_dots", "age_data")); y += STEP
rows.append(kv(y, "Host", "Builder first, founder second")); y += STEP
rows.append(kv(y, "Kernel", "deep-tech · web3 · AI")); y += STEP
y += STEP
rows.append(kv(y, "Languages.Programming", "Rust, TypeScript, Solidity")); y += STEP
rows.append(kv(y, "Languages.Systems", "Python, C, Move, Bash")); y += STEP
y += STEP

rows.append(section(y, "Focus")); y += STEP
rows.append(kv(y, "OpenHuman", "Personal AI super-intelligence")); y += STEP
rows.append(kv(y, "DeFi", "ZeroLend · MahaDAO · ARTH")); y += STEP
y += STEP

rows.append(section(y, "Contact")); y += STEP
rows.append(kv(y, "X", "@senamakel")); y += STEP
rows.append(kv(y, "Instagram", "@stevenenamakel")); y += STEP
rows.append(kv(y, "Medium", "@enamakel")); y += STEP
rows.append(kv(y, "Linktree", "linktr.ee/enamakel")); y += STEP
y += STEP

rows.append(section(y, "GitHub Stats")); y += STEP
rows.append(kv(y, "Repos", "00", "repo_data_dots", "repo_data")); y += STEP
rows.append(kv(y, "Contributed", "00", "contrib_data_dots", "contrib_data")); y += STEP
rows.append(kv(y, "Stars", "00", "star_data_dots", "star_data")); y += STEP
rows.append(kv(y, "Commits", "0,000", "commit_data_dots", "commit_data")); y += STEP
rows.append(kv(y, "Followers", "00", "follower_data_dots", "follower_data")); y += STEP
rows.append(
    f'<tspan x="{X}" y="{y}"><tspan class="cc">. </tspan>'
    f'<tspan class="key">Lines of Code</tspan>:'
    f'<tspan class="cc"> ( </tspan><tspan class="addColor" id="loc_add">000,000</tspan>'
    f'<tspan class="addColor">++</tspan><tspan class="cc">, </tspan>'
    f'<tspan class="delColor" id="loc_del">00,000</tspan><tspan class="delColor">--</tspan>'
    f'<tspan class="cc"> )</tspan>'
    f'<tspan class="cc" id="loc_data_dots"> ... </tspan><tspan class="value" id="loc_data">000,000</tspan></tspan>'
)
y += STEP

text_block = "\n".join(rows)
line_block = "\n".join(lines)
W = round(RULE_END + 24)

svg = f'''<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {W} {H}" width="{W}px" height="{H}px" font-size="{FONT_SIZE}px">
<style>
@font-face {{
  font-family: 'JBMono';
  font-style: normal;
  font-weight: 400;
  src: url("data:font/woff2;base64,{font_b64}") format('woff2');
}}
svg {{font-family: 'JBMono', 'SF Mono', Menlo, Consolas, monospace;}}
.key {{fill: #ffa657;}}
.value {{fill: #a5d6ff;}}
.addColor {{fill: #3fb950;}}
.delColor {{fill: #f85149;}}
.cc {{fill: #6e7681;}}
text, tspan {{white-space: pre;}}
</style>
<rect width="{W}" height="{H}" fill="{BG}" rx="15"/>
<image id="portrait" x="{PX}" y="{PY}" width="{PW}" height="{PH}" xlink:href="data:image/png;base64,{portrait}"/>
<g id="rules">
{line_block}
</g>
<text id="stats" x="{X}" y="{Y0}" fill="#c9d1d9">
{text_block}
</text>
</svg>
'''

out = os.path.join(HERE, "header.svg")
with open(out, "w", encoding="utf-8") as f:
    f.write(svg)
print(f"wrote {out} ({len(svg)/1024:.0f} KB), card {W}x{H}, portrait {PW}x{PH}, value column RC={RC} @ x={col_px(RC):.0f}")
