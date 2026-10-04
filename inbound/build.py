"""Builds inbound/index.html from page.src.html by inlining the sprite (shapes, trims, truck) from inspo/sprite.svg.
Run:  python inbound/build.py     The sprite's embedded provenance metadata is dropped (it is ~6 KB and unused)."""
import io
import re
from pathlib import Path

here = Path(__file__).resolve().parent
sprite = io.open(here / "assets" / "sprite.svg", encoding="utf-8").read()
sprite = re.sub(r"<metadata>.*?</metadata>", "", sprite, flags=re.S)
sprite = re.sub(r'\sxmlns:c2pa="[^"]*"', "", sprite)
page = io.open(here / "page.src.html", encoding="utf-8").read().replace("<!--SPRITE-->", sprite)
io.open(here / "index.html", "w", encoding="utf-8").write(page)
print(f"index.html: {len(page.encode('utf-8')) / 1024:.0f} KB")
