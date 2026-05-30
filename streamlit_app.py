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

try:
    import master_sync
except ImportError:
    master_sync = None

try:
    import ai_analyst
except ImportError:
    ai_analyst = None


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

    # Apply match-threshold filter. Prefer AI Fit (Gemini) over keyword
    # Match Score — AI Fit reflects context-aware fit and is what the
    # user actually wants for "should I get notified about this?".
    threshold = float(getattr(args, "match_threshold", 0) or 0)
    jd_nums = [r.get("JD Number") for r in rows if r.get("JD Number")]
    ai_fit_by_jd = _fetch_ai_fits(sup, user_id, jd_nums)
    if threshold > 0:
        kept = []
        for r in rows:
            score = _effective_score(r, ai_fit_by_jd)
            if score >= threshold:
                kept.append(r)
        skipped = len(rows) - len(kept)
        if skipped:
            metric = "AI Fit" if ai_fit_by_jd else "Match Score"
            print(f"  [tg-cards] {skipped} 條低於下限 {threshold:.0f}（用 {metric}），已過濾")
        rows = kept
    if not rows:
        print(f"  [tg-cards] 無工作達到下限，0 通知")
        return

    # Replace the row's Match Score with AI Fit before sending so the
    # paginated Telegram card displays the AI score (more meaningful).
    for r in rows:
        jd = r.get("JD Number") or ""
        if jd in ai_fit_by_jd:
            r["Match Score"] = int(round(ai_fit_by_jd[jd]))

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


def _supabase_service_client():
    """Get a service-role Supabase client (bypasses RLS, server-side)."""
    if telegram_cards is None:
        return None
    sb_url, sb_service = appcfg.supabase_service_credentials()
    if not (sb_url and sb_service):
        return None
    return telegram_cards.supabase_client(sb_url, sb_service)


def _pre_populate_master(args):
    """Rebuild /tmp/jobs_master.xlsx from Supabase before scrape starts.

    Without this, Streamlit Cloud's ephemeral filesystem means every
    container restart loses the accumulated master xlsx. Pulling from
    Supabase at scrape start makes the dedup logic in scraper.MasterDB
    see all historic jobs.
    """
    if master_sync is None or not getattr(args, "user_id", None) or not args.master:
        return
    sup = _supabase_service_client()
    if not sup:
        return
    try:
        n = master_sync.download_master_to_xlsx(sup, args.user_id, args.master)
        if n:
            print(f"  [master-sync] 從 Supabase 預載 {n} 條既有工作")
    except Exception as e:
        print(f"  [master-sync] 預載失敗: {e}")


def _post_sync_master(args):
    """After scrape, push new rows from /tmp/jobs_master.xlsx to Supabase."""
    if master_sync is None or not getattr(args, "user_id", None) or not args.master:
        return
    sup = _supabase_service_client()
    if not sup:
        return
    try:
        added, updated = master_sync.sync_xlsx_to_supabase(
            sup, args.user_id, args.master
        )
        if added or updated:
            print(f"  [master-sync] 已同步 {added} 條新 + {updated} 條更新工作至 Supabase")
    except Exception as e:
        print(f"  [master-sync] 同步失敗: {e}")


