"""JOB RADAR — single-page wizard layout (5 sub-tabs).

  Tab 1  📄 上傳 CV          — Upload + auto-extract + edit keywords
  Tab 2  🎯 比對分數         — Match score threshold for Telegram push
  Tab 3  📨 Telegram 通知   — Bot status, enable toggle, test ping
  Tab 4  🔍 搜尋 & 開始       — Source / keyword / location / pages + advanced + start
  Tab 5  📊 結果 & 日誌      — KPIs + live log + output downloads

Single page means session_state preserves everything without page-nav
URL/localStorage gymnastics — clean fix for the persistence problem.
"""

import queue
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

import auth
import config as appcfg
import scraper
import theme

try:
    import cv_match
except ImportError:
    cv_match = None

try:
    import telegram_cards
except ImportError:
    telegram_cards = None


# JobsDB hidden — Cloud datacenter IPs get HTTP 403 from hk.jobsdb.com.
# CLI / local can still use `--source jobsdb`.
UI_SOURCES = ("cpjobs", "ctgoodjobs")


# ============================================================
# Worker pipe & thread
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


def _post_scrape_send_paginated(args, csv_path):
    """After scrape, read the per-run CSV and send ONE paginated Telegram
    card (instead of N individual messages). Requires Supabase to be
    configured and the scrape to have produced new rows.
    """
    if telegram_cards is None:
        print("  [tg-cards] module not loaded; skipping paginated send")
        return
    if not args.telegram_token or not args.telegram_chat_id:
        return

    # Use SERVICE_ROLE client for the post-scrape write.
    # Reasoning: this function runs in a worker thread where the user's
    # auth context (auth.set_session token) doesn't reliably propagate
    # to supabase-py's PostgREST calls. RLS would then see auth.uid()
    # = NULL and reject the insert. We explicitly tag the row with
    # user_id so per-user isolation is preserved by data convention
    # even though RLS is bypassed.
    sb_url, sb_service = appcfg.supabase_service_credentials()
    if not (sb_url and sb_service):
        print("  [tg-cards] Supabase service_role 未設定，跳過 paginated 推送")
        return
    sup = telegram_cards.supabase_client(sb_url, sb_service)
    if sup is None:
        return

    user = auth.get_user()
    user_id = user["id"] if user else None

    # Read the per-run CSV — these are exactly the jobs scraped this run
    import csv as _csv
    from pathlib import Path as _P
    p = _P(str(csv_path)) if csv_path else None
    if not p or not p.exists():
        print("  [tg-cards] 無 per-run CSV，跳過")
        return
    try:
        with open(p, "r", encoding="utf-8-sig", newline="") as fh:
            rows = list(_csv.DictReader(fh))
    except Exception as e:
        print(f"  [tg-cards] CSV 讀取失敗: {e}")
        return
    if not rows:
        print("  [tg-cards] CSV 為空，跳過")
        return

    # Apply match-threshold filter (mirroring scraper.process_new_row logic)
    threshold = float(getattr(args, "match_threshold", 0) or 0)
    if threshold > 0:
        kept = []
        for r in rows:
            try:
                s = float(r.get("Match Score") or 0)
            except (TypeError, ValueError):
                s = 0
            if s >= threshold:
                kept.append(r)
        skipped = len(rows) - len(kept)
        if skipped:
            print(f"  [tg-cards] {skipped} 條低於下限 {threshold:.0f}，已過濾")
        rows = kept
    if not rows:
        print(f"  [tg-cards] 無工作達到下限，0 通知")
        return

    # Apply telegram_max cap (mirror scraper)
    limit = int(getattr(args, "telegram_max", 0) or 0)
    if limit > 0:
        rows = rows[:limit]

    # Auto-link Telegram chat_id ↔ Supabase user_id so the bot_listener
    # can identify the user when Save / Hide / Apply buttons are clicked
    if user_id and args.telegram_chat_id:
        try:
            sup.table("user_telegram").upsert({
                "user_id": str(user_id),
                "chat_id": str(args.telegram_chat_id),
            }).execute()
        except Exception as e:
            print(f"  [tg-cards] could not save user→chat mapping: {e}")

    batch_id, msg_id = telegram_cards.create_and_send_batch(
        sup, args.telegram_token, args.telegram_chat_id,
        rows, args.source, user_id=user_id,
    )
    if msg_id:
        print(f"  [tg-cards] ✓ 已推送 paginated card (batch={batch_id}, jobs={len(rows)})")
    else:
        print(f"  [tg-cards] ✗ paginated 推送失敗")


