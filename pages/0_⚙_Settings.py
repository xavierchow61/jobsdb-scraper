"""Settings page — split into 3 sub-tabs.

  📨 Telegram   — bot token (cloud: secrets only) + enable toggle + test
  🎯 CV 比對    — upload CV, threshold for Telegram push
  ⚡ 進階       — delay, full JD, scheduled start + save-to-config button

Output CSV path and Master xlsx path are no longer user-facing — they use
sensible defaults from config.SETTING_SPECS (DEFAULT_MASTER, auto-named CSV).
"""

import tempfile
from pathlib import Path

import streamlit as st

import config as appcfg
import scraper
import theme

try:
    import cv_match
except ImportError:
    cv_match = None

st.set_page_config(page_title="設定", page_icon="⚙", layout="wide")
theme.apply()
theme.render_sidebar_nav()
appcfg.init_settings()

theme.glass_title(
    "設定",
    emoji="⚙",
    subtitle="爬蟲的次要選項全部在此",
    badge="雲端" if appcfg.IS_CLOUD else "本機",
)

tab_tg, tab_cv, tab_adv = st.tabs(["📨 Telegram 通知", "🎯 CV 比對", "⚡ 進階"])


# ============================================================
# 📨 Telegram
# ============================================================
with tab_tg:
    tok, chat, src = appcfg.telegram_credentials()

    if appcfg.IS_CLOUD:
        if src == "secrets":
            masked_chat = chat[:3] + "…" + chat[-2:] if len(chat) > 5 else "…"
            st.success(
                f"✓ 已透過 Streamlit Cloud Secrets 設定 · "
                f"Chat ID `{masked_chat}` · Token 已隱藏"
            )
        else:
            st.error("✗ 雲端模式下尚未設定 Telegram Secrets")
            st.markdown(
                "請至 **Streamlit Cloud → Settings → Secrets**，貼上以下內容，"
                "**請勿在介面直接顯示 token**："
            )
            st.code(
                '[telegram]\ntoken = "您的 BotFather token"\nchat_id = "您的 chat ID"',
                language="toml",
            )
    else:
        if src == "secrets":
            st.info("ℹ Telegram 認證來自本地 `.streamlit/secrets.toml`（建議做法）")
        elif src == "config":
            st.warning(
                "⚠ Telegram token 目前儲存於 `config.json`。"
                "建議改放至 `.streamlit/secrets.toml`（已 gitignore，不會外洩）。"
            )
        else:
            st.caption("尚未設定。可在下方填寫，或寫入 `.streamlit/secrets.toml`。")

        with st.expander("✏ 本地編輯 Telegram 認證（僅限本機）", expanded=src == "none"):
            st.text_input(
                "Bot Token (BotFather)",
                value=tok,
                type="password",
                key="s_tg_token_local",
                help="本地 token — 不會推送至 GitHub（config.json 已 gitignore）",
            )
            st.text_input("Chat ID (numeric)", value=chat, key="s_tg_chat_local")
            if st.button("💾 寫入 config.json"):
                cfg_existing = appcfg._load_config_json()
                cfg_existing["tg_token"] = st.session_state.s_tg_token_local
                cfg_existing["tg_chat"] = st.session_state.s_tg_chat_local
                ok, msg = appcfg.save_config_json(cfg_existing)
                (st.success if ok else st.error)(msg)
                st.rerun()

    st.divider()

    if src in ("secrets", "config"):
        toggle_help = (
            "已設定 token，預設自動開啟。"
            "雲端 session 重啟後會保持開啟（因為 secrets 仍然存在）。"
        )
    else:
        toggle_help = "尚未設定 token，此項目暫時無法啟用。"

    st.checkbox(
        "啟用 Telegram 推送（每條新工作即時通知）",
        key="s_tg_enabled",
        disabled=src == "none",
        help=toggle_help,
    )

    cc1, cc2 = st.columns(2)
    with cc1:
        st.number_input(
            "最多推送（0 = 無上限）",
            min_value=0, max_value=9999, step=1,
            key="s_tg_max",
            disabled=not st.session_state.s_tg_enabled,
        )
    with cc2:
        st.checkbox(
            "加 儲存 / 隱藏 / 已申請 按鈕（需 bot_listener.py）",
            key="s_include_actions",
            disabled=not st.session_state.s_tg_enabled,
        )

    if st.button("🔔 測試 Telegram", disabled=not (tok and chat)):
        ok, msg = scraper.telegram_test_ping(tok, chat)
        (st.success if ok else st.error)(msg)


