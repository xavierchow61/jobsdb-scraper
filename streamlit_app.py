"""JobsDB HK Scraper - Streamlit web UI.

Mirrors gui.py functionality but in a browser. Imports scraper.py untouched.

Run with:
    streamlit run streamlit_app.py
"""

import json
import os
import queue
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

import scraper
import theme

CONFIG_PATH = Path(__file__).parent / "config.json"

# Streamlit Cloud puts the repo at /mount/src and the FS is ephemeral.
# Detect that and route the master xlsx to /tmp so writes succeed,
# but warn the user the file won't survive a restart.
IS_CLOUD = (
    "/mount/src" in str(Path(__file__).resolve())
    or os.getenv("STREAMLIT_RUNTIME_ENV") == "cloud"
)
DEFAULT_MASTER = (
    Path("/tmp/jobs_master.xlsx") if IS_CLOUD
    else Path(__file__).parent / "jobs_master.xlsx"
)


def _secret(section, key, default=""):
    """Read st.secrets[section][key] without raising if missing."""
    try:
        return st.secrets[section][key]
    except (KeyError, FileNotFoundError, AttributeError):
        return default


class Args:
    """Mirror of gui.py's Args — a plain bag of attributes for scraper.scrape()."""


class StreamPipe:
    """File-like that pushes each line into a queue.Queue (same idea as gui.py:GuiPipe)."""

    def __init__(self, q):
        self.q = q
        self.buf = ""

    def write(self, s):
        if not s:
            return
        self.buf += s
        while "\n" in self.buf or "\r" in self.buf:
            nl = self.buf.find("\n")
            cr = self.buf.find("\r")
            if nl == -1:
                idx, sep = cr, "\r"
            elif cr == -1:
                idx, sep = nl, "\n"
            else:
                idx, sep = (nl, "\n") if nl < cr else (cr, "\r")
            line = self.buf[:idx]
            self.buf = self.buf[idx + 1:]
            if line.strip():
                self.q.put((line.rstrip(), sep == "\r"))

    def flush(self):
        pass


def load_config():
    """Merge precedence: st.secrets > config.json > built-in defaults.

    On Streamlit Cloud config.json is absent (gitignored); secrets fill it in.
    Locally, config.json wins unless secrets.toml exists.
    """
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    # Overlay Telegram secrets if present
    tg_token = _secret("telegram", "token")
    tg_chat = _secret("telegram", "chat_id")
    if tg_token:
        cfg["tg_token"] = tg_token
        cfg.setdefault("tg_enabled", True)
    if tg_chat:
        cfg["tg_chat"] = tg_chat
    # Overlay form defaults from secrets
    for k in ("source", "keyword", "location", "max_pages", "delay", "full_jd", "match_threshold"):
        v = _secret("defaults", k, None)
        if v is not None and k not in cfg:
            cfg[k] = v
    return cfg


def is_cloud_mode():
    return IS_CLOUD


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        st.warning(f"無法寫入 config.json: {e}")


def init_state():
    ss = st.session_state
    ss.setdefault("worker", None)
    ss.setdefault("stop_event", threading.Event())
    ss.setdefault("log_queue", queue.Queue())
    ss.setdefault("log_lines", [])
    ss.setdefault("running", False)
    ss.setdefault("last_output_path", None)
    ss.setdefault("finished_msg", None)


def drain_log_queue():
    """Pull whatever the worker thread has written into log_lines."""
    ss = st.session_state
    while True:
        try:
            line, overwrite = ss.log_queue.get_nowait()
        except queue.Empty:
            return
        if overwrite and ss.log_lines:
            ss.log_lines[-1] = line
        else:
            ss.log_lines.append(line)


def run_scrape(args, q, stop_event, result):
    """Worker thread body — redirects stdout into the queue, calls scraper.scrape().

    `result` is a dict shared with the main thread for return values
    (avoids touching st.session_state from a background thread).
    """
    old_stdout = sys.stdout
    sys.stdout = StreamPipe(q)
    try:
        if args.at:
            scraper.wait_until(args.at, stop_event=stop_event)
            if stop_event.is_set():
                print("已取消（未開始爬）")
                return
        path = scraper.scrape(args, stop_event=stop_event)
        if path:
            result["output_path"] = str(path)
    except Exception as e:
        print(f"✗ 錯誤: {e}")
    finally:
        sys.stdout = old_stdout
        q.put(("__DONE__", False))


