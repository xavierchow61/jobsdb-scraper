"""ZIP dist_app/ into a single distributable file."""
import sys, zipfile
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SRC = APP_DIR / "dist_app"
OUT = APP_DIR / f"JobsDBScraper_{datetime.now():%Y%m%d}.zip"

if not SRC.exists():
    sys.exit(f"{SRC} not found — run build_exe.py first")

count = 0
total = 0
print(f"Zipping {SRC} → {OUT.name} ...")
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for f in SRC.rglob("*"):
        if f.is_file():
            rel = f.relative_to(SRC.parent)
            zf.write(f, arcname=str(rel))
            count += 1
            total += f.stat().st_size

print(f"  files: {count}")
print(f"  raw:   {total / 1024 / 1024:.0f} MB")
print(f"  zip:   {OUT.stat().st_size / 1024 / 1024:.0f} MB")
print(f"  ->     {OUT}")
