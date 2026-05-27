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

st.set_page_config(page_title="設定", page_icon="⚙", layout="wide")
theme.apply()
theme.render_sidebar_nav()
appcfg.init_settings()

theme.glass_title(
    "設定",
    emoji="⚙",
    subtitle="爬蟲嘅次要選項全部喺呢度",
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
                "去 **Streamlit Cloud → Settings → Secrets**，paste 以下，"
                "**唔好喺介面直接顯示 token**："
            )
            st.code(
                '[telegram]\ntoken = "你嘅 BotFather token"\nchat_id = "你嘅 chat ID"',
                language="toml",
            )
    else:
        if src == "secrets":
            st.info("ℹ Telegram credentials 來自本地 `.streamlit/secrets.toml`（推薦做法）")
        elif src == "config":
            st.warning(
                "⚠ Telegram token 而家擺喺 `config.json` 入面。"
                "建議搬去 `.streamlit/secrets.toml`（已 gitignore，唔會 leak）。"
            )
        else:
            st.caption("未設定。可以喺下面填，或者寫入 `.streamlit/secrets.toml`。")

        with st.expander("✏ 本地編輯 Telegram credentials（只限本機）", expanded=src == "none"):
            st.text_input(
                "Bot Token (BotFather)",
                value=tok,
                type="password",
                key="s_tg_token_local",
                help="本地 token — 唔會推上 GitHub（config.json 已 gitignore）",
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

    st.checkbox(
        "啟用 Telegram 推送（每條新工作即時通知）",
        key="s_tg_enabled",
        disabled=src == "none",
        help="未設定 token 嘅話呢度會 disabled。" if src == "none" else None,
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
            "只用關鍵字比對。"
        )

    uploaded_cv = st.file_uploader("上傳 CV（PDF 或 TXT）", type=["pdf", "txt"])
    if uploaded_cv is not None:
        suffix = Path(uploaded_cv.name).suffix or ".pdf"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded_cv.getvalue())
        tmp.close()
        st.session_state.uploaded_cv_path = tmp.name
        st.session_state.uploaded_cv_name = uploaded_cv.name
        st.success(f"✓ 已上傳：{uploaded_cv.name}")
    elif st.session_state.get("uploaded_cv_name"):
        st.info(f"📎 已上傳：{st.session_state.uploaded_cv_name}")
        if st.button("✗ 清除上傳"):
            st.session_state.uploaded_cv_path = None
            st.session_state.uploaded_cv_name = None
            st.rerun()

    if not appcfg.IS_CLOUD:
        st.text_input(
            "或者填本地 CV 路徑",
            key="s_cv_path",
            help="本地 PDF / TXT 嘅完整路徑（爬蟲會自動讀取）",
        )

    st.number_input(
        "Telegram 推送 Match Score 下限（0 = 全部推送）",
        min_value=0.0, max_value=100.0, step=5.0,
        key="s_match_threshold",
        help="只有匹配分數 ≥ 呢個值嘅工作先會推 Telegram。主資料庫照樣全部記錄。",
    )


# ============================================================
# ⚡ 進階
# ============================================================
with tab_adv:
    c1, c2 = st.columns(2)
    with c1:
        st.number_input(
            "Request 間隔（秒）",
            min_value=0.5, max_value=10.0, step=0.5,
            key="s_delay",
            help="每次抓取之間嘅等待時間，避免被網站限流。",
        )
    with c2:
        st.checkbox(
            "抓取完整 JD（自動分段：職責 / 要求）",
            key="s_full_jd",
            help="關閉可加快爬取速度，但只攞到工作標題。",
        )

    st.text_input(
        "定時開始（留空 = 即刻）",
        key="s_at",
        placeholder="HH:MM 或 YYYY-MM-DD HH:MM",
        help="例如 `09:30` = 等今日 / 明日 9:30；`2026-06-01 08:00` = 等指定時刻。",
    )

    st.divider()

    # Save to config (local only)
    if appcfg.IS_CLOUD:
        st.caption(
            "💡 雲端模式下，config.json 唔會 persist（檔案系統重啟即清）。"
            "Settings 只喺呢個 session 內保留。要永久改 default，去 "
            "**Streamlit Cloud → Settings → Secrets** 寫 `[defaults]` block。"
        )
    else:
        if st.button("💾 儲存全部設定到 config.json"):
            cfg_existing = appcfg._load_config_json()
            cfg_existing.update(appcfg.export_settings())
            ok, msg = appcfg.save_config_json(cfg_existing)
            (st.success if ok else st.error)(msg)
