"""JobsDB HK Scraper — main dashboard.

Glassmorphism layout inspired by personal-finance-app/Home.py:
  • Gradient title
  • Source selector (top)
  • 4 KPI cards (Master DB stats)
  • 2-column: control & log (left) + source breakdown chart (right)
  • Output download + Master table

Scrape settings live on the Settings page.
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


# Hong Kong's 18 official districts (區) — used as JobsDB's location filter.
# Key  = URL slug value (英文，scraper.build_search_url 會 hyphenate)
# Value = display label (中文，按港島/九龍/新界分組)
JOBSDB_DISTRICTS = {
    "": "全港（不限地區）",
    # 港島 4 區
    "Central and Western District": "中西區（港島）",
    "Wan Chai District":            "灣仔區（港島）",
    "Eastern District":             "東區（港島）",
    "Southern District":            "南區（港島）",
    # 九龍 5 區
    "Yau Tsim Mong District":       "油尖旺區（九龍）",
    "Sham Shui Po District":        "深水埗區（九龍）",
    "Kowloon City District":        "九龍城區（九龍）",
    "Wong Tai Sin District":        "黃大仙區（九龍）",
    "Kwun Tong District":           "觀塘區（九龍）",
    # 新界 9 區
    "Kwai Tsing District":          "葵青區（新界）",
    "Tsuen Wan District":           "荃灣區（新界）",
    "Tuen Mun District":            "屯門區（新界）",
    "Yuen Long District":           "元朗區（新界）",
    "Northern District":            "北區（新界）",
    "Tai Po District":              "大埔區（新界）",
    "Sha Tin District":             "沙田區（新界）",
    "Sai Kung District":            "西貢區（新界）",
    "Islands District":             "離島區（新界）",
}


# ============================================================
# Worker pipe & thread (unchanged from prior version)
# ============================================================

class Args:
    pass


class StreamPipe:
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
    ss.setdefault("finished_kind", "done")
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

    tok, chat, _src = appcfg.telegram_credentials()
    a.telegram_enabled = bool(s.s_tg_enabled and tok and chat)
    a.telegram_token = tok
    a.telegram_chat_id = chat
    a.telegram_max = int(s.s_tg_max or 0)
    a.telegram_delay = 1.5
    a.include_actions = bool(s.s_include_actions)
    a.match_threshold = float(s.s_match_threshold or 0)

    a.cv = s.uploaded_cv_path or (s.s_cv_path or "").strip()

    at_text = (s.s_at or "").strip()
    a.at = scraper.parse_at(at_text) if at_text else None
    return a


# ============================================================
# UI
# ============================================================

st.set_page_config(
    page_title="JOB RADAR",
    page_icon="🎯",
    layout="wide",
    # "auto" lets Streamlit collapse the sidebar on mobile / narrow viewports.
    # Hard-coding "expanded" forces it open on phones, where it overlays
    # the main content and looks like the sidebar is "blocking" the page.
    initial_sidebar_state="auto",
)
theme.apply()
theme.render_sidebar_nav()
appcfg.init_settings()
init_runtime_state()
ss = st.session_state

# ---- Header ----
theme.glass_title(
    "JOB RADAR",
    emoji="🎯",
    subtitle="一鍵抓取 JobsDB · CTgoodjobs · cpjobs，配 Telegram 通知 + CV 比對",
    badge="雲端" if appcfg.IS_CLOUD else "本機",
)

if appcfg.IS_CLOUD:
    st.markdown(
        theme.cloud_banner_html(
            "☁ <b>雲端模式</b> · 檔案系統重啟即清 — "
            "完成爬取後記住按 <b>⬇ 下載</b> 儲低。"
            "CV 語意比對已關閉，只用關鍵字配對。"
        ),
        unsafe_allow_html=True,
    )

# ---- JobsDB-style filter pill: 來源 | 關鍵字 | 地區 | 頁數 ----
col_src, col_kw, col_loc, col_pg = st.columns([1.1, 1.6, 1.6, 0.9])
with col_src:
    st.selectbox(
        "🏷 來源",
        options=list(scraper.SOURCES),
        key="s_source",
        help="揀邊個求職網爬",
    )
with col_kw:
    st.text_input(
        "🔍 關鍵字",
        key="s_keyword",
        placeholder="例如：Accountant",
    )
with col_loc:
    fmt_district = lambda x: x if x else "全港"
    if ss.s_source == "ctgoodjobs":
        loc_options = [""] + list(scraper.CT_LOCATIONS)
        if ss.s_location not in loc_options:
            ss.s_location = ""
        st.selectbox("📍 地區", loc_options, key="s_location",
                     format_func=fmt_district,
                     help="CTgoodjobs 全港所有地區")
    elif ss.s_source == "cpjobs":
        loc_options = [""] + list(scraper.CP_LOCATIONS)
        if ss.s_location not in loc_options:
            ss.s_location = ""
        st.selectbox("📍 地區", loc_options, key="s_location",
                     format_func=fmt_district,
                     help="cpjobs 只支援 4 大區")
    else:  # jobsdb
        jobsdb_keys = list(JOBSDB_DISTRICTS.keys())
        if ss.s_location not in jobsdb_keys:
            ss.s_location = ""
        st.selectbox(
            "📍 地區",
            jobsdb_keys,
            key="s_location",
            format_func=lambda x: JOBSDB_DISTRICTS[x],
            help="香港 18 區（JobsDB 官方篩選層級）",
        )
with col_pg:
    st.number_input(
        "📄 頁數",
        min_value=0, max_value=999, step=1,
        key="s_max_pages",
        help="0 = 全部頁",
    )

# Pre-warn: JobsDB blocks Streamlit Cloud's datacenter IPs (HTTP 403)
if ss.s_source == "jobsdb" and appcfg.IS_CLOUD:
    st.markdown(
        theme.cloud_banner_html(
            "⚠ <b>JobsDB 喺雲端通常會 block</b>（HTTP 403 Forbidden）— "
            "JobsDB 對 datacenter IP 比較嚴。建議揀 <b>cpjobs</b> 或 "
            "<b>ctgoodjobs</b>（佢哋通常 OK），或者本機跑 Streamlit 用住宅 IP。"
        ),
        unsafe_allow_html=True,
    )

# ---- KPI cards (Master DB stats) ----
master_path = (ss.s_master or "").strip()
mp = Path(master_path) if master_path else None
stats = None
if mp and mp.exists() and not ss.running:
    try:
        stats = scraper.master_stats(mp)
    except Exception:
        stats = None

c1, c2, c3, c4 = st.columns(4)
theme.kpi_card(c1, "工作總數", stats["total"] if stats else 0,
               color=theme.PALETTE["accent"], emoji="📊")
theme.kpi_card(c2, "已儲存", stats["saved"] if stats else 0,
               color=theme.PALETTE["warning"], emoji="⭐")
theme.kpi_card(c3, "已申請", stats["applied"] if stats else 0,
               color=theme.PALETTE["success"], emoji="✅")
theme.kpi_card(c4, "已隱藏", stats["hidden"] if stats else 0,
               color=theme.PALETTE["red"], emoji="🚫")

st.write("")

# ---- Control bar ----
theme.section_label("⚡ 爬蟲控制")
ctrl1, ctrl2, ctrl3, ctrl_status = st.columns([1, 1, 1.2, 4])
with ctrl1:
    start_clicked = st.button("▶ 開始", type="primary", disabled=ss.running, use_container_width=True)
with ctrl2:
    stop_clicked = st.button("■ 停止", disabled=not ss.running, use_container_width=True)
with ctrl3:
    clear_clicked = st.button("🧹 清空 Log", disabled=ss.running, use_container_width=True)
with ctrl_status:
    if ss.running:
        chip = theme.status_chip("執行中", "running")
    elif ss.finished_msg:
        kind = ss.get("finished_kind", "done")
        chip = theme.status_chip(ss.finished_msg, kind)
    else:
        chip = theme.status_chip("準備好", "idle")
    st.markdown(
        f'<div style="display:flex;align-items:center;height:38px;padding-left:10px;">{chip}</div>',
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

# ---- Log (full width) ----
theme.section_label("📜 日誌")
log_box = st.empty()
drain_log_queue()
done = False
if ss.log_lines and ss.log_lines[-1] == "__DONE__":
    ss.log_lines.pop()
    done = True
log_box.code("\n".join(ss.log_lines[-500:]) or "(尚未開始)", language="log")

# ---- Poll while running ----
if ss.running:
    if done or (ss.worker is not None and not ss.worker.is_alive()):
        ss.running = False
        # Scan log for site-block / error patterns to set status colour
        log_text = "\n".join(ss.log_lines)
        if "HTTP 403" in log_text:
            ss.finished_msg = "已被封鎖 (HTTP 403)"
            ss.finished_kind = "warning"
            # Append a tip into the log for visibility
            ss.log_lines.append("")
            ss.log_lines.append("💡 提示：JobsDB 對 datacenter IP 嚴格。試下用 cpjobs 或 ctgoodjobs，或本機跑。")
        elif "HTTP 4" in log_text or "HTTP 5" in log_text:
            ss.finished_msg = "完成（有錯誤）"
            ss.finished_kind = "warning"
        elif "✗" in log_text or "ERROR:" in log_text:
            ss.finished_msg = "完成（有錯誤）"
            ss.finished_kind = "warning"
        else:
            ss.finished_msg = f"完成 {datetime.now():%H:%M:%S}"
            ss.finished_kind = "done"
        ss.last_output_path = ss.get("worker_result", {}).get("output_path")
        st.rerun()
    else:
        time.sleep(0.4)
        st.rerun()

# ---- Output download ----
if not ss.running and ss.last_output_path:
    p = Path(ss.last_output_path)
    if p.exists():
        theme.section_label("📂 今次輸出")
        theme.glass_card_open()
        try:
            data = p.read_bytes()
            mime = "text/csv" if p.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            sz_kb = len(data) / 1024
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:12px;">'
                f'<div style="font-family:{theme.FONTS["mono"]};font-size:0.85rem;'
                f'color:{theme.PALETTE["subtext"]};flex:1;">📄 <b>{p.name}</b>'
                f'<span style="color:{theme.PALETTE["muted"]};margin-left:8px;">{sz_kb:.1f} KB</span></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                f"⬇ 下載 {p.name}", data, file_name=p.name, mime=mime,
                use_container_width=False,
            )
        except Exception as e:
            st.warning(f"讀取輸出檔失敗: {e}")
        theme.glass_card_close()

