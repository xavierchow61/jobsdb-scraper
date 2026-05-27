"""JobsDB HK Scraper — Streamlit main page (scrape control + log + outputs).

Settings (Telegram / CV / Master path / advanced) live on the Settings page.
This file keeps the sidebar minimal: source / keyword / location / max_pages.

Run with:
    streamlit run streamlit_app.py
"""

import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

import config as appcfg
import scraper
import theme


# ============================================================
# Worker pipe & thread
# ============================================================

class Args:
    """Plain attribute bag passed into scraper.scrape() (mirrors gui.py)."""


class StreamPipe:
    """File-like that pushes each line into a queue.Queue."""

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


def init_runtime_state():
    ss = st.session_state
    ss.setdefault("worker", None)
    ss.setdefault("stop_event", threading.Event())
    ss.setdefault("log_queue", queue.Queue())
    ss.setdefault("log_lines", [])
    ss.setdefault("running", False)
    ss.setdefault("last_output_path", None)
    ss.setdefault("finished_msg", None)
    ss.setdefault("worker_result", {})
    ss.setdefault("uploaded_cv_path", None)
    ss.setdefault("uploaded_cv_name", None)


def drain_log_queue():
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
    """Worker thread body — redirects stdout into queue, calls scraper.scrape()."""
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


def build_args():
    """Build a scraper-compatible Args object from session_state settings."""
    s = st.session_state
    a = Args()
    a.source = s.s_source
    a.keyword = (s.s_keyword or "").strip() or "Accountant"
    a.location = (s.s_location or "").strip()
    a.max_pages = max(0, int(s.s_max_pages or 0))
    a.full_jd = bool(s.s_full_jd)
    a.delay = max(0.0, float(s.s_delay or 1.5))
    a.output = (s.s_output or "").strip() or None
    a.csv = True
    a.master = (s.s_master or "").strip() if s.s_master_enabled else ""

    # Telegram — Cloud always pulls from secrets, never UI
    tok, chat, _src = appcfg.telegram_credentials()
    a.telegram_enabled = bool(s.s_tg_enabled and tok and chat)
    a.telegram_token = tok
    a.telegram_chat_id = chat
    a.telegram_max = int(s.s_tg_max or 0)
    a.telegram_delay = 1.5
    a.include_actions = bool(s.s_include_actions)
    a.match_threshold = float(s.s_match_threshold or 0)

    # CV: uploaded file (saved by Settings page) wins over path
    a.cv = s.uploaded_cv_path or (s.s_cv_path or "").strip()

    at_text = (s.s_at or "").strip()
    a.at = scraper.parse_at(at_text) if at_text else None
    return a


# ============================================================
# UI
# ============================================================

st.set_page_config(page_title="JobsDB HK 爬蟲", page_icon="🇭🇰", layout="wide")
theme.apply()
appcfg.init_settings()
init_runtime_state()

# ---- Header ----
badge = '<span class="badge">CLOUD</span>' if appcfg.IS_CLOUD else ""
st.markdown(
    f'<div class="app-title">🇭🇰 JobsDB HK 爬蟲 {badge}</div>'
    '<div class="app-subtitle">JobsDB · CTgoodjobs · cpjobs &nbsp;·&nbsp; Telegram + CV match</div>',
    unsafe_allow_html=True,
)

if appcfg.IS_CLOUD:
    st.markdown(
        '<div class="cloud-banner">'
        '☁ <b>Cloud mode</b> · Filesystem ephemeral — 完 scrape 記住按 <b>⬇ 下載</b>。'
        'Semantic CV scoring 已關，keyword matching only.'
        '</div>',
        unsafe_allow_html=True,
    )