def build_args(form, uploaded_cv):
    """Translate the Streamlit form dict into a scraper-compatible Args object."""
    a = Args()
    a.source = form["source"]
    a.keyword = form["keyword"].strip() or "Accountant"
    a.location = form["location"].strip()
    a.max_pages = max(0, int(form["max_pages"]))
    a.full_jd = bool(form["full_jd"])
    a.delay = max(0.0, float(form["delay"]))
    a.output = form["output"].strip() or None
    a.csv = True
    a.master = form["master"].strip() if form["master_enabled"] else ""

    a.telegram_enabled = bool(form["tg_enabled"])
    a.telegram_token = form["tg_token"].strip()
    a.telegram_chat_id = form["tg_chat"].strip()
    a.telegram_max = int(form["tg_max"] or 0)
    a.telegram_delay = 1.5
    a.include_actions = bool(form["include_actions"])
    a.match_threshold = float(form["match_threshold"] or 0)

    # CV: prefer freshly uploaded file, fallback to path in config
    if uploaded_cv is not None:
        suffix = Path(uploaded_cv.name).suffix or ".pdf"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded_cv.getvalue())
        tmp.close()
        a.cv = tmp.name
    else:
        a.cv = form["cv_path"].strip()

    at_text = form["at"].strip()
    a.at = scraper.parse_at(at_text) if at_text else None
    return a


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------

st.set_page_config(page_title="JobsDB HK 爬蟲", page_icon="🇭🇰", layout="wide")
theme.apply()
init_state()
cfg = load_config()

st.title("JobsDB HK 爬蟲")
st.caption("Hong Kong job aggregator · JobsDB / CTgoodjobs / cpjobs · Telegram + CV match")

if IS_CLOUD:
    st.warning(
        "☁ **Cloud mode** — Streamlit Cloud filesystem 係 ephemeral，"
        "`jobs_master.xlsx` **唔會 persist**。每次 scrape 完記住按下面 **⬇ 下載 Master** 儲低。"
        "另外 semantic CV scoring 已關閉（pkg 太重）— 只用 keyword matching。"
    )

# ---- Sidebar form ----
with st.sidebar:
    st.header("爬蟲設定")

    source = st.selectbox(
        "資料來源 Source",
        options=list(scraper.SOURCES),
        index=list(scraper.SOURCES).index(cfg.get("source", "jobsdb")) if cfg.get("source") in scraper.SOURCES else 0,
    )

    keyword = st.text_input("關鍵字 Keyword", value=cfg.get("keyword", "Accountant"))

    # Location picker depends on source
    if source == "ctgoodjobs":
        loc_options = [""] + scraper.CT_LOCATIONS
        loc_default = cfg.get("location", "")
        loc_idx = loc_options.index(loc_default) if loc_default in loc_options else 0
        location = st.selectbox("地區 Location (CTgoodjobs)", loc_options, index=loc_idx)
    elif source == "cpjobs":
        loc_options = [""] + scraper.CP_LOCATIONS
        loc_default = cfg.get("location", "")
        loc_idx = loc_options.index(loc_default) if loc_default in loc_options else 0
        location = st.selectbox("地區 Location (cpjobs — 只支援 4 大區)", loc_options, index=loc_idx)
    else:
        location = st.text_input("地區 Location (JobsDB — 留空 = 全港)", value=cfg.get("location", ""))

    col1, col2 = st.columns(2)
    with col1:
        max_pages = st.number_input("最多頁數 (0 = 全部)", min_value=0, max_value=999, value=int(cfg.get("max_pages", 0) or 0), step=1)
    with col2:
        delay = st.number_input("Request 間隔 (秒)", min_value=0.5, max_value=10.0, value=float(cfg.get("delay", 1.5) or 1.5), step=0.5)

    full_jd = st.checkbox("抓取完整 JD（Responsibilities / Requirements 自動分段）", value=bool(cfg.get("full_jd", True)))

    at = st.text_input("定時開始（HH:MM 或 YYYY-MM-DD HH:MM，留空 = 即刻）", value="")

    with st.expander("📂 輸出 / Master"):
        output = st.text_input("Per-run CSV 路徑（留空 = 自動命名）", value="")
        master_enabled = st.checkbox("寫入 Master xlsx", value=bool(cfg.get("master_enabled", True)))
        master = st.text_input("Master xlsx 路徑", value=cfg.get("master", str(DEFAULT_MASTER)))

    with st.expander("🎯 CV Match Scoring"):
        uploaded_cv = st.file_uploader("上傳 CV（PDF / TXT）", type=["pdf", "txt"])
        cv_path = st.text_input("或者用本地 CV 路徑", value=cfg.get("cv", ""))
        match_threshold = st.number_input(
            "Telegram 推送 Match Score 下限 (0–100)",
            min_value=0.0, max_value=100.0,
            value=float(cfg.get("match_threshold", 0) or 0), step=5.0,
        )

    with st.expander("📨 Telegram 通知"):
        tg_enabled = st.checkbox("啟用 Telegram 即時通知", value=bool(cfg.get("tg_enabled", False)))
        tg_token = st.text_input("Bot Token", value=cfg.get("tg_token", ""), type="password")
        tg_chat = st.text_input("Chat ID", value=cfg.get("tg_chat", ""))
        tg_max = st.number_input("最多推送幾多條（0 = 無上限）", min_value=0, max_value=9999, value=int(cfg.get("tg_max", 0) or 0), step=1)
        include_actions = st.checkbox("加 Save / Hide / Apply 按鈕（需 bot_listener.py 運行）", value=False)
        if st.button("🔔 Test Telegram"):
            ok, msg = scraper.telegram_test_ping(tg_token.strip(), tg_chat.strip())
            (st.success if ok else st.error)(msg)

    if st.button("💾 儲存設定到 config.json"):
        save_config({
            "source": source, "keyword": keyword, "location": location,
            "max_pages": str(max_pages), "full_jd": full_jd, "delay": str(delay),
            "master": master, "master_enabled": master_enabled,
            "tg_token": tg_token, "tg_chat": tg_chat, "tg_enabled": tg_enabled,
            "tg_max": str(tg_max), "cv": cv_path,
            "match_threshold": str(match_threshold),
        })
        st.success("已儲存到 config.json")