def run_scrape(args, q, stop_event, result):
    old_stdout = sys.stdout
    sys.stdout = StreamPipe(q)
    # Disable scraper's per-row Telegram — we'll send ONE paginated card
    # after scrape finishes (paginated_card flow). Keep token/chat for
    # threshold/max bookkeeping inside scraper, but skip the per-row send.
    wanted_tg = bool(getattr(args, "telegram_enabled", False))
    args.telegram_enabled = False
    try:
        if args.at:
            scraper.wait_until(args.at, stop_event=stop_event)
            if stop_event.is_set():
                print("已取消（尚未開始爬取）")
                return
        path = scraper.scrape(args, stop_event=stop_event)
        if path:
            result["output_path"] = str(path)

        # Re-enable for the paginated send + actually send
        if wanted_tg:
            args.telegram_enabled = True
            try:
                _post_scrape_send_paginated(args, path)
            except Exception as e:
                print(f"  [tg-cards] 推送階段錯誤: {e}")
    except Exception as e:
        print(f"✗ 錯誤: {e}")
    finally:
        sys.stdout = old_stdout
        q.put(("__DONE__", False))


def persist_cv_keywords():
    """Save edited keywords as .profile.json next to the CV so cv_match
    reads our edits instead of auto-extracting on each scrape."""
    if cv_match is None:
        return
    cv_path = (
        st.session_state.get("uploaded_cv_path")
        or (st.session_state.get("s_cv_path") or "").strip()
    )
    if not cv_path or not Path(cv_path).exists():
        return
    edited = st.session_state.get("cv_keywords") or []
    if not edited:
        return
    try:
        profile = cv_match.CVProfile(
            keywords=set(edited),
            years=st.session_state.get("cv_years"),
            raw_chars=0,
            source_path=cv_path,
        )
        cv_match.save_profile(profile)
    except Exception as e:
        print(f"  [CV] could not save edited keywords: {e}")


def build_args():
    s = st.session_state
    a = Args()
    a.source = s.get("s_source", "cpjobs")
    a.keyword = (s.get("s_keyword") or "").strip() or "Accountant"
    a.location = (s.get("s_location") or "").strip()
    a.max_pages = max(0, int(s.get("s_max_pages") or 0))
    a.full_jd = bool(s.get("s_full_jd", True))
    a.delay = max(0.0, float(s.get("s_delay") or 1.5))
    a.output = (s.get("s_output") or "").strip() or None
    a.csv = True
    a.master = (s.get("s_master") or "").strip() if s.get("s_master_enabled") else ""

    # Per-user Telegram credentials (from Supabase user_settings)
    user_settings = auth.get_user_settings()
    tok = (user_settings.get("telegram_token") or "").strip()
    chat = (user_settings.get("telegram_chat_id") or "").strip()
    a.telegram_enabled = bool(s.get("s_tg_enabled") and tok and chat)
    a.telegram_token = tok
    a.telegram_chat_id = chat
    a.telegram_max = int(s.get("s_tg_max") or 0)
    a.telegram_delay = 1.5
    a.include_actions = bool(s.get("s_include_actions"))
    a.match_threshold = float(s.get("s_match_threshold") or 0)

    a.cv = s.get("uploaded_cv_path") or (s.get("s_cv_path") or "").strip()

    at_text = (s.get("s_at") or "").strip()
    a.at = scraper.parse_at(at_text) if at_text else None
    return a


# ============================================================
# Page setup
# ============================================================

st.set_page_config(
    page_title="JOB RADAR",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)
theme.apply()
theme.render_sidebar_nav()
auth.init_session()


