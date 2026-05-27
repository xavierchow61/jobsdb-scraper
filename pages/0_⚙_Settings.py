"""Settings page — all secondary config (Telegram / CV / Master / advanced).

Sensitive values (Telegram token) on Cloud route through st.secrets and never
appear in any UI widget. Locally, they're editable but with explicit warnings.

Widgets bind directly to st.session_state["s_*"] keys (seeded by
config.init_settings()). Changes are visible to the main page immediately.
"""

import tempfile
from pathlib import Path

import streamlit as st

import config as appcfg
import scraper
import theme

st.set_page_config(page_title="Settings", page_icon="⚙", layout="wide")
theme.apply()
theme.render_sidebar_nav()
appcfg.init_settings()


# ============================================================
# Header
# ============================================================
theme.glass_title(
    "設定",
    emoji="⚙",
    subtitle="Telegram 通知 · CV 比對 · 主資料庫 · 進階爬蟲選項",
    badge="雲端" if appcfg.IS_CLOUD else "本機",
)


def section_label(text):
    theme.section_label(text)


# ============================================================
# Telegram
# ============================================================
section_label("📨 TELEGRAM NOTIFICATIONS")

tok, chat, src = appcfg.telegram_credentials()

if appcfg.IS_CLOUD:
    # On Cloud, Telegram credentials MUST come from st.secrets — no UI field.
    if src == "secrets":
        masked_chat = chat[:3] + "…" + chat[-2:] if len(chat) > 5 else "…"
        st.success(
            f"✓ Configured via Streamlit Cloud Secrets · chat ID `{masked_chat}` · "
            f"token hidden for security"
        )
    else:
        st.error("✗ Telegram secrets not configured on Cloud")
        st.markdown(
            "去 **Streamlit Cloud → Settings → Secrets** paste 以下，"
            "**唔好喺 UI 顯示 token**：",
        )
        st.code(
            '[telegram]\ntoken = "你嘅 BotFather token"\nchat_id = "你嘅 chat ID"',
            language="toml",
        )
else:
    # Local: allow manual editing, but warn loudly
    if src == "secrets":
        st.info("ℹ Telegram credentials 來自本地 `.streamlit/secrets.toml`（推薦做法）")
    elif src == "config":
        st.warning(
            "⚠ Telegram token 而家擺喺 `config.json` 入面。建議搬去 "
            "`.streamlit/secrets.toml`（已 gitignore，唔會 leak）。"
        )
    else:
        st.caption("未設定。可以喺下面填，或者寫入 `.streamlit/secrets.toml`。")

    # Editable fields ONLY on local
    with st.expander("✏ 本地 edit Telegram credentials（local only）", expanded=src == "none"):
        st.text_input(
            "Bot Token (BotFather)",
            value=tok,
            type="password",
            key="s_tg_token_local",
            help="本地用嘅 token — 唔會推上 GitHub（config.json 已 gitignore）",
        )
        st.text_input(
            "Chat ID (numeric)",
            value=chat,
            key="s_tg_chat_local",
        )
        if st.button("💾 寫入 config.json (local only)"):
            cfg_existing = appcfg._load_config_json()
            cfg_existing["tg_token"] = st.session_state.s_tg_token_local
            cfg_existing["tg_chat"] = st.session_state.s_tg_chat_local
            ok, msg = appcfg.save_config_json(cfg_existing)
            (st.success if ok else st.error)(msg)
            st.rerun()

st.checkbox(
    "啟用 Telegram 推送（每條新 job 即時通知）",
    key="s_tg_enabled",
    disabled=src == "none",
    help="未設定 token 嘅話呢度 disabled。" if src == "none" else None,
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
        "加 Save / Hide / Apply 按鈕（需 bot_listener.py）",
        key="s_include_actions",
        disabled=not st.session_state.s_tg_enabled,
    )

