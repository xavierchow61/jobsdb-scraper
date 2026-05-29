"""Shared config + session-state-backed settings for the Streamlit app.

Both streamlit_app.py (main page) and pages/0_⚙_Settings.py import from here.

Settings storage strategy:
  1. On first page load, init_settings() populates st.session_state from
     config.json (local) + st.secrets (cloud), falling back to defaults.
  2. Each form widget binds directly to a "s_*" session_state key. Edits on
     the Settings page are immediately visible to the main page (same session).
  3. "Save" on Settings page writes config.json locally (no-op on Cloud).
  4. Sensitive values (Telegram token) bypass session_state on Cloud and come
     directly from st.secrets so they never appear in any UI widget.
"""

import json
import os
from pathlib import Path

import streamlit as st


# ============================================================
# Environment
# ============================================================

CONFIG_PATH = Path(__file__).parent / "config.json"

IS_CLOUD = (
    "/mount/src" in str(Path(__file__).resolve())
    or os.getenv("STREAMLIT_RUNTIME_ENV") == "cloud"
)

DEFAULT_MASTER = (
    Path("/tmp/jobs_master.xlsx") if IS_CLOUD
    else Path(__file__).parent / "jobs_master.xlsx"
)


# ============================================================
# Secrets / config loading
# ============================================================

def _secret(section, key, default=""):
    """Read st.secrets[section][key] without raising if missing."""
    try:
        return st.secrets[section][key]
    except (KeyError, FileNotFoundError, AttributeError):
        return default


