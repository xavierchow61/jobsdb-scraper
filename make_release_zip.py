"""Pack the scraper as a release ZIP that can be shared.

Includes: source files, .bat launchers, requirements, industry reference
Excludes: config.json (your bot token), jobs_master.xlsx, CVs,
          bot_state.json, *.csv, *.profile.json, __pycache__, backups
"""
import sys, zipfile
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

INCLUDE = [
    "scraper.py",
    "cv_match.py",
    "gui.pyw",
    "bot_listener.py",
    "requirements.txt",
    "JobsDB Scraper.bat",
    "Start Bot Listener.bat",
    "industry_keywords_reference.xlsx",
    "啟動.bat",
    "SETUP.md",
]


def main():
    out_name = f"jobsdb-scraper_{datetime.now():%Y%m%d}.zip"
    out_path = APP_DIR / out_name
    missing = []
    written = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in INCLUDE:
            src = APP_DIR / name
            if not src.exists():
                missing.append(name)
                continue
            zf.write(src, arcname=f"jobsdb-scraper/{name}")
            written.append(name)
    print(f"Wrote {out_path}")
    print(f"  Included ({len(written)}):")
    for n in written:
        print(f"    • {n}")
    if missing:
        print(f"  ⚠ Missing ({len(missing)}):")
        for n in missing:
            print(f"    • {n}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