# ============================================================
# Auth gate — show login UI when not logged in, halt rest of script
# ============================================================
if not auth.is_logged_in():
    theme.glass_title(
        "JOB RADAR",
        emoji="🎯",
        subtitle="香港求職爬蟲 · 請登入或註冊以使用",
    )
    _l, mid, _r = st.columns([1, 2, 1])
    with mid:
        tab_login, tab_signup, tab_reset = st.tabs(
            ["🔓 登入", "✨ 註冊", "🔑 忘記密碼"]
        )

        with tab_login:
            with st.form("login_form"):
                em = st.text_input("Email", placeholder="you@example.com",
                                   key="login_email")
                pw = st.text_input("Password", type="password",
                                   placeholder="密碼", key="login_pw")
                if st.form_submit_button("登入", type="primary",
                                          use_container_width=True):
                    if not em or not pw:
                        st.error("請填 email 同密碼")
                    else:
                        ok, msg = auth.login(em, pw)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        with tab_signup:
            with st.form("signup_form"):
                em = st.text_input("Email", placeholder="you@example.com",
                                   key="signup_email")
                pw = st.text_input("Password", type="password",
                                   placeholder="密碼（至少 6 位）",
                                   key="signup_pw")
                pw2 = st.text_input("Confirm", type="password",
                                    placeholder="再輸入密碼",
                                    key="signup_pw2")
                if st.form_submit_button("✨ 註冊", type="primary",
                                          use_container_width=True):
                    if not em or not pw:
                        st.error("請填 email 同密碼")
                    elif pw != pw2:
                        st.error("兩次密碼不同")
                    else:
                        ok, msg = auth.signup(em, pw)
                        if ok:
                            st.success(msg)
                            if auth.is_logged_in():
                                st.rerun()
                        else:
                            st.error(msg)

        with tab_reset:
            with st.form("reset_form"):
                em = st.text_input("Email", placeholder="你註冊嘅 email",
                                   key="reset_email")
                if st.form_submit_button("📧 寄重設密碼連結",
                                          use_container_width=True):
                    if em:
                        ok, msg = auth.reset_password(em)
                        (st.success if ok else st.error)(msg)

    st.stop()


# ============================================================
# Logged-in users only — main app
# ============================================================
appcfg.init_settings()
init_runtime_state()
ss = st.session_state
user = auth.get_user()

# Header with user info + logout
hc1, hc2 = st.columns([5, 1])
with hc1:
    theme.glass_title(
        "JOB RADAR",
        emoji="🎯",
        subtitle="一鍵抓取 JobsDB · CTgoodjobs · cpjobs，配 Telegram 通知 + CV 比對",
        badge="雲端" if appcfg.IS_CLOUD else "本機",
    )
with hc2:
    st.markdown(
        f'<div style="margin-top:18px;text-align:right;font-size:0.78rem;'
        f'color:{theme.PALETTE["muted"]};">'
        f'👤 {user["email"]}</div>',
        unsafe_allow_html=True,
    )
    if st.button("🚪 登出", key="logout_btn", use_container_width=True):
        auth.logout()
        st.rerun()

if appcfg.IS_CLOUD:
    st.markdown(
        theme.cloud_banner_html(
            "☁ <b>雲端模式</b> · 檔案系統重啟即清空 — "
            "完成爬取後請按 <b>⬇ 下載</b> 儲存。"
            "CV 語意比對已關閉，僅使用關鍵字配對。"
        ),
        unsafe_allow_html=True,
    )