if st.button("🔔 Test Telegram", disabled=not (tok and chat)):
    ok, msg = scraper.telegram_test_ping(tok, chat)
    (st.success if ok else st.error)(msg)


# ============================================================
# CV Match
# ============================================================
section_label("🎯 CV MATCH SCORING")

if appcfg.IS_CLOUD:
    st.caption(
        "⚠ Cloud 上 semantic CV scoring 已關（sentence-transformers 太重）— "
        "只用 keyword matching。"
    )

uploaded_cv = st.file_uploader("上傳 CV（PDF / TXT）", type=["pdf", "txt"])
if uploaded_cv is not None:
    # Persist to a temp file so the path survives page navigation
    suffix = Path(uploaded_cv.name).suffix or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_cv.getvalue())
    tmp.close()
    st.session_state.uploaded_cv_path = tmp.name
    st.session_state.uploaded_cv_name = uploaded_cv.name
    st.success(f"✓ Uploaded: {uploaded_cv.name}")
elif st.session_state.get("uploaded_cv_name"):
    st.info(f"📎 已上傳: {st.session_state.uploaded_cv_name}")
    if st.button("✗ 清除上傳"):
        st.session_state.uploaded_cv_path = None
        st.session_state.uploaded_cv_name = None
        st.rerun()

if not appcfg.IS_CLOUD:
    st.text_input(
        "或者本地 CV 路徑",
        key="s_cv_path",
        help="本地 PDF / TXT 嘅完整路徑（會由 scraper 自動讀取）",
    )

st.number_input(
    "Telegram 推送 Match Score 下限（0 = 全部推送）",
    min_value=0.0, max_value=100.0, step=5.0,
    key="s_match_threshold",
    help="只有 match score ≥ 呢個值嘅 job 先會推 Telegram。Master / CSV 仍然全部記錄。",
)


# ============================================================
# Output / Master
# ============================================================
section_label("📂 OUTPUT & MASTER")

st.text_input(
    "Per-run CSV 路徑（留空 = 自動命名）",
    key="s_output",
    help="留空就會喺工作目錄出 jobsdb_<keyword>_<datetime>.csv",
)

st.checkbox("寫入 Master xlsx（cumulative DB）", key="s_master_enabled")

st.text_input(
    "Master xlsx 路徑",
    key="s_master",
    disabled=not st.session_state.s_master_enabled,
    help="Cloud 上會自動寫去 /tmp（ephemeral）— 每次完要下載。" if appcfg.IS_CLOUD else None,
)


# ============================================================
# Advanced scrape options
# ============================================================
section_label("⚡ ADVANCED")

c1, c2 = st.columns(2)
with c1:
    st.number_input(
        "Request 間隔（秒）",
        min_value=0.5, max_value=10.0, step=0.5,
        key="s_delay",
    )
with c2:
    st.checkbox("抓取完整 JD（自動分段 Resp / Req）", key="s_full_jd")

st.text_input(
    "定時開始（HH:MM 或 YYYY-MM-DD HH:MM，留空 = 即刻）",
    key="s_at",
    help="例如 `09:30` = 等今日 / 明日 9:30。`2026-06-01 08:00` = 等指定時刻。",
)


# ============================================================
# Persist to config.json (local only)
# ============================================================
section_label("💾 PERSISTENCE")

if appcfg.IS_CLOUD:
    st.caption(
        "Cloud 上 config.json 唔會 persist (filesystem ephemeral)。"
        "Settings 只喺呢個 session 內保留。要永久改 default，去 "
        "**Streamlit Cloud → Settings → Secrets** 入面寫 `[defaults]` block。"
    )
else:
    if st.button("💾 Save 全部 settings 落 config.json"):
        cfg_existing = appcfg._load_config_json()
        cfg_existing.update(appcfg.export_settings())
        # Preserve Telegram creds from .json if they were stored there
        ok, msg = appcfg.save_config_json(cfg_existing)
        (st.success if ok else st.error)(msg)
