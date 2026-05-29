"""Paginated Telegram cards backed by Supabase.

Replaces the scraper's per-job sendMessage flood with ONE paginated card
that the user can navigate via ← / → buttons. The bot_listener (running
separately on Render) handles the navigation callbacks by reading the
batch from Supabase and editing the message in place.

Sender side (this module, used from streamlit_app.py):
    - create_and_send_batch(...)  ← entry point

Reader side (bot_listener.py):
    - get_batch(supabase, batch_id)
    - update_batch_idx(supabase, batch_id, idx)
    - render_card(jobs, idx, source)
    - build_keyboard(batch_id, idx, total, jd_number)
    - edit_message(token, chat_id, message_id, text, keyboard)
"""

import json
import uuid
import urllib.error
import urllib.request

import scraper  # for format_telegram_card


TELEGRAM_API = "https://api.telegram.org"


# ============================================================
# Supabase client + table operations
# ============================================================

def supabase_client(url, anon_key):
    """Lazy-create a Supabase client. Returns None if libs missing or no creds."""
    if not url or not anon_key:
        return None
    try:
        from supabase import create_client
    except ImportError:
        print("  [tg-cards] supabase-py not installed; paginated cards disabled")
        return None
    try:
        return create_client(url, anon_key)
    except Exception as e:
        print(f"  [tg-cards] supabase client init failed: {e}")
        return None


def create_batch(supabase, chat_id, jobs, user_id=None):
    """Insert a new batch into telegram_batches. Returns batch_id.

    user_id is required when RLS is enabled with per-user policies.
    """
    batch_id = uuid.uuid4().hex[:8]
    payload = {
        "batch_id": batch_id,
        "chat_id": str(chat_id),
        "jobs": jobs,
        "current_idx": 0,
    }
    if user_id:
        payload["user_id"] = str(user_id)
    supabase.table("telegram_batches").insert(payload).execute()
    return batch_id


def get_batch(supabase, batch_id):
    """Fetch a batch by id. Returns dict or None."""
    try:
        res = (
            supabase.table("telegram_batches")
            .select("*")
            .eq("batch_id", batch_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        print(f"  [tg-cards] get_batch failed: {e}")
        return None


def update_batch_message_id(supabase, batch_id, message_id):
    supabase.table("telegram_batches").update(
        {"message_id": message_id}
    ).eq("batch_id", batch_id).execute()


def update_batch_idx(supabase, batch_id, idx):
    supabase.table("telegram_batches").update(
        {"current_idx": idx}
    ).eq("batch_id", batch_id).execute()


# ============================================================
# Card rendering
# ============================================================

def render_card(jobs, idx, source=""):
    """Render the HTML body for the card at index `idx`.

    `source` can be passed; if jobs[idx]["Source"] is set, it overrides.
    """
    total = len(jobs)
    job = jobs[idx]
    actual_source = (job.get("Source") or source or "?").strip()
    body = scraper.format_telegram_card(job, actual_source)
    header = (
        f"📦 <b>第 {idx + 1} / {total} 張</b>"
        f"  ·  <i>{actual_source}</i>\n\n"
    )
    return header + body


def build_keyboard(batch_id, idx, total, jd_number=""):
    """Build inline_keyboard with nav row + action row.

    Nav row: [← 上一張] [N/total] [下一張 →]
    Action row: [⭐ Save] [🚫 Hide] [✅ Applied]
    """
    nav_row = []
    if idx > 0:
        nav_row.append({
            "text": "← 上一張",
            "callback_data": f"nav:{batch_id}:{idx - 1}",
        })
    nav_row.append({
        "text": f"{idx + 1}/{total}",
        "callback_data": "nav:noop",
    })
    if idx < total - 1:
        nav_row.append({
            "text": "下一張 →",
            "callback_data": f"nav:{batch_id}:{idx + 1}",
        })

    action_row = [
        {"text": "⭐ Save",    "callback_data": f"act:save:{jd_number}"},
        {"text": "🚫 Hide",    "callback_data": f"act:hide:{jd_number}"},
        {"text": "✅ Applied", "callback_data": f"act:apply:{jd_number}"},
    ]
    return [nav_row, action_row]


# ============================================================
# Telegram API
# ============================================================

def _post(api_url, payload, timeout=20):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        api_url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"  [tg-cards] HTTP {e.code}: {err_body}")
        return {"ok": False, "error_code": e.code, "description": err_body}
    except Exception as e:
        print(f"  [tg-cards] request failed: {e}")
        return {"ok": False, "description": str(e)}


def send_card(token, chat_id, text, keyboard):
    """POST /sendMessage. Returns message_id on success, None on failure."""
    api_url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": keyboard},
    }
    body = _post(api_url, payload)
    if body.get("ok"):
        return body["result"]["message_id"]
    return None


def edit_card(token, chat_id, message_id, text, keyboard):
    """POST /editMessageText. Returns True on success."""
    api_url = f"{TELEGRAM_API}/bot{token}/editMessageText"
    payload = {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": keyboard},
    }
    body = _post(api_url, payload)
    return bool(body.get("ok"))


def answer_callback(token, callback_query_id, text=""):
    """POST /answerCallbackQuery to dismiss the loading spinner on Telegram."""
    api_url = f"{TELEGRAM_API}/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text}
    return bool(_post(api_url, payload).get("ok"))


# ============================================================
# Sender entry point — used from streamlit_app.py
# ============================================================

def create_and_send_batch(supabase, token, chat_id, jobs, source, user_id=None):
    """Create batch in Supabase and send the first paginated card.

    Returns (batch_id, message_id) or (None, None) on failure.
    """
    if not jobs:
        return None, None
    # Embed the source into each row so the bot_listener (which only
    # sees the batch via Supabase) can render the card correctly.
    for j in jobs:
        if not j.get("Source"):
            j["Source"] = source
    try:
        batch_id = create_batch(supabase, chat_id, jobs, user_id=user_id)
    except Exception as e:
        print(f"  [tg-cards] create_batch failed: {e}")
        return None, None

    text = render_card(jobs, 0, source)
    jd_number = (jobs[0].get("JD Number") or "").strip()
    keyboard = build_keyboard(batch_id, 0, len(jobs), jd_number)
    message_id = send_card(token, chat_id, text, keyboard)
    if message_id is None:
        return batch_id, None

    try:
        update_batch_message_id(supabase, batch_id, message_id)
    except Exception as e:
        print(f"  [tg-cards] update_batch_message_id failed: {e}")
    return batch_id, message_id
