"""Build standalone .exe for distribution.

Produces:
    dist_app/
        JobsDB Scraper/         <- GUI (windowed, no console)
            JobsDBScraper.exe
            _internal/...        <- shared Python + libs
            industry_keywords_reference.xlsx
            SETUP.md
        Bot Listener/            <- Telegram bot listener (console)
            BotListener.exe
            _internal/...

Tested with: PyInstaller 6.x, Python 3.13, torch 2.x, sentence-transformers 5.x.
"""
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
OUT = APP_DIR / "dist_app"


def banner(text):
    print()
    print("=" * 70)
    print(f"  {text}")
    print("=" * 70)


COMMON_FLAGS = [
    "--noconfirm",
    "--clean",
    # Hidden imports / data that PyInstaller cannot auto-discover
    "--collect-data", "sentence_transformers",
    "--collect-data", "tokenizers",
    "--collect-data", "transformers",
    "--collect-data", "curl_cffi",
    "--collect-binaries", "torch",
    "--collect-data", "torch",
    "--collect-submodules", "sentence_transformers",
    "--hidden-import", "openpyxl",
    "--hidden-import", "openpyxl.cell._writer",
    "--hidden-import", "pdfminer",
    "--hidden-import", "pdfminer.high_level",
    "--hidden-import", "cv_match",
    "--hidden-import", "scraper",
    "--exclude-module", "PyQt5",
    "--exclude-module", "PyQt6",
    "--exclude-module", "PySide2",
    "--exclude-module", "PySide6",
]


def build_gui():
    banner("Building GUI (JobsDBScraper.exe)")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "JobsDBScraper",
        "--windowed",
        "--add-data", "industry_keywords_reference.xlsx;.",
        "--add-data", "SETUP.md;.",
        *COMMON_FLAGS,
        "gui.pyw",
    ]
    print("Command:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=APP_DIR)


def build_listener():
    banner("Building Bot Listener (BotListener.exe)")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "BotListener",
        "--console",
        *COMMON_FLAGS,
        "bot_listener.py",
    ]
    print("Command:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=APP_DIR)


def assemble():
    banner("Assembling release folder")
    dist = APP_DIR / "dist"
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    # Copy GUI folder
    if (dist / "JobsDBScraper").exists():
        shutil.copytree(dist / "JobsDBScraper", OUT / "JobsDB Scraper")
    # Copy listener folder
    if (dist / "BotListener").exists():
        shutil.copytree(dist / "BotListener", OUT / "Bot Listener")
    # Copy SETUP.md at top level too
    if (APP_DIR / "SETUP.md").exists():
        shutil.copy(APP_DIR / "SETUP.md", OUT / "SETUP.md")
    # Generate a Start.bat that opens GUI (and reminds about listener)
    (OUT / "1. Open GUI.bat").write_text(
        '@echo off\r\nstart "" "JobsDB Scraper\\JobsDBScraper.exe"\r\n',
        encoding="utf-8",
    )
    (OUT / "2. Start Telegram Bot.bat").write_text(
        '@echo off\r\ncd /d "%~dp0Bot Listener"\r\nBotListener.exe\r\npause\r\n',
        encoding="utf-8",
    )
    print(f"\nRelease ready at: {OUT}")


def main():
    if not (APP_DIR / "gui.pyw").exists():
        sys.exit("gui.pyw missing — run this from the project folder.")
    build_gui()
    # Listener disabled — uncomment to also build it
    # build_listener()
    assemble_gui_only()
    banner("Done!")
    print(f"  ZIP this folder to share:  {OUT}")


def assemble_gui_only():
    banner("Assembling release folder (GUI only)")
    dist = APP_DIR / "dist"
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    if (dist / "JobsDBScraper").exists():
        shutil.copytree(dist / "JobsDBScraper", OUT / "JobsDB Scraper")
    if (APP_DIR / "SETUP.md").exists():
        shutil.copy(APP_DIR / "SETUP.md", OUT / "SETUP.md")
    (OUT / "Open JobsDB Scraper.bat").write_text(
        '@echo off\r\nstart "" "JobsDB Scraper\\JobsDBScraper.exe"\r\n',
        encoding="utf-8",
    )
    print(f"\nRelease ready at: {OUT}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
