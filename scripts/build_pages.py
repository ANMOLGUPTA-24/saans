"""Publish the dashboard as a static page.

The same web/index.html the API serves, plus the snapshot it reads when
there is no API behind it. One page, two homes, so the published site
and the running engine can never show different numbers.
"""
from __future__ import annotations
import shutil, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"

OUT.mkdir(exist_ok=True)
(OUT / "data").mkdir(exist_ok=True)
shutil.copy2(ROOT / "web" / "index.html", OUT / "index.html")
for f in ("snapshot.json", "delhi_boundary.json"):
    shutil.copy2(ROOT / "data" / f, OUT / "data" / f)
(OUT / ".nojekyll").write_text("")
total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
print(f"docs/ built — {total/1024:.0f} KB")
for p in sorted(OUT.rglob("*")):
    if p.is_file():
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size/1024:.0f} KB")