def _load_config_json():
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config_json(values):
    """Persist edited values to config.json (local only — Cloud FS is ephemeral)."""
    if IS_CLOUD:
        return False, "雲端模式下 config.json 不會持久儲存（檔案系統重啟即清空）。請改用 Streamlit Secrets。"
    try:
        CONFIG_PATH.write_text(
            json.dumps(values, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True, f"已寫入 {CONFIG_PATH.name}"
    except Exception as e:
        return False, f"寫入失敗: {e}"


def supabase_credentials():
    """Return (url, anon_key) for Supabase, or ('', '') if not configured.

    Read first from st.secrets [supabase] block, then from env vars
    (for the bot_listener running on Render / locally with .env).
    """
    url = _secret("supabase", "url") or os.getenv("SUPABASE_URL", "")
    key = _secret("supabase", "anon_key") or _secret("supabase", "key") or os.getenv("SUPABASE_KEY", "")
    return url.strip(), key.strip()


def supabase_service_credentials():
    """Return (url, service_role_key). Used for server-side writes that
    need to bypass RLS — e.g. worker thread inserting telegram_batches.
    The row's user_id is set explicitly so per-user data isolation is
    preserved despite bypassing the RLS check.
    """
    url = _secret("supabase", "url") or os.getenv("SUPABASE_URL", "")
    key = (
        _secret("supabase", "service_role_key")
        or _secret("supabase", "service_role")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    )
    return url.strip(), key.strip()


# Telegram token helpers — Cloud routes through st.secrets, never user input.
def telegram_credentials():
    """Return (token, chat_id, source) — source ∈ {'secrets', 'config', 'none'}."""
    token = _secret("telegram", "token")
    chat = _secret("telegram", "chat_id")
    if token and chat:
        return token, chat, "secrets"
    cfg = _load_config_json()
    token = (cfg.get("tg_token") or "").strip()
    chat = (cfg.get("tg_chat") or "").strip()
    if token and chat:
        return token, chat, "config"
    return "", "", "none"


# ============================================================
# Session-state-backed settings
# ============================================================
# Each settings field lives at st.session_state["s_<name>"]. Widgets bind via
# key="s_<name>". Defaults are seeded once per session in init_settings().

# Keys to skip when loading [defaults] from Streamlit Secrets (and when
# exporting the TOML snippet on the Settings page). Either per-machine
# paths, credentials, or per-run values that shouldn't be a "default".
DEFAULTS_SKIP = {"master", "output", "tg_token", "tg_chat", "at"}


SETTING_SPECS = {
    # key:           (config_key, default, type_caster)
    "s_source":          ("source",          "cpjobs",     str),
    "s_keyword":         ("keyword",         "Accountant", str),
    "s_location":        ("location",        "",           str),
    "s_max_pages":       ("max_pages",       0,            int),
    "s_delay":           ("delay",           1.5,          float),
    "s_full_jd":         ("full_jd",         True,         bool),
    "s_at":              ("at",              "",           str),
    "s_output":          ("output",          "",           str),
    "s_master_enabled":  ("master_enabled",  True,         bool),
    "s_master":          ("master",          "",           str),  # filled below
    "s_cv_path":         ("cv",              "",           str),
    "s_match_threshold": ("match_threshold", 0.0,          float),
    "s_tg_enabled":      ("tg_enabled",      False,        bool),
    "s_tg_max":          ("tg_max",          0,            int),
    "s_include_actions": ("include_actions", False,        bool),
}


def _coerce(value, typ, default):
    if value is None:
        return default
    if typ is bool:
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)
    try:
        return typ(value)
    except (TypeError, ValueError):
        return default


def init_settings():
    """Populate session_state from config.json + secrets + URL params
    (once per session), then mirror back to URL so navigation preserves state."""
    if st.session_state.get("_settings_loaded"):
        # Already loaded — just ensure URL reflects current state for this page
        sync_url_from_session()
        return
    cfg = _load_config_json()

    # Auto-enable Telegram push when credentials are configured (secrets or
    # config.json) and tg_enabled hasn't been explicitly set. Without this,
    # users have to manually toggle tg_enabled every fresh Cloud session
    # because session_state doesn't persist.
    have_creds = bool(_secret("telegram", "token") or cfg.get("tg_token"))
    if have_creds and "tg_enabled" not in cfg:
        cfg["tg_enabled"] = True

    # Overlay [defaults] from Streamlit Secrets for every persistable setting.
    # Skip per-machine paths and credentials (those live in [telegram] section
    # or in config.json directly).
    for sk, (ck, _, _) in SETTING_SPECS.items():
        if ck in DEFAULTS_SKIP:
            continue
        v = _secret("defaults", ck, None)
        if v is not None:
            cfg.setdefault(ck, v)

    # Highest precedence: URL query params (for bookmarkable settings).
    # This is the cloud-friendly persistence — user updates URL via the
    # "保存到網址" button, bookmarks it, and the values auto-load next visit.
    for sk, (ck, _, _) in SETTING_SPECS.items():
        if ck in DEFAULTS_SKIP:
            continue
        try:
            v = st.query_params.get(ck)
        except Exception:
            v = None
        if v is not None and v != "":
            cfg[ck] = v

    # Seed each session-state key
    for sk, (ck, default, typ) in SETTING_SPECS.items():
        if sk in st.session_state:
            continue
        if sk == "s_master":
            default = str(cfg.get("master") or DEFAULT_MASTER)
            st.session_state[sk] = default
            continue
        st.session_state[sk] = _coerce(cfg.get(ck), typ, default)

    st.session_state._settings_loaded = True

    # Mirror to URL so the current page's URL reflects loaded state.
    # Subsequent reruns / navigations will keep this in sync via the
    # early-return branch above.
    sync_url_from_session()


def export_settings():
    """Return current settings as a plain dict for config.json (excludes Telegram secrets)."""
    out = {}
    for sk, (ck, _, _) in SETTING_SPECS.items():
        out[ck] = st.session_state.get(sk)
    # Boolean-ish stored values get coerced back to str-friendly for compat with old config
    return out


def _serialize_value(v):
    """Serialize a Python setting value to a URL query string."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _should_write_to_url(v, default):
    """Return True if this value differs from default enough to bother
    putting in URL. We omit defaults/empties to keep URLs short."""
    if v is None or v == "":
        return False
    if v is False:
        return False
    if isinstance(v, (int, float)) and v == 0:
        return False
    if v == default:
        return False
    return True


def sync_url_from_session():
    """Mirror current session_state settings into URL query params.

    Called automatically at the end of every init_settings() — so every
    page load (Dashboard, Settings, ...) writes the same settings into
    its own URL. That means navigating between pages preserves state in
    the URL, and bookmarking ANY page captures all current settings.

    Only writes when the value differs from URL's current value, so this
    doesn't trigger gratuitous reruns.
    """
    for sk, (ck, default, typ) in SETTING_SPECS.items():
        if ck in DEFAULTS_SKIP:
            continue
        v = st.session_state.get(sk)
        try:
            if _should_write_to_url(v, default):
                new_val = _serialize_value(v)
                current = st.query_params.get(ck)
                if current != new_val:
                    st.query_params[ck] = new_val
            else:
                # Value matches default — remove from URL if present
                if ck in st.query_params:
                    try:
                        del st.query_params[ck]
                    except Exception:
                        pass
        except Exception:
            # Be defensive: a flaky st.query_params API call must not
            # break the page render.
            pass


# Back-compat alias (the older "save to URL" button calls this)
update_url_from_session = sync_url_from_session