# When a scrape is running, show a top-level hint pointing to the Results tab
if ss.running:
    st.markdown(
        f'<div style="background:linear-gradient(135deg, rgba(239,246,255,0.95), rgba(255,255,255,0.85));'
        f'backdrop-filter:blur(14px);border:1px solid rgba(59,130,246,0.4);'
        f'border-left:4px solid {theme.PALETTE["accent"]};border-radius:12px;'
        f'padding:8px 14px;font-size:0.85rem;color:{theme.PALETTE["subtext"]};'
        f'margin:0 0 14px;box-shadow:0 4px 14px rgba(59,130,246,0.12);">'
        f'⚙ <b>爬取中…</b> · 切換至「📊 結果 & 日誌」tab 查看實時進度'
        '</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# 5 sub-tabs
# ============================================================

# ─────────────────────────────────────────────────────────────
# Sub-page navigation — st.radio styled as tabs.
# Why not st.tabs? Streamlit's native tabs are purely client-side and
# CAN'T be programmatically switched. We need to jump to 結果 after
# clicking Start, so we use st.radio with a session-state key and just
# style it to look tab-like.
# ─────────────────────────────────────────────────────────────
TAB_OPTIONS = [
    "📄 上傳 CV",
    "🎯 比對分數",
    "📨 Telegram 通知",
    "🔍 搜尋 & 開始",
    "📊 結果 & 日誌",
]
if "active_tab" not in st.session_state:
    st.session_state.active_tab = TAB_OPTIONS[0]

# Apply any deferred tab switch BEFORE the radio widget is created.
# Streamlit forbids assigning to a widget's session_state key AFTER the
# widget has been instantiated in the current script run, so we use a
# "_pending_tab" handoff: handlers set it, the next rerun applies it here.
if "_pending_tab" in st.session_state:
    pending = st.session_state.pop("_pending_tab")
    if pending in TAB_OPTIONS:
        st.session_state.active_tab = pending

st.radio(
    "Sub-page",
    TAB_OPTIONS,
    key="active_tab",
    horizontal=True,
    label_visibility="collapsed",
)
active = st.session_state.active_tab


# ─────────────────────────────────────────────────────────────
# Tab 1: 上傳 CV + 關鍵字編輯
# ─────────────────────────────────────────────────────────────
if active == "📄 上傳 CV":
    theme.section_label("📄 上傳 CV")

    if appcfg.IS_CLOUD:
        st.caption(
            "⚠ 雲端模式下語意比對已關閉（sentence-transformers 套件太重），僅使用關鍵字比對。"
        )

    uploaded_cv = st.file_uploader(
        "上傳 CV（PDF 或 TXT）", type=["pdf", "txt"], key="cv_uploader",
    )
    # CRITICAL: only save the tempfile when this is a NEW upload (different
    # filename from what we already stored). Otherwise every rerun would
    # re-save a fresh tempfile + clear cv_keywords_for, which would force
    # an auto-re-extract — masking any edits or the Clear button.
    if uploaded_cv is not None and (
        st.session_state.get("uploaded_cv_name") != uploaded_cv.name
        or not st.session_state.get("uploaded_cv_path")
        or not Path(st.session_state.get("uploaded_cv_path") or "").exists()
    ):
        suffix = Path(uploaded_cv.name).suffix or ".pdf"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded_cv.getvalue())
        tmp.close()
        st.session_state.uploaded_cv_path = tmp.name
        st.session_state.uploaded_cv_name = uploaded_cv.name
        st.session_state.pop("cv_keywords_for", None)
        st.success(f"✓ 已上傳：{uploaded_cv.name}")
    elif st.session_state.get("uploaded_cv_name"):
        st.info(f"📎 已上傳：{st.session_state.uploaded_cv_name}")
        if st.button("✗ 清除上傳", key="cv_clear"):
            st.session_state.uploaded_cv_path = None
            st.session_state.uploaded_cv_name = None
            for k in ("cv_keywords", "cv_keywords_for", "cv_years"):
                st.session_state.pop(k, None)
            st.rerun()

    if not appcfg.IS_CLOUD:
        st.text_input(
            "或填入本地 CV 路徑",
            key="s_cv_path",
            help="本地 PDF / TXT 的完整路徑（爬蟲會自動讀取）",
        )

    # Keyword editor
    cv_path_for_extract = (
        st.session_state.get("uploaded_cv_path")
        or st.session_state.get("s_cv_path", "")
    )
    if cv_path_for_extract and cv_match is not None:
        if st.session_state.get("cv_keywords_for") != cv_path_for_extract:
            with st.spinner("抽取 CV 關鍵字…"):
                try:
                    profile = cv_match.load_cv(cv_path_for_extract, use_saved_profile=False)
                except Exception as e:
                    profile = None
                    st.warning(f"抽取失敗：{e}")
            if profile:
                st.session_state.cv_keywords = sorted(profile.keywords)
                st.session_state.cv_years = profile.years
                st.session_state.cv_keywords_for = cv_path_for_extract
            else:
                st.session_state.cv_keywords = []
                st.session_state.cv_years = None
                st.session_state.cv_keywords_for = cv_path_for_extract

        kw_list = st.session_state.get("cv_keywords") or []
        years = st.session_state.get("cv_years")

        st.divider()
        st.markdown(
            f"#### 🔑 CV 關鍵字 "
            f"<span style='font-family:monospace;font-size:0.75rem;color:#64748B;'>"
            f"({len(kw_list)} 個" + (f" · {years} 年經驗" if years else "") + ")</span>",
            unsafe_allow_html=True,
        )
        st.caption("自動由 CV 抽取，以逗號分隔。可移除不適合的，或新增自訂關鍵字。")

        # Version counter trick: bumping `cv_kw_ver` gives the text_area
        # a fresh `key=`, which forces Streamlit to discard the previous
        # widget state (including any cached browser value). This is the
        # bulletproof way to truly clear / refill the textarea — popping
        # the key alone is unreliable across some Streamlit versions.
        kw_ver = st.session_state.get("cv_kw_ver", 0)
        edited_text = st.text_area(
            "關鍵字（以逗號分隔）",
            value=", ".join(kw_list),
            key=f"cv_keywords_textarea_v{kw_ver}",
            height=140,
            label_visibility="collapsed",
        )

        parsed = []
        seen_lower = set()
        for raw in edited_text.split(","):
            k = raw.strip()
            if not k:
                continue
            kl = k.lower()
            if kl in seen_lower:
                continue
            seen_lower.add(kl)
            parsed.append(k)
        st.session_state.cv_keywords = parsed

        b1, b2, _ = st.columns([1, 1, 3])
        with b1:
            if st.button("🔄 重新抽取", help="重新由 CV 文字提取（將覆蓋你的編輯）"):
                st.session_state.pop("cv_keywords_for", None)
                st.session_state.cv_kw_ver = kw_ver + 1
                st.rerun()
        with b2:
            if st.button("🧹 清空", key="cv_kw_clear"):
                st.session_state.cv_keywords = []
                st.session_state.cv_kw_ver = kw_ver + 1
                st.rerun()
    elif cv_path_for_extract and cv_match is None:
        st.warning("`cv_match` 模組未載入，無法抽取關鍵字。")
    else:
        st.caption("尚未上傳 CV — 上傳後會自動抽取關鍵字。")