# ---- Sidebar: ONLY core scrape params ----
with st.sidebar:
    st.markdown(
        '<div style="font-family:var(--font-mono); font-size:0.65rem; '
        'font-weight:600; letter-spacing:0.6px; text-transform:uppercase; '
        'color:var(--color-text-muted); margin-bottom:6px;">SCRAPE</div>',
        unsafe_allow_html=True,
    )

    st.selectbox(
        "資料來源 Source",
        options=list(scraper.SOURCES),
        key="s_source",
    )

    st.text_input("關鍵字 Keyword", key="s_keyword")

    # Location field is source-dependent
    if st.session_state.s_source == "ctgoodjobs":
        loc_options = [""] + list(scraper.CT_LOCATIONS)
        if st.session_state.s_location not in loc_options:
            st.session_state.s_location = ""
        st.selectbox("地區 Location (CTgoodjobs)", loc_options, key="s_location")
    elif st.session_state.s_source == "cpjobs":
        loc_options = [""] + list(scraper.CP_LOCATIONS)
        if st.session_state.s_location not in loc_options:
            st.session_state.s_location = ""
        st.selectbox("地區 Location (cpjobs · 4 大區)", loc_options, key="s_location")
    else:
        st.text_input("地區 Location (留空 = 全港)", key="s_location")

    st.number_input(
        "最多頁數 (0 = 全部)",
        min_value=0, max_value=999, step=1,
        key="s_max_pages",
    )

    st.markdown(
        f'<div style="margin-top:18px; padding:10px 12px; background:var(--color-surface-alt); '
        f'border:1px solid var(--color-border); border-radius:var(--radius-md); '
        f'font-size:0.75rem; color:var(--color-text-secondary);">'
        f'⚙ 進階設定（Telegram / CV / Master 等）<br>'
        f'<span style="color:var(--color-text-muted);">→ Sidebar 入面點 <b>Settings</b> page</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ---- Control bar ----
ss = st.session_state
ctrl1, ctrl2, ctrl3, ctrl_status = st.columns([1, 1, 1.2, 4])

with ctrl1:
    start_clicked = st.button("▶ 開始", type="primary", disabled=ss.running, use_container_width=True)
with ctrl2:
    stop_clicked = st.button("■ 停止", disabled=not ss.running, use_container_width=True)
with ctrl3:
    clear_clicked = st.button("🧹 清空 Log", disabled=ss.running, use_container_width=True)
with ctrl_status:
    if ss.running:
        chip = '<span class="status-chip running"><span class="dot"></span>執行中</span>'
    elif ss.finished_msg:
        chip = f'<span class="status-chip done"><span class="dot"></span>{ss.finished_msg}</span>'
    else:
        chip = '<span class="status-chip idle"><span class="dot"></span>準備好</span>'
    st.markdown(
        f'<div style="display:flex; align-items:center; height:32px; padding-left:8px;">{chip}</div>',
        unsafe_allow_html=True,
    )

if clear_clicked:
    ss.log_lines = []
    ss.finished_msg = None
    st.rerun()

if start_clicked and not ss.running:
    try:
        args = build_args()
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
st.markdown(
    '<div style="font-family:var(--font-mono); font-size:0.65rem; font-weight:600; '
    'letter-spacing:0.6px; text-transform:uppercase; color:var(--color-text-muted); '
    'margin-top:14px; margin-bottom:4px;">LOG</div>',
    unsafe_allow_html=True,
)
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
        st.markdown(
            '<div style="font-family:var(--font-mono); font-size:0.65rem; font-weight:600; '
            'letter-spacing:0.6px; text-transform:uppercase; color:var(--color-text-muted); '
            'margin-top:18px; margin-bottom:6px;">📂 OUTPUT</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"`{p.name}`")
        try:
            data = p.read_bytes()
            mime = "text/csv" if p.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            st.download_button(f"⬇ 下載 {p.name}", data, file_name=p.name, mime=mime)
        except Exception as e:
            st.warning(f"讀取輸出檔失敗: {e}")

# ---- Master xlsx download + stats ----
if not ss.running:
    master_path = (ss.s_master or "").strip()
    mp = Path(master_path) if master_path else None
    if mp and mp.exists():
        st.markdown(
            '<div style="font-family:var(--font-mono); font-size:0.65rem; font-weight:600; '
            'letter-spacing:0.6px; text-transform:uppercase; color:var(--color-text-muted); '
            'margin-top:18px; margin-bottom:6px;">📊 MASTER DATABASE</div>',
            unsafe_allow_html=True,
        )
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