def _auto_ai_analyze(args, csv_path):
    """Run Gemini fit analysis for every row in the per-run CSV.

    Results land in Supabase job_analysis (cached). Downstream code
    (filter, Telegram push, UI table) reads the cache and prefers
    AI Fit over keyword Match Score. Idempotent — already-cached
    rows skip the LLM call inside analyze_mismatch.
    """
    if ai_analyst is None:
        return
    if not ai_analyst.is_available():
        print(f"  [ai] {ai_analyst.availability_reason()}")
        return
    user_id = getattr(args, "user_id", None)
    if not user_id or not csv_path:
        return

    sb_url, sb_service = appcfg.supabase_service_credentials()
    if not (sb_url and sb_service):
        print("  [ai] Supabase service_role 未設定，跳過 AI 分析")
        return
    sup = telegram_cards.supabase_client(sb_url, sb_service)
    if not sup:
        return

    try:
        cv_kw = list(st.session_state.get("cv_keywords") or [])
        cv_yr = st.session_state.get("cv_years")
    except Exception:
        cv_kw, cv_yr = [], None

    if not cv_kw:
        print("  [ai] 無 CV keywords，跳過 AI 分析")
        return

    import csv as _csv
    p = Path(str(csv_path))
    if not p.exists():
        return
    try:
        with open(p, encoding="utf-8-sig", newline="") as fh:
            rows = list(_csv.DictReader(fh))
    except Exception as e:
        print(f"  [ai] 讀取 CSV 失敗: {e}")
        return
    if not rows:
        return

    print(f"  [ai] 開始為 {len(rows)} 條工作運行 Gemini fit 分析…")
    success = 0
    for i, r in enumerate(rows, 1):
        if not r.get("JD Number"):
            continue
        try:
            obj, err = ai_analyst.analyze_mismatch(
                sup, user_id, cv_kw, cv_yr, r,
            )
            if err:
                print(f"  [ai] 第 {i} 條：{err}")
            elif obj and obj.get("fit_score") is not None:
                success += 1
        except Exception as e:
            print(f"  [ai] 第 {i} 條失敗: {e}")
        if i % 5 == 0 or i == len(rows):
            print(f"  [ai]   進度 {i}/{len(rows)}")
    print(f"  [ai] 完成 {success}/{len(rows)} 條 fit 分析（已快取至 Supabase）")


def _fetch_ai_fits(supabase, user_id, jd_numbers):
    """Batch-read fit_score from job_analysis cache. Returns {jd: score}."""
    if not supabase or not user_id or not jd_numbers:
        return {}
    try:
        res = (
            supabase.table("job_analysis")
            .select("jd_number, mismatch_analysis")
            .eq("user_id", str(user_id))
            .in_("jd_number", list(jd_numbers))
            .execute()
        )
    except Exception as e:
        print(f"  [ai] 讀取 fit cache 失敗: {e}")
        return {}
    out = {}
    for ar in (res.data or []):
        ma = ar.get("mismatch_analysis") or {}
        if ma.get("fit_score") is not None:
            try:
                out[ar["jd_number"]] = float(ma["fit_score"])
            except (TypeError, ValueError):
                pass
    return out


def _effective_score(row, ai_fit_by_jd):
    """Return the score we should use for this row: AI Fit if cached,
    else fall back to keyword Match Score."""
    jd = row.get("JD Number") or ""
    if jd in ai_fit_by_jd:
        return ai_fit_by_jd[jd]
    try:
        return float(row.get("Match Score") or 0)
    except (TypeError, ValueError):
        return 0.0


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

        # PRE-SCRAPE: rebuild local xlsx from Supabase so dedup sees history
        _pre_populate_master(args)

        path = scraper.scrape(args, stop_event=stop_event)
        if path:
            result["output_path"] = str(path)

        # POST-SCRAPE: push new rows (including just-scraped) up to Supabase
        _post_sync_master(args)

        # AUTO AI: run Gemini fit analysis for each new job before any
        # downstream threshold / Telegram logic — so AI Fit is the
        # primary score, not keyword Match.
        _auto_ai_analyze(args, path)

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