# ─────────────────────────────────────────────────────────────
# Tab 2: 比對分數
# ─────────────────────────────────────────────────────────────
if active == "🎯 比對分數":
    theme.section_label("🎯 比對分數下限")

    st.markdown(
        "設定 Telegram 推送的 **匹配分數下限**。系統將每個工作的 JD 與你的 "
        "CV 關鍵字做比對，計算 0–100 分。"
    )

    score_threshold = st.number_input(
        "下限（0 = 全部推送）",
        min_value=0.0, max_value=100.0, step=5.0,
        key="s_match_threshold",
        help="只有匹配分數 ≥ 此值的工作才會推送至 Telegram。主資料庫仍會記錄全部結果。",
    )

    # Visual guide
    st.markdown(
        f"""<div style="display:flex;gap:8px;margin-top:14px;font-size:0.8rem;">
        <div style="flex:1;background:{theme.PALETTE['red_subtle']};border:1px solid {theme.PALETTE['red']};
             border-radius:10px;padding:10px;text-align:center;color:{theme.PALETTE['red']};">
          <b>0 – 39</b><br/><span style="font-size:0.75rem;">關聯度低</span>
        </div>
        <div style="flex:1;background:{theme.PALETTE['warning_subtle']};border:1px solid {theme.PALETTE['warning']};
             border-radius:10px;padding:10px;text-align:center;color:{theme.PALETTE['warning']};">
          <b>40 – 69</b><br/><span style="font-size:0.75rem;">有關但唔強</span>
        </div>
        <div style="flex:1;background:{theme.PALETTE['success_subtle']};border:1px solid {theme.PALETTE['success']};
             border-radius:10px;padding:10px;text-align:center;color:{theme.PALETTE['success']};">
          <b>70 – 100</b><br/><span style="font-size:0.75rem;">高度匹配</span>
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    if score_threshold > 0:
        st.success(f"目前設定：只推送 ≥ **{score_threshold:.0f} 分** 的工作至 Telegram。")
    else:
        st.info("目前設定：**全部**工作都會推送（無下限）。")


# ─────────────────────────────────────────────────────────────
# Tab 3: 📨 Telegram 通知 — per-user bot credentials
# ─────────────────────────────────────────────────────────────
if active == "📨 Telegram 通知":
    theme.section_label("📨 你自己的 Telegram BOT 設定")

    user_settings = auth.get_user_settings()
    my_token = (user_settings.get("telegram_token") or "").strip()
    my_chat = (user_settings.get("telegram_chat_id") or "").strip()
    has_setup = bool(my_token and my_chat)

    if has_setup:
        st.success(
            f"✓ 你的 Telegram bot 已連結 · "
            f"Chat ID 末尾 `…{my_chat[-3:]}`"
        )
    else:
        st.info(
            "👇 跟以下 3 步設定**你自己**的 Telegram bot — "
            "每個 user 用獨立 bot，互不影響。"
        )
        with st.expander("📖 教學（首次設定）", expanded=True):
            st.markdown("""
**1. 開新 Telegram bot**

- 喺 Telegram 找 [@BotFather](https://t.me/BotFather)
- 打 `/newbot` → 跟指示輸入 bot 名 → 拿到 **Bot Token**

**2. 拿你的 Chat ID**

- 喺 Telegram 找 [@userinfobot](https://t.me/userinfobot)
- 打 `/start` → bot 回覆你的 **Chat ID**（數字）

**3. 拿你新建嘅 bot 發第一條訊息**

- 喺 Telegram 搜尋你嘅 bot username（步驟 1 攞過）
- 打 `/start` —令 bot 有資格主動發訊息俾你

完成 → 喺下面填入 token + chat ID → 儲存 → 試訊息
            """)

    with st.form("user_tg_form"):
        new_tok = st.text_input(
            "Bot Token",
            value=my_token,
            type="password",
            placeholder="123456:ABC-DEF...",
            help="由 @BotFather 攞",
        )
        new_chat = st.text_input(
            "Chat ID",
            value=my_chat,
            placeholder="123456789",
            help="由 @userinfobot 攞（純數字）",
        )
        save_btn = st.form_submit_button(
            "💾 儲存到我的帳戶", type="primary", use_container_width=True,
        )
        if save_btn:
            new_tok_clean = new_tok.strip()
            new_chat_clean = new_chat.strip()
            if not new_tok_clean or not new_chat_clean:
                st.error("Token 同 Chat ID 都要填")
            else:
                ok, msg = auth.save_user_settings(
                    telegram_token=new_tok_clean,
                    telegram_chat_id=new_chat_clean,
                )
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    if has_setup:
        st.divider()
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("🔔 測試訊息", use_container_width=True):
                ok, msg = scraper.telegram_test_ping(my_token, my_chat)
                (st.success if ok else st.error)(msg)
        with bc2:
            if st.button("✗ 清除", use_container_width=True):
                ok, msg = auth.save_user_settings(
                    telegram_token="", telegram_chat_id="",
                )
                if ok:
                    st.rerun()

    st.divider()

    # Auto-enable s_tg_enabled the FIRST time the user has a valid setup,
    # but don't override later (so user can manually disable). The flag
    # `_tg_enabled_seeded` records that we've done the one-shot seed.
    if has_setup and not st.session_state.get("_tg_enabled_seeded"):
        st.session_state.s_tg_enabled = True
        st.session_state._tg_enabled_seeded = True

    # Push options — note: when `key` is already in session_state (seeded
    # by init_settings or by the line above), Streamlit forbids passing
    # `value=` to the widget — would raise StreamlitAPIException.
    st.checkbox(
        "啟用 Telegram 推送（每次 scrape 自動推 paginated card）",
        key="s_tg_enabled",
        disabled=not has_setup,
        help="設好 bot 之後預設啟用。" if has_setup else "請先設定 bot。",
    )

    cc1, cc2 = st.columns(2)
    with cc1:
        st.number_input(
            "最多推送（0 = 無上限）",
            min_value=0, max_value=9999, step=1,
            key="s_tg_max",
            disabled=not st.session_state.get("s_tg_enabled", False),
        )
    with cc2:
        st.checkbox(
            "加 儲存 / 隱藏 / 已申請 按鈕",
            key="s_include_actions",
            disabled=not st.session_state.get("s_tg_enabled", False),
        )

    # Webhook registration (one-time)
    if has_setup:
        with st.expander("⚙ 進階：註冊 webhook（首次設好 bot 之後做一次）"):
            st.caption(
                "你的 bot 需要註冊一個 webhook URL，"
                "Telegram 才會將翻頁／Save／Hide 按鈕的 callback 傳送至 bot_listener。"
            )
            bot_listener_url = st.text_input(
                "Bot Listener URL",
                value=appcfg._secret("bot_listener", "url",
                                      "https://jobradar-bot.onrender.com"),
                help="管理員部署嘅 Render service URL（通常 `https://jobradar-bot.onrender.com`）",
            )
            if st.button("🔗 註冊我嘅 bot 嘅 webhook"):
                import urllib.request, json as _json
                webhook_url = bot_listener_url.rstrip("/") + "/webhook"
                api = f"https://api.telegram.org/bot{my_token}/setWebhook"
                payload = _json.dumps({
                    "url": webhook_url,
                    "allowed_updates": ["callback_query"],
                }).encode()
                req = urllib.request.Request(
                    api, data=payload, method="POST",
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        body = _json.loads(resp.read().decode("utf-8"))
                        if body.get("ok"):
                            st.success(f"✓ Webhook 已註冊至 {webhook_url}")
                        else:
                            st.error(f"失敗：{body.get('description')}")
                except Exception as e:
                    st.error(f"網絡錯誤：{e}")


# ─────────────────────────────────────────────────────────────
# Tab 4: 🔍 搜尋 & 開始
# ─────────────────────────────────────────────────────────────
if active == "🔍 搜尋 & 開始":
    theme.section_label("🔍 搜尋條件")

    # Filter pill
    col_src, col_kw, col_loc, col_pg = st.columns([1.1, 1.6, 1.6, 0.9])
    with col_src:
        if st.session_state.get("s_source") not in UI_SOURCES:
            st.session_state.s_source = UI_SOURCES[0]
        st.selectbox(
            "🏷 來源",
            options=list(UI_SOURCES),
            key="s_source",
            help="選擇求職網站",
        )
    with col_kw:
        st.text_input(
            "🔍 關鍵字",
            key="s_keyword",
            placeholder="例如：Accountant",
        )
    with col_loc:
        fmt_district = lambda x: x if x else "全港"
        current_src = st.session_state.get("s_source", UI_SOURCES[0])
        current_loc = st.session_state.get("s_location", "")
        if current_src == "ctgoodjobs":
            loc_options = [""] + list(scraper.CT_LOCATIONS)
            if current_loc not in loc_options:
                st.session_state.s_location = ""
            st.selectbox("📍 地區", loc_options, key="s_location",
                         format_func=fmt_district,
                         help="CTgoodjobs 全港所有地區")
        else:
            loc_options = [""] + list(scraper.CP_LOCATIONS)
            if current_loc not in loc_options:
                st.session_state.s_location = ""
            st.selectbox("📍 地區", loc_options, key="s_location",
                         format_func=fmt_district,
                         help="cpjobs 只支援 4 大區")
    with col_pg:
        st.number_input(
            "📄 頁數",
            min_value=0, max_value=999, step=1,
            key="s_max_pages",
            help="0 = 全部頁",
        )

    # Advanced expander
    with st.expander("⚡ 進階設定（可選）"):
        a1, a2 = st.columns(2)
        with a1:
            st.number_input(
                "請求間隔（秒）",
                min_value=0.5, max_value=10.0, step=0.5,
                key="s_delay",
                help="每次抓取之間的等待時間，避免被網站限流。",
            )
        with a2:
            st.checkbox(
                "抓取完整 JD（自動分段：職責 / 要求）",
                key="s_full_jd",
                help="關閉可加快爬取速度，但只會取得工作標題。",
            )
        st.text_input(
            "定時開始（留空 = 即時執行）",
            key="s_at",
            placeholder="HH:MM 或 YYYY-MM-DD HH:MM",
            help="例如 `09:30` 表示等候今日／明日 9:30；`2026-06-01 08:00` 表示等候指定時刻。",
        )

    st.divider()
    theme.section_label("⚡ 爬蟲控制")

    ctrl1, ctrl2, ctrl3, ctrl_status = st.columns([1, 1, 1.2, 4])
    with ctrl1:
        start_clicked = st.button(
            "▶ 開始", type="primary",
            disabled=ss.running, use_container_width=True,
        )
    with ctrl2:
        stop_clicked = st.button(
            "■ 停止",
            disabled=not ss.running, use_container_width=True,
        )
    with ctrl3:
        clear_clicked = st.button(
            "🧹 清空 Log",
            disabled=ss.running, use_container_width=True,
        )
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

        persist_cv_keywords()

        ss.log_lines = []
        ss.finished_msg = None
        ss.last_output_path = None
        ss.log_queue = queue.Queue()
        ss.stop_event = threading.Event()
        ss.log_lines.append(
            f"關鍵字: {args.keyword}  |  Source: {args.source}  |  "
            f"Location: {args.location or '(無)'}"
        )
        ss.log_lines.append(
            f"最多頁數: {'全部' if args.max_pages == 0 else args.max_pages}  |  "
            f"完整 JD: {'是' if args.full_jd else '否'}  |  Delay: {args.delay}s"
        )
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
        # Auto-jump to 結果 tab so user sees the log immediately.
        # Use the deferred handoff (NOT direct ss.active_tab = ...) because
        # the radio widget already rendered earlier in this script run, and
        # Streamlit forbids assigning to widget keys post-instantiation.
        ss._pending_tab = "📊 結果 & 日誌"
        st.rerun()

    if stop_clicked and ss.running:
        ss.stop_event.set()
        ss.log_lines.append(">>> 停止訊號已發送，正在結束…")


# ─────────────────────────────────────────────────────────────
# Tab 5: 📊 結果 & 日誌
# ─────────────────────────────────────────────────────────────
if active == "📊 結果 & 日誌":
    # KPIs from master_stats
    master_path = (st.session_state.get("s_master") or "").strip()
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
    theme.section_label("📜 日誌")
    log_box = st.empty()
    drain_log_queue()
    done = False
    if ss.log_lines and ss.log_lines[-1] == "__DONE__":
        ss.log_lines.pop()
        done = True
    log_box.code("\n".join(ss.log_lines[-500:]) or "(尚未開始)", language="log")

    # Output (current run CSV) — show table + CSV/Excel download
    if not ss.running and ss.last_output_path:
        p = Path(ss.last_output_path)
        if p.exists():
            theme.section_label("📂 今次輸出")
            try:
                import csv as _csv
                with open(p, encoding="utf-8-sig", newline="") as fh:
                    rows = list(_csv.DictReader(fh))
                # Apply match threshold filter — only show jobs that passed
                threshold = float(st.session_state.get("s_match_threshold", 0) or 0)
                if threshold > 0:
                    rows = [
                        r for r in rows
                        if float(r.get("Match Score") or 0) >= threshold
                    ]

                if rows:
                    # Show summary chip + table
                    st.caption(
                        f"今次抓到 **{len(rows)}** 條工作"
                        + (f"（match score ≥ {threshold:.0f}）" if threshold else "")
                    )

                    # Display key columns only (otherwise too wide)
                    display_cols = [
                        c for c in (
                            "Match Score", "Job Title", "Company",
                            "Salary", "Location", "Posted Date",
                            "Work Type", "URL",
                        )
                        if c in rows[0]
                    ]
                    table_data = [
                        {k: r.get(k, "") for k in display_cols}
                        for r in rows
                    ]
                    st.dataframe(
                        table_data,
                        use_container_width=True,
                        height=min(400, 40 + len(table_data) * 35),
                        column_config={
                            "URL": st.column_config.LinkColumn(
                                "URL", width="small", display_text="🔗",
                            ),
                            "Match Score": st.column_config.NumberColumn(
                                "Match", format="%d", width="small",
                            ),
                        },
                    )
                else:
                    st.info("無工作通過 match score 下限。")

                # Downloads row — CSV + Excel
                csv_data = p.read_bytes()
                csv_sz_kb = len(csv_data) / 1024

                # Convert to xlsx on-the-fly for the Excel download
                try:
                    import io as _io
                    import openpyxl
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = "Jobs"
                    if rows:
                        headers = list(rows[0].keys())
                        ws.append(headers)
                        for r in rows:
                            ws.append([r.get(h, "") for h in headers])
                    buf = _io.BytesIO()
                    wb.save(buf)
                    xlsx_bytes = buf.getvalue()
                    xlsx_name = p.stem + ".xlsx"
                    xlsx_sz_kb = len(xlsx_bytes) / 1024
                except Exception:
                    xlsx_bytes = None
                    xlsx_name = ""
                    xlsx_sz_kb = 0

                dc1, dc2 = st.columns(2)
                with dc1:
                    st.download_button(
                        f"⬇ CSV  ·  {csv_sz_kb:.1f} KB",
                        csv_data, file_name=p.name, mime="text/csv",
                        key="dl_csv", use_container_width=True,
                    )
                with dc2:
                    if xlsx_bytes:
                        st.download_button(
                            f"📊 Excel  ·  {xlsx_sz_kb:.1f} KB",
                            xlsx_bytes,
                            file_name=xlsx_name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="dl_xlsx", use_container_width=True,
                        )
                    else:
                        st.caption("⚠ Excel 轉換失敗")
            except Exception as e:
                st.warning(f"讀取輸出檔失敗: {e}")


# ============================================================
# Polling loop (runs at top-level regardless of active tab)
# ============================================================

if ss.running:
    if done or (ss.worker is not None and not ss.worker.is_alive()):
        ss.running = False
        log_text = "\n".join(ss.log_lines)
        if "HTTP 403" in log_text:
            ss.finished_msg = "已被封鎖 (HTTP 403)"
            ss.finished_kind = "warning"
            ss.log_lines.append("")
            ss.log_lines.append(
                "💡 提示：JobsDB 對資料中心 IP 較嚴格。建議改用 cpjobs 或 ctgoodjobs，或本機運行。"
            )
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