# ============================================================
# 🎯 CV 比對
# ============================================================
with tab_cv:
    if appcfg.IS_CLOUD:
        st.caption(
            "⚠ 雲端模式下語意比對已關閉（sentence-transformers 套件太重），"
            "僅使用關鍵字比對。"
        )

    uploaded_cv = st.file_uploader("上傳 CV（PDF 或 TXT）", type=["pdf", "txt"])
    if uploaded_cv is not None:
        suffix = Path(uploaded_cv.name).suffix or ".pdf"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded_cv.getvalue())
        tmp.close()
        st.session_state.uploaded_cv_path = tmp.name
        st.session_state.uploaded_cv_name = uploaded_cv.name
        # Reset keyword cache so we re-extract from the new CV
        st.session_state.pop("cv_keywords_for", None)
        st.success(f"✓ 已上傳：{uploaded_cv.name}")
    elif st.session_state.get("uploaded_cv_name"):
        st.info(f"📎 已上傳：{st.session_state.uploaded_cv_name}")
        if st.button("✗ 清除上傳"):
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

    # ---- Keyword editor (auto-extract + edit/add) ----
    cv_path_for_extract = st.session_state.get("uploaded_cv_path") or st.session_state.get("s_cv_path", "")
    if cv_path_for_extract and cv_match is not None:
        # Re-extract keywords when the CV changes
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

        edited_text = st.text_area(
            "關鍵字（以逗號分隔）",
            value=", ".join(kw_list),
            key="cv_keywords_textarea",
            height=140,
            label_visibility="collapsed",
        )

        # Parse + dedupe (case-insensitive, preserve original casing)
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

        b1, b2, b3 = st.columns([1, 1, 3])
        with b1:
            if st.button("🔄 重新抽取", help="重新由 CV 文字提取（將覆蓋你的編輯）"):
                st.session_state.pop("cv_keywords_for", None)
                st.rerun()
        with b2:
            if st.button("🧹 清空"):
                st.session_state.cv_keywords = []
                st.session_state.cv_keywords_textarea = ""
                st.rerun()
    elif cv_path_for_extract and cv_match is None:
        st.warning("`cv_match` 模組未載入，無法抽取關鍵字。")

    st.number_input(
        "Telegram 推送匹配分數下限（0 = 全部推送）",
        min_value=0.0, max_value=100.0, step=5.0,
        key="s_match_threshold",
        help="只有匹配分數 ≥ 此值的工作才會推送至 Telegram。主資料庫仍會記錄全部結果。",
    )


# ============================================================
# ⚡ 進階
# ============================================================
with tab_adv:
    c1, c2 = st.columns(2)
    with c1:
        st.number_input(
            "請求間隔（秒）",
            min_value=0.5, max_value=10.0, step=0.5,
            key="s_delay",
            help="每次抓取之間的等待時間，避免被網站限流。",
        )
    with c2:
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

    # Save to config (local only)
    if appcfg.IS_CLOUD:
        st.caption(
            "💡 雲端模式下，config.json 不會持久儲存（檔案系統重啟即清空）。"
            "設定僅在此 session 內保留。如需永久更改預設值，請至 "
            "**Streamlit Cloud → Settings → Secrets** 寫入 `[defaults]` 區塊。"
        )
    else:
        if st.button("💾 儲存全部設定到 config.json"):
            cfg_existing = appcfg._load_config_json()
            cfg_existing.update(appcfg.export_settings())
            ok, msg = appcfg.save_config_json(cfg_existing)
            (st.success if ok else st.error)(msg)