form = dict(
    source=source, keyword=keyword, location=location,
    max_pages=max_pages, delay=delay, full_jd=full_jd, at=at,
    output=output, master=master, master_enabled=master_enabled,
    cv_path=cv_path, match_threshold=match_threshold,
    tg_enabled=tg_enabled, tg_token=tg_token, tg_chat=tg_chat,
    tg_max=tg_max, include_actions=include_actions,
)

# ---- Control bar ----
ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1, 3])
ss = st.session_state

with ctrl1:
    start_clicked = st.button("▶ 開始", type="primary", disabled=ss.running, use_container_width=True)
with ctrl2:
    stop_clicked = st.button("■ 停止", disabled=not ss.running, use_container_width=True)
with ctrl3:
    clear_clicked = st.button("🧹 清空 Log", disabled=ss.running, use_container_width=True)
with ctrl4:
    if ss.running:
        st.info("執行中…")
    elif ss.finished_msg:
        st.success(ss.finished_msg)
    else:
        st.caption("準備好")

if clear_clicked:
    ss.log_lines = []
    ss.finished_msg = None
    st.rerun()

if start_clicked and not ss.running:
    try:
        args = build_args(form, uploaded_cv)
    except Exception as e:
        st.error(f"參數錯誤: {e}")
        st.stop()

    ss.log_lines = []
    ss.finished_msg = None
    ss.last_output_path = None
    ss.log_queue = queue.Queue()
    ss.stop_event = threading.Event()
    ss.log_lines.append(f"關鍵字: {args.keyword}  |  Source: {args.source}  |  Location: {args.location or '(無)'}")
    ss.log_lines.append(f"最多頁數: {'全部' if args.max_pages == 0 else args.max_pages}  |  完整 JD: {'是' if args.full_jd else '否'}  |  Delay: {args.delay}s")
    if args.at:
        ss.log_lines.append(f"預定 {args.at:%Y-%m-%d %H:%M:%S} 開始")
    ss.log_lines.append("-" * 60)
    ss.running = True
    ss.worker_result = {}
    ss.worker = threading.Thread(
        target=run_scrape,
        args=(args, ss.log_queue, ss.stop_event, ss.worker_result),
        daemon=True,
    )
    ss.worker.start()
    st.rerun()

if stop_clicked and ss.running:
    ss.stop_event.set()
    ss.log_lines.append(">>> 停止訊號已發送，等緊收尾…")

# ---- Log display ----
st.subheader("日誌 Log")
log_box = st.empty()

drain_log_queue()

# Detect worker completion sentinel
done = False
if ss.log_lines and ss.log_lines[-1] == "__DONE__":
    ss.log_lines.pop()
    done = True

log_box.code("\n".join(ss.log_lines[-500:]) or "(尚未開始)", language="log")

# ---- Poll while running ----
if ss.running:
    if done or (ss.worker is not None and not ss.worker.is_alive()):
        ss.running = False
        ss.finished_msg = f"完成 — {datetime.now():%H:%M:%S}"
        ss.last_output_path = ss.get("worker_result", {}).get("output_path")
        st.rerun()
    else:
        time.sleep(0.4)
        st.rerun()

# ---- Output download ----
if not ss.running and ss.last_output_path:
    p = Path(ss.last_output_path)
    if p.exists():
        st.divider()
        st.subheader("📂 輸出")
        st.write(f"檔案: `{p}`")
        try:
            data = p.read_bytes()
            mime = "text/csv" if p.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            st.download_button(f"⬇ 下載 {p.name}", data, file_name=p.name, mime=mime)
        except Exception as e:
            st.warning(f"讀取輸出檔失敗: {e}")

# ---- Master xlsx download + stats ----
if not ss.running:
    mp = Path(master) if master else None
    if mp and mp.exists():
        st.divider()
        st.subheader("📊 Master xlsx")
        try:
            stats = scraper.master_stats(mp)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total jobs", stats["total"])
            c2.metric("Saved", stats["saved"])
            c3.metric("Applied", stats["applied"])
            c4.metric("Hidden", stats["hidden"])
            if stats["sources"]:
                st.caption("By source: " + ", ".join(f"{k}={v}" for k, v in stats["sources"].items()))
            if stats["latest_scrape"]:
                st.caption(f"Latest scrape: {stats['latest_scrape']}")
            data = mp.read_bytes()
            st.download_button(
                f"⬇ 下載 {mp.name}", data, file_name=mp.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.warning(f"讀取 master 失敗: {e}")
