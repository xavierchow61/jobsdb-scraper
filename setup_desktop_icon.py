"""Create a desktop shortcut + icon for JobsDB Scraper GUI.

Run once: python setup_desktop_icon.py
Result:   "JobsDB Scraper" icon appears on your Desktop.
Double-click it → GUI opens.
"""
import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ICON_PATH = APP_DIR / "icon.ico"
TARGET_BAT = APP_DIR / "JobsDB Scraper.bat"


def make_icon():
    """Generate a simple JD icon using Pillow (bundled with torch / transformers)."""
    if ICON_PATH.exists():
        print(f"  icon already exists -> {ICON_PATH.name}")
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  Pillow not installed -- icon will be the default Windows .bat icon.")
        return

    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Rounded square background (gradient-ish)
    d.rounded_rectangle((10, 10, size - 10, size - 10),
                        radius=44, fill=(40, 110, 200, 255))
    # Decorative briefcase shape (simple lines)
    d.rounded_rectangle((58, 100, 198, 200), radius=16, fill=(255, 255, 255, 240))
    d.rectangle((110, 80, 146, 100), fill=(255, 255, 255, 240))
    d.rectangle((120, 145, 136, 165), fill=(40, 110, 200, 255))
    # Try drawing "JD" big text
    font = None
    for name in ("arialbd.ttf", "arial.ttf", "segoeui.ttf", "tahoma.ttf"):
        try:
            font = ImageFont.truetype(name, 60)
            break
        except Exception:
            continue
    if font is not None:
        d.text((size // 2, 230), "JD", font=font,
               fill=(255, 255, 255, 255), anchor="mb")
    # Save as multi-resolution .ico
    img.save(ICON_PATH, format="ICO",
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64),
                    (128, 128), (256, 256)])
    print(f"  icon -> {ICON_PATH}")


def _get_desktop_via_shell():
    """Ask Windows which folder is the *real* Desktop (respects OneDrive redirect)."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetFolderPath('Desktop')"],
            text=True, encoding="utf-8",
        ).strip()
        if out:
            return Path(out)
    except Exception:
        pass
    return None


def make_shortcut():
    # Prefer Windows-reported Desktop (handles OneDrive redirection)
    desktop = _get_desktop_via_shell()
    if desktop is None or not desktop.exists():
        # Fallbacks
        candidates = [
            Path(os.environ.get("OneDrive", "")) / "Desktop"
                if os.environ.get("OneDrive") else None,
            Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Desktop",
            Path(os.environ.get("USERPROFILE", "")) / "Desktop",
        ]
        for cand in candidates:
            if cand and cand.exists():
                desktop = cand
                break
    if desktop is None or not desktop.exists():
        sys.exit("Cannot find Desktop folder.")
    print(f"  desktop -> {desktop}")

    lnk = desktop / "JobsDB Scraper.lnk"
    target = str(TARGET_BAT)
    workdir = str(APP_DIR)
    icon = str(ICON_PATH) if ICON_PATH.exists() else target

    # Build via PowerShell + WScript.Shell COM
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('{lnk}')
$s.TargetPath       = '{target}'
$s.WorkingDirectory = '{workdir}'
$s.IconLocation     = '{icon}'
$s.WindowStyle      = 7
$s.Description      = 'HK Job Scraper - search JobsDB / CTgoodjobs / cpjobs'
$s.Save()
""".strip()

    subprocess.check_call([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps
    ])
    print(f"  shortcut -> {lnk}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if not TARGET_BAT.exists():
        sys.exit(f"Cannot find {TARGET_BAT.name} in {APP_DIR}")
    print("Creating desktop icon for JobsDB Scraper...")
    make_icon()
    make_shortcut()
    print("\nDone! Look at your Desktop -- double-click the JobsDB Scraper icon.")


if __name__ == "__main__":
    main()
