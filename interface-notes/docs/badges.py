"""
Generate self-contained SVG badges (no external requests needed).
Run:  python docs/badges.py
Outputs SVG files into docs/badges/
"""
import os, base64

OUT = os.path.join(os.path.dirname(__file__), "badges")
os.makedirs(OUT, exist_ok=True)

# (filename, label, value, label_color, value_color)
BADGES = [
    ("python.svg",    "python", "3.10+",  "#555",    "#3776AB"),
    ("license.svg",   "license", "MIT",   "#555",    "#4FB867"),
    ("status.svg",    "status",  "active","#555",    "#4FB867"),
    ("lang-en.svg",   "lang",    "EN",    "#555",    "#1F6FEB"),
    ("lang-zh.svg",   "lang",    "中文",   "#555",    "#D4380D"),
]

TEMPLATE = '''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20">
  <linearGradient id="a" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <rect rx="3" width="{w}" height="20" fill="#555"/>
  <rect rx="3" x="{split}" width="{wv}" height="20" fill="{vc}"/>
  <rect rx="3" width="{w}" height="20" fill="url(#a)"/>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
    <text x="{x1}" y="14">{label}</text>
    <text x="{x2}" y="14">{value}</text>
  </g>
</svg>'''

def make(label, value, lc, vc):
    lw = max(38, 10 + len(label) * 7)
    vw = max(34, 10 + len(value) * 7)
    total = lw + vw
    split = lw
    return TEMPLATE.format(
        w=total, split=split,
        wv=vw, vc=vc,
        x1=split//2, x2=split + vw//2,
        label=label, value=value,
    )

for fname, label, value, lc, vc in BADGES:
    svg = make(label, value, lc, vc)
    path = os.path.join(OUT, fname)
    with open(path, "w") as f:
        f.write(svg)
    print(f"  ✅ {fname}  ({len(svg)} bytes)")

print(f"\nAll badges written to: {OUT}")