def _render_fit_analysis(obj):
    """Display Gemini's fit analysis with positive reasoning emphasis.

    Expected dict shape (returned by ai_analyst.analyze_mismatch):
      fit_score, verdict, why_apply (list), talking_points,
      matched_skills (list), missing_skills (list), concerns

    Also handles legacy field names (strength_summary, mismatch_reason)
    so cached older analyses still render gracefully.
    """
    fit = obj.get("fit_score") or 0
    verdict = (obj.get("verdict") or "").strip()
    color = (
        theme.PALETTE["success"] if fit >= 70
        else theme.PALETTE["warning"] if fit >= 40
        else theme.PALETTE["red"]
    )
    verdict_emoji = {
        "建議申請": "✅",
        "可考慮":   "🤔",
        "不太建議": "⚠",
    }.get(verdict, "🎯")

    # Top row: score + verdict
    st.markdown(
        f"""<div style='display:flex;align-items:center;gap:18px;
        background:white;border:2px solid {color};border-radius:14px;
        padding:14px 18px;margin:8px 0;'>
          <div style='font-size:2.2rem;font-weight:800;color:{color};
          line-height:1;'>{fit}<span style='font-size:0.9rem;font-weight:500;
          color:{theme.PALETTE["muted"]};'> / 100</span></div>
          <div style='font-size:1.05rem;font-weight:700;color:{color};'>
          {verdict_emoji} {verdict or 'AI 評估'}</div>
        </div>""",
        unsafe_allow_html=True,
    )

    # Main reasoning — 為何建議申請
    why = obj.get("why_apply") or []
    # Backwards-compat: old cache used strength_summary single string
    if not why and obj.get("strength_summary"):
        why = [obj["strength_summary"]]
    if why:
        st.markdown(
            f"<div style='font-weight:700;font-size:0.95rem;"
            f"color:{theme.PALETTE['accent_dark']};margin:14px 0 6px;'>"
            f"💡 為何建議申請</div>",
            unsafe_allow_html=True,
        )
        for r in why:
            st.markdown(
                f"<div style='padding:8px 12px;background:{theme.PALETTE['accent_subtle']};"
                f"border-left:3px solid {theme.PALETTE['accent']};"
                f"border-radius:6px;margin:4px 0;font-size:0.9rem;'>"
                f"{r}</div>",
                unsafe_allow_html=True,
            )

    # Talking points
    if obj.get("talking_points"):
        st.markdown(
            f"<div style='margin:14px 0 6px;padding:10px 14px;"
            f"background:{theme.PALETTE['success_subtle']};border-radius:8px;"
            f"font-size:0.88rem;'>"
            f"🎤 <b>申請時可強調：</b> {obj['talking_points']}"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Skills chips
    matched = obj.get("matched_skills") or []
    missing = obj.get("missing_skills") or []
    if matched or missing:
        sk1, sk2 = st.columns(2)
        with sk1:
            if matched:
                st.caption("✅ 已配對的 skill")
                st.write(", ".join(matched))
        with sk2:
            if missing:
                st.caption("❌ JD 有但 CV 無")
                st.write(", ".join(missing))

    # Concerns (collapsed by default — secondary info)
    concerns = obj.get("concerns") or obj.get("mismatch_reason")
    if concerns:
        with st.expander("⚠ 申請時要留意"):
            st.write(concerns)


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

    # ISOLATION FIX: on Streamlit Cloud, /tmp is shared across all
    # concurrent user sessions on the same container. If two users
    # scrape at the same time, _pre_populate_master would overwrite
    # each other's xlsx and _post_sync_master would upsert the wrong
    # user's rows. Use a per-user filename.
    if appcfg.IS_CLOUD and a.master:
        _u = auth.get_user()
        if _u and _u.get("id"):
            a.master = f"/tmp/jobs_master_{_u['id']}.xlsx"

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
                em = st.text_input("Email", placeholder="你註冊的 email",
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
    "📌 我的工作",
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
          <b>40 – 69</b><br/><span style="font-size:0.75rem;">有關但不強</span>
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

- 在 Telegram 找 [@BotFather](https://t.me/BotFather)
- 輸入 `/newbot` → 跟指示輸入 bot 名稱 → 取得 **Bot Token**

**2. 取得你的 Chat ID**

- 在 Telegram 找 [@userinfobot](https://t.me/userinfobot)
- 輸入 `/start` → bot 回覆你的 **Chat ID**（數字）

**3. 向你新建的 bot 發送第一條訊息**

- 在 Telegram 搜尋你的 bot username（步驟 1 取得）
- 輸入 `/start` — 令 bot 有資格主動發送訊息給你

完成 → 在下方填入 token + chat ID → 儲存 → 測試訊息
            """)

    with st.form("user_tg_form"):
        new_tok = st.text_input(
            "Bot Token",
            value=my_token,
            type="password",
            placeholder="123456:ABC-DEF...",
            help="由 @BotFather 取得",
        )
        new_chat = st.text_input(
            "Chat ID",
            value=my_chat,
            placeholder="123456789",
            help="由 @userinfobot 取得（純數字）",
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
                help="管理員部署的 Render service URL（通常為 `https://jobradar-bot.onrender.com`）",
            )
            if st.button("🔗 註冊我的 bot 的 webhook"):
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

        # Attach the logged-in user's id so the worker thread can sync
        # /tmp/jobs_master.xlsx ↔ Supabase master_jobs under the right row.
        _u = auth.get_user()
        args.user_id = _u["id"] if _u else None

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
                    all_rows = list(_csv.DictReader(fh))
                total_scraped = len(all_rows)

                # Merge cached Gemini fit_score into each row so the table
                # can show both keyword Match and AI Fit side-by-side.
                ai_fit_by_jd = {}
                sup_user = auth.get_supabase()
                user_now = auth.get_user()
                if sup_user and user_now and all_rows and ai_analyst is not None:
                    jd_nums = [
                        r.get("JD Number") for r in all_rows
                        if r.get("JD Number")
                    ]
                    if jd_nums:
                        try:
                            ai_res = (
                                sup_user.table("job_analysis")
                                .select("jd_number, mismatch_analysis")
                                .eq("user_id", user_now["id"])
                                .in_("jd_number", jd_nums)
                                .execute()
                            )
                            for ar in (ai_res.data or []):
                                ma = ar.get("mismatch_analysis") or {}
                                if ma.get("fit_score") is not None:
                                    ai_fit_by_jd[ar["jd_number"]] = ma["fit_score"]
                        except Exception:
                            pass
                for r in all_rows:
                    fit_val = ai_fit_by_jd.get(r.get("JD Number"))
                    r["AI Fit"] = int(fit_val) if fit_val is not None else None

                # Filter logic — prefer AI Fit (Gemini) over keyword Match.
                # AI Fit reflects context-aware reasoning; keyword Match is
                # the legacy narrow vocab score.
                threshold = float(st.session_state.get("s_match_threshold", 0) or 0)
                show_zero = st.checkbox(
                    "顯示無分數的工作（AI 未分析或分析失敗）",
                    value=False, key="show_zero_match",
                )

                def _row_score(r):
                    """AI Fit (if cached) ─ else keyword Match Score."""
                    jd = r.get("JD Number") or ""
                    if jd in ai_fit_by_jd:
                        return float(ai_fit_by_jd[jd])
                    try:
                        return float(r.get("Match Score") or 0)
                    except (TypeError, ValueError):
                        return 0.0

                rows = all_rows
                if threshold > 0:
                    rows = [r for r in rows if _row_score(r) >= threshold]
                if not show_zero:
                    # When threshold=0, hide rows scored 0 (no signal).
                    # When threshold>0, threshold already covered the cut.
                    if threshold == 0:
                        rows = [r for r in rows if _row_score(r) > 0]
                hidden_count = total_scraped - len(rows)

                if rows:
                    parts = [f"今次抓到 **{total_scraped}** 條"]
                    if threshold > 0:
                        parts.append(f"≥ {threshold:.0f} 分顯示 **{len(rows)}** 條")
                    elif hidden_count:
                        parts.append(f"已隱藏 Match=0 **{hidden_count}** 條（剩 **{len(rows)}**）")
                    st.caption("，".join(parts))

                    # AI Fit always shown when Gemini is configured (even
                    # before any analysis has been cached — column displays
                    # blanks until batch fills them).
                    ai_available = (
                        ai_analyst is not None and ai_analyst.is_available()
                    )
                    cols_order = [
                        "AI Fit",
                        "Job Title", "Company",
                        "Salary", "Location", "Posted Date",
                        "Work Type", "URL",
                    ]
                    display_cols = []
                    for c in cols_order:
                        if c not in rows[0]:
                            continue
                        if c == "AI Fit" and not ai_available:
                            continue
                        display_cols.append(c)
                    table_data = [
                        {k: r.get(k) for k in display_cols}
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
                            "AI Fit": st.column_config.NumberColumn(
                                "AI Fit", format="%d", width="small",
                                help="Gemini AI 語意配對分數（0-100）",
                            ),
                        },
                    )

                    # Batch AI 分析 button — fills cache for uncached rows
                    if ai_analyst is not None and ai_analyst.is_available():
                        uncached = [
                            r for r in rows
                            if r.get("JD Number")
                            and not ai_fit_by_jd.get(r.get("JD Number"))
                        ]
                        if uncached:
                            cv_kw_b = ss.get("cv_keywords") or []
                            cv_yr_b = ss.get("cv_years")
                            if st.button(
                                f"🤖 為其餘 {len(uncached)} 條工作運行 Gemini 配對",
                                key="ai_batch_run",
                            ):
                                prog = st.progress(0)
                                stat = st.empty()
                                for i, r in enumerate(uncached):
                                    stat.caption(
                                        f"分析中… {i + 1}/{len(uncached)}："
                                        f"{(r.get('Job Title') or '')[:50]}"
                                    )
                                    try:
                                        ai_analyst.analyze_mismatch(
                                            sup_user, user_now["id"],
                                            cv_kw_b, cv_yr_b, r,
                                        )
                                    except Exception as e:
                                        print(f"batch ai failed: {e}")
                                    prog.progress((i + 1) / len(uncached))
                                stat.caption("完成 — 重新整理表格")
                                st.rerun()
                else:
                    if total_scraped == 0:
                        st.info("今次無新工作。")
                    elif threshold > 0:
                        st.info(
                            f"今次抓到 {total_scraped} 條，但全部分數均 < {threshold:.0f}。"
                            "可調低 Tab 🎯 比對分數 的下限，或勾選下方選項查看全部。"
                        )
                    else:
                        st.info(
                            f"今次抓到 {total_scraped} 條，但全部評分為 0（Gemini 未配置或分析未完成）。"
                            "勾選下方選項查看全部，或至 Tab 📄 CV 確認關鍵字已抽取。"
                        )

                # Downloads row — CSV + Excel
                csv_data = p.read_bytes()
                csv_sz_kb = len(csv_data) / 1024

                # Convert to xlsx on-the-fly for the Excel download.
                # Use all_rows (not filtered) so the download contains every
                # job scraped — the table filter is for display only.
                try:
                    import io as _io
                    import openpyxl
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = "Jobs"
                    if all_rows:
                        headers = list(all_rows[0].keys())
                        ws.append(headers)
                        for r in all_rows:
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

                # ─── AI JD 分析 panel ───
                if rows and ai_analyst is not None:
                    st.divider()
                    theme.section_label("🤖 AI 分析（選一條工作查看）")
                    if not ai_analyst.is_available():
                        st.caption(f"⚠ {ai_analyst.availability_reason()}")
                    else:
                        labels = [
                            f"{i + 1}. {(r.get('Job Title') or '').strip()[:60]}"
                            f"  @ {(r.get('Company') or '').strip()[:25]}"
                            for i, r in enumerate(rows)
                        ]
                        pick = st.selectbox(
                            "選擇工作",
                            options=list(range(len(rows))),
                            format_func=lambda i: labels[i],
                            key="ai_job_pick",
                        )
                        chosen = rows[pick]

                        sup_ai = auth.get_supabase()
                        user_ai = auth.get_user()
                        uid_ai = user_ai["id"] if user_ai else None
                        cv_kw_ai = ss.get("cv_keywords") or []
                        cv_yr_ai = ss.get("cv_years")

                        ai1, ai2 = st.columns(2)
                        with ai1:
                            if st.button("📋 JD 摘要", key="ai_btn_sum",
                                         use_container_width=True):
                                with st.spinner("Gemini 分析中…"):
                                    text, err = ai_analyst.summarize_jd(
                                        sup_ai, uid_ai, chosen,
                                    )
                                if err:
                                    st.error(err)
                                elif text:
                                    st.markdown(text)
                        with ai2:
                            if st.button("🎯 配對分析", key="ai_btn_fit",
                                         use_container_width=True):
                                with st.spinner("Gemini 比對 CV ↔ JD 中…"):
                                    obj, err = ai_analyst.analyze_mismatch(
                                        sup_ai, uid_ai, cv_kw_ai, cv_yr_ai,
                                        chosen,
                                    )
                                if err:
                                    st.error(err)
                                elif obj:
                                    _render_fit_analysis(obj)
            except Exception as e:
                st.warning(f"讀取輸出檔失敗: {e}")


# ─────────────────────────────────────────────────────────────
# Tab 6: 📌 我的工作 — Saved / Applied / Hidden views
# ─────────────────────────────────────────────────────────────
if active == "📌 我的工作":
    sup_user = auth.get_supabase()
    user_now = auth.get_user()
    if not sup_user or not user_now:
        st.warning("請先登入。")
    else:
        uid = user_now["id"]
        # Fetch master_jobs + job_actions in parallel-ish (two queries)
        try:
            mj_res = (
                sup_user.table("master_jobs")
                .select("*")
                .eq("user_id", uid)
                .order("scraped_at", desc=True)
                .limit(2000)
                .execute()
            )
            master_rows = mj_res.data or []
        except Exception as e:
            st.warning(f"讀取主資料庫失敗：{e}")
            master_rows = []
        try:
            ja_res = (
                sup_user.table("job_actions")
                .select("*")
                .eq("user_id", uid)
                .execute()
            )
            action_rows = ja_res.data or []
        except Exception as e:
            st.warning(f"讀取狀態失敗：{e}")
            action_rows = []

        actions_by_jd = {a["jd_number"]: a for a in action_rows}
        saved_jobs   = []
        applied_jobs = []
        hidden_jobs  = []
        for m in master_rows:
            jd = m.get("jd_number")
            a = actions_by_jd.get(jd, {})
            row = {**m, "_saved": a.get("saved"),
                       "_applied": a.get("applied"),
                       "_hidden": a.get("hidden")}
            if a.get("saved"):
                saved_jobs.append(row)
            if a.get("applied"):
                applied_jobs.append(row)
            if a.get("hidden"):
                hidden_jobs.append(row)

        c1, c2, c3, c4 = st.columns(4)
        theme.kpi_card(c1, "主資料庫", len(master_rows),
                       color=theme.PALETTE["accent"], emoji="📊")
        theme.kpi_card(c2, "已儲存", len(saved_jobs),
                       color=theme.PALETTE["warning"], emoji="⭐")
        theme.kpi_card(c3, "已申請", len(applied_jobs),
                       color=theme.PALETTE["success"], emoji="✅")
        theme.kpi_card(c4, "已隱藏", len(hidden_jobs),
                       color=theme.PALETTE["red"], emoji="🚫")

        st.write("")

        # ─── Dashboard 招聘洞察 ───
        if master_rows:
            theme.section_label("📊 招聘市場洞察")
            try:
                from collections import Counter
                # Top hiring companies
                companies = [r.get("company") for r in master_rows if r.get("company")]
                top_co = Counter(companies).most_common(10)

                # Match score distribution
                score_buckets = {"0–19": 0, "20–39": 0, "40–59": 0,
                                 "60–79": 0, "80–100": 0}
                for r in master_rows:
                    s = r.get("match_score")
                    if s is None:
                        continue
                    try:
                        s = float(s)
                    except (TypeError, ValueError):
                        continue
                    if s < 20: score_buckets["0–19"] += 1
                    elif s < 40: score_buckets["20–39"] += 1
                    elif s < 60: score_buckets["40–59"] += 1
                    elif s < 80: score_buckets["60–79"] += 1
                    else: score_buckets["80–100"] += 1

                # Top location
                locations = [r.get("location") for r in master_rows if r.get("location")]
                top_loc = Counter(locations).most_common(8)

                # Two-column layout
                lc, rc = st.columns(2)
                with lc:
                    st.caption("📊 Match Score 分佈")
                    st.bar_chart(score_buckets, height=200)
                with rc:
                    if top_loc:
                        st.caption("📍 工作地點 Top 8")
                        st.bar_chart(dict(top_loc), height=200)

                if top_co:
                    st.caption("🏢 最多招聘的公司（Top 10）")
                    st.bar_chart(dict(top_co), height=220, horizontal=True)
            except Exception as e:
                st.caption(f"⚠ 洞察渲染失敗：{e}")

        st.divider()

        # Download full master
        if master_rows and master_sync is not None:
            try:
                xlsx_bytes = master_sync.build_xlsx_bytes(
                    _supabase_service_client(), uid
                )
                if xlsx_bytes:
                    from datetime import datetime as _dt
                    fn = f"jobs_master_{_dt.now():%Y%m%d}.xlsx"
                    st.download_button(
                        f"📥 下載完整 Master xlsx · {len(xlsx_bytes)/1024:.1f} KB"
                        f"（{len(master_rows)} 條）",
                        xlsx_bytes, file_name=fn,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_master_xlsx",
                    )
            except Exception as e:
                st.caption(f"⚠ Master xlsx 建立失敗：{e}")

        st.divider()

        view_saved, view_applied, view_hidden = st.tabs([
            f"⭐ 已儲存（{len(saved_jobs)}）",
            f"✅ 已申請（{len(applied_jobs)}）",
            f"🚫 已隱藏（{len(hidden_jobs)}）",
        ])

        def render_job_list(rows, status_field, status_label, empty_msg):
            if not rows:
                st.caption(empty_msg)
                return
            display = []
            for r in rows:
                display.append({
                    status_label: r.get(status_field, "")[:10] if r.get(status_field) else "",
                    "Job Title": r.get("job_title") or "",
                    "Company":   r.get("company") or "",
                    "Salary":    r.get("salary") or "",
                    "Location":  r.get("location") or "",
                    "Match":     int(r["match_score"]) if r.get("match_score") else None,
                    "URL":       r.get("url") or "",
                })
            st.dataframe(
                display, use_container_width=True,
                height=min(500, 40 + len(display) * 35),
                column_config={
                    "URL": st.column_config.LinkColumn("", width="small", display_text="🔗"),
                    "Match": st.column_config.NumberColumn(format="%d", width="small"),
                },
            )

        with view_saved:
            render_job_list(saved_jobs, "_saved", "Saved",
                            "尚未有已儲存的工作。在 Telegram 點 ⭐ Save 即會記錄至此。")
            # AI helpers per saved job
            if saved_jobs and ai_analyst is not None:
                st.divider()
                theme.section_label("✍ AI 助手（為已儲存工作生成 cover letter / gap 分析）")
                if not ai_analyst.is_available():
                    st.caption(f"⚠ {ai_analyst.availability_reason()}")
                else:
                    labels = [
                        f"{i + 1}. {(r.get('job_title') or '').strip()[:60]}"
                        f"  @ {(r.get('company') or '').strip()[:25]}"
                        for i, r in enumerate(saved_jobs)
                    ]
                    pick_s = st.selectbox(
                        "選擇 saved 工作",
                        options=list(range(len(saved_jobs))),
                        format_func=lambda i: labels[i],
                        key="ai_saved_pick",
                    )
                    chosen_s = saved_jobs[pick_s]

                    cv_kw_s = ss.get("cv_keywords") or []
                    cv_yr_s = ss.get("cv_years")
                    sup_s = auth.get_supabase()

                    ab1, ab2 = st.columns(2)
                    with ab1:
                        if st.button("📝 Cover Letter (英文)",
                                     key="ai_btn_cl",
                                     use_container_width=True):
                            with st.spinner("Gemini 撰寫中…"):
                                text, err = ai_analyst.generate_cover_letter(
                                    sup_s, uid, cv_kw_s, cv_yr_s, chosen_s,
                                )
                            if err:
                                st.error(err)
                            elif text:
                                st.text_area(
                                    "可直接 copy",
                                    value=text, height=320,
                                    key="cl_preview",
                                    label_visibility="collapsed",
                                )
                    with ab2:
                        if st.button("🎯 配對 / Gap 分析",
                                     key="ai_btn_gap",
                                     use_container_width=True):
                            with st.spinner("Gemini 分析中…"):
                                obj, err = ai_analyst.analyze_mismatch(
                                    sup_s, uid, cv_kw_s, cv_yr_s, chosen_s,
                                )
                            if err:
                                st.error(err)
                            elif obj:
                                _render_fit_analysis(obj)
        with view_applied:
            render_job_list(applied_jobs, "_applied", "Applied",
                            "尚未有已申請的工作。在 Telegram 點 ✅ Applied 即會記錄至此。")
        with view_hidden:
            render_job_list(hidden_jobs, "_hidden", "Hidden",
                            "尚未有已隱藏的工作。在 Telegram 點 🚫 Hide 即會記錄至此。")


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
