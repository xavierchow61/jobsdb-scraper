"""Supabase Auth for JOB RADAR Streamlit app.

Ported from minute-hk-app/auth.py, simplified for personal use:
  • No captcha (low traffic, personal app)
  • No invite codes (single user)
  • Same disposable-email guard

Public API:
    init_session()        — populate session_state.user / .session keys
    get_user() -> dict | None
    is_logged_in() -> bool
    signup(email, pw) -> (ok, msg)
    login(email, pw) -> (ok, msg)
    logout()
    reset_password(email) -> (ok, msg)
    get_supabase() -> Client  (auth-attached, RLS-aware)
"""

import streamlit as st


# Disposable email guard — stops bots from creating throwaway accounts
DISPOSABLE_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "20minutemail.com",
    "anonymbox.com", "burnermail.io", "deadaddress.com", "deadspam.com",
    "dispostable.com", "easytrashmail.com", "emailondeck.com",
    "fakeinbox.com", "fakemail.fr", "getnada.com", "guerrillamail.com",
    "guerrillamail.de", "guerrillamail.net", "guerrillamail.org",
    "harakirimail.com", "incognitomail.com", "inboxalias.com",
    "jetable.org", "mailcatch.com", "maildrop.cc", "mailexpire.com",
    "mailforspam.com", "mailimate.com", "mailinator.com", "mailinator.net",
    "mailinator.org", "maildx.com", "mailnesia.com", "mailnull.com",
    "mailtrash.net", "mintemail.com", "moakt.com", "mt2014.com",
    "mt2015.com", "mytrashmail.com", "neverbox.com", "objectmail.com",
    "obobbo.com", "onewaymail.com", "pookmail.com", "rcpt.at",
    "sharklasers.com", "shortmail.net", "sneakemail.com", "snkmail.com",
    "spambox.us", "spamfree24.org", "spamgourmet.com", "spamspot.com",
    "tempemail.com", "tempemail.net", "tempemailaddress.com",
    "tempinbox.co.uk", "tempinbox.com", "tempmail.com", "tempmail.email",
    "tempmail.net", "tempmail2.com", "tempmaildemand.com", "tempmailer.com",
    "tempmailer.de", "tempomail.fr", "temporaryemail.net",
    "temporaryemail.us", "throwam.com", "throwaway.email",
    "throwawayemailaddresses.com", "throwawaymail.com", "trashinbox.com",
    "trashmail.at", "trashmail.com", "trashmail.de", "trashmail.io",
    "trashmail.me", "trashmail.net", "trashmail.org", "trashmailer.com",
    "trashymail.com", "yopmail.com", "yopmail.fr", "yopmail.net",
    "1secmail.com", "30minutemail.com",
}


def is_disposable_email(email):
    domain = email.lower().rsplit("@", 1)[-1].strip()
    return domain in DISPOSABLE_DOMAINS


def _get_credentials():
    """Read SUPABASE_URL and SUPABASE_ANON_KEY from st.secrets.

    Returns (url, key) — empty strings if not configured.
    """
    try:
        url = st.secrets["supabase"]["url"]
    except Exception:
        url = ""
    try:
        key = st.secrets["supabase"]["anon_key"]
    except Exception:
        try:
            key = st.secrets["supabase"]["key"]   # back-compat
        except Exception:
            key = ""
    return url.strip(), key.strip()


def get_supabase():
    """One shared Supabase client per Streamlit session.

    Re-attaching the auth session every rerun is critical: without it,
    auth.uid() inside Postgres RLS evaluates to NULL and every query
    returns nothing.
    """
    if "supabase_client" not in st.session_state:
        url, key = _get_credentials()
        if not (url and key):
            return None
        try:
            from supabase import create_client
        except ImportError:
            return None
        try:
            st.session_state.supabase_client = create_client(url, key)
        except Exception:
            return None

    sb = st.session_state.supabase_client
    session = st.session_state.get("session")
    if session and not st.session_state.get("_session_attached"):
        try:
            sb.auth.set_session(session.access_token, session.refresh_token)
            st.session_state._session_attached = True
        except Exception:
            pass
    return sb


def init_session():
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("session", None)
    st.session_state.setdefault("_session_attached", False)


def get_user():
    init_session()
    return st.session_state.user


def is_logged_in():
    return get_user() is not None


def signup(email, password):
    if len(password) < 6:
        return False, "密碼至少 6 位字符"
    if "@" not in email:
        return False, "Email 格式錯誤"
    if is_disposable_email(email):
        return False, "不接受臨時 email，請用真實 email"
    sb = get_supabase()
    if sb is None:
        return False, "Supabase 未設定（缺 URL / anon key）"
    try:
        result = sb.auth.sign_up({"email": email, "password": password})
        if result.user:
            if result.session:
                st.session_state.user = {
                    "id": result.user.id,
                    "email": result.user.email,
                }
                st.session_state.session = result.session
                st.session_state._session_attached = True
                return True, "✅ 註冊成功！正在登入…"
            return True, "✅ 註冊成功！請到 email 確認啟用，然後登入。"
        return False, "註冊失敗，請再試。"
    except Exception as e:
        msg = str(e)
        if "already" in msg.lower() or "registered" in msg.lower():
            return False, "此 email 已註冊，請直接登入。"
        return False, f"註冊失敗：{e}"


def login(email, password):
    sb = get_supabase()
    if sb is None:
        return False, "Supabase 未設定（缺 URL / anon key）"
    try:
        result = sb.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        if result.user and result.session:
            st.session_state.user = {
                "id": result.user.id,
                "email": result.user.email,
            }
            st.session_state.session = result.session
            st.session_state._session_attached = True
            return True, "✅ 登入成功"
        return False, "登入失敗"
    except Exception as e:
        msg = str(e).lower()
        if "invalid" in msg or "credentials" in msg:
            return False, "Email 或密碼錯誤"
        if "confirmed" in msg or "confirm" in msg:
            return False, "請先到 email 確認啟用帳戶"
        return False, f"登入失敗：{e}"


def logout():
    sb = st.session_state.get("supabase_client")
    if sb:
        try:
            sb.auth.sign_out()
        except Exception:
            pass
    st.session_state.user = None
    st.session_state.session = None
    st.session_state._session_attached = False


def reset_password(email):
    sb = get_supabase()
    if sb is None:
        return False, "Supabase 未設定"
    try:
        sb.auth.reset_password_for_email(email)
        return True, "✅ 重設密碼連結已送到你的 email"
    except Exception as e:
        return False, f"失敗：{e}"
