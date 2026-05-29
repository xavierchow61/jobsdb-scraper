"""Telegram webhook handler — Render-deployable.

Receives Telegram callback_query updates via webhook (not long-polling),
which means this fits on Render's free Web Service tier. Polling-based
bot_listener.py is still around for local use (talks to local xlsx).

Endpoints:
  GET  /            — health check ("ok")
  POST /webhook     — Telegram pushes updates here
  POST /set-webhook — call once to register the webhook with Telegram
                      (or do it manually via curl, see RENDER_DEPLOY.md)

Required env vars (set in Render dashboard):
  TELEGRAM_BOT_TOKEN          — BotFather token
  SUPABASE_URL                — https://<project>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY   — service_role key (NOT anon — bot_listener
                                serves Telegram callbacks, not authenticated
                                users, so it needs RLS-bypass access)
  WEBHOOK_SECRET              — optional; if set, Telegram must include
                                this in the X-Telegram-Bot-Api-Secret-Token
                                header. Stops random HTTP visitors from
                                impersonating Telegram.

  Fallback: if SUPABASE_SERVICE_ROLE_KEY is unset, falls back to
  SUPABASE_KEY for back-compat (you can name your env var either way).

Run locally:
  pip install flask gunicorn supabase
  export TELEGRAM_BOT_TOKEN=...
  export SUPABASE_URL=...
  export SUPABASE_KEY=...
  python bot_listener_cloud.py
  # then in another shell, register the webhook:
  curl -F "url=https://YOUR-PUBLIC-URL/webhook" \
       https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

from flask import Flask, jsonify, request

# Local imports — also installed on Render via requirements.txt
import telegram_cards


app = Flask(__name__)


# ============================================================
# Lazy singletons
# ============================================================

_supabase = None
_supabase_init_failed = False


def get_supabase():
    global _supabase, _supabase_init_failed
    if _supabase is not None:
        return _supabase
    if _supabase_init_failed:
        return None
    url = os.getenv("SUPABASE_URL", "").strip()
    # Prefer service_role (bypasses RLS — what a server-side worker needs).
    # Fall back to SUPABASE_KEY for back-compat with older env setups.
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )
    _supabase = telegram_cards.supabase_client(url, key)
    if _supabase is None:
        _supabase_init_failed = True
    return _supabase


def lookup_user_by_chat(supabase, chat_id):
    """Map a Telegram chat_id → Supabase user_id via user_telegram table."""
    try:
        res = (
            supabase.table("user_telegram")
            .select("user_id")
            .eq("chat_id", str(chat_id))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0]["user_id"] if rows else None
    except Exception as e:
        print(f"lookup_user_by_chat failed: {e}", file=sys.stderr)
        return None


def get_user_token(supabase, user_id):
    """Fetch user's own Telegram bot token from user_settings."""
    try:
        res = (
            supabase.table("user_settings")
            .select("telegram_token")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return (rows[0].get("telegram_token") or "").strip() if rows else ""
    except Exception as e:
        print(f"get_user_token failed: {e}", file=sys.stderr)
        return ""


def resolve_user_and_token(supabase, chat_id):
    """For a Telegram chat_id, return (user_id, user_token) or (None, '').

    Falls back to the admin TELEGRAM_BOT_TOKEN env if user has no token.
    """
    user_id = lookup_user_by_chat(supabase, chat_id) if chat_id else None
    token = get_user_token(supabase, user_id) if user_id else ""
    if not token:
        # Fallback to admin/global bot token (legacy / single-user setups)
        token = get_token()
    return user_id, token


def get_token():
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


# ============================================================
# Health
# ============================================================

@app.route("/", methods=["GET"])
def health():
    sup_ok = get_supabase() is not None
    tok_ok = bool(get_token())
    return jsonify({
        "status": "ok",
        "service": "jobradar-bot-listener",
        "supabase_ok": sup_ok,
        "telegram_token_ok": tok_ok,
    })


# ============================================================
# Webhook
# ============================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    # Optional shared-secret check (Telegram setWebhook supports it)
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if secret:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != secret:
            return jsonify({"ok": False, "error": "bad secret"}), 403

    update = request.get_json(silent=True) or {}
    callback = update.get("callback_query")
    if callback:
        try:
            handle_callback(callback)
        except Exception as e:
            print(f"callback handler crashed: {e}", file=sys.stderr)
    return jsonify({"ok": True})


@app.route("/set-webhook", methods=["POST", "GET"])
def set_webhook():
    """Convenience endpoint: register this service's URL with Telegram.

    Usage: POST/GET to /set-webhook?url=https://yourservice.onrender.com/webhook
    Or omit `url` and we'll try to infer from the request's Host header.
    """
    target = request.args.get("url") or request.values.get("url")
    if not target:
        host = request.host_url.rstrip("/")
        target = f"{host}/webhook"

    token = get_token()
    if not token:
        return jsonify({"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}), 500

    api = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = {"url": target, "allowed_updates": ["callback_query"]}
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if secret:
        payload["secret_token"] = secret

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        api, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return jsonify({"webhook_url": target, "telegram_response": body})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================
# Callback dispatcher
# ============================================================

def handle_callback(callback):
    cb_id = callback["id"]
    data = (callback.get("data") or "").strip()
    msg = callback.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    message_id = msg.get("message_id")

    sup = get_supabase()
    if sup is None:
        # No Supabase → can only respond with admin token if set
        admin_token = get_token()
        if admin_token:
            telegram_cards.answer_callback(admin_token, cb_id, text="Supabase 未設定")
        return

    # Resolve which user's bot this callback belongs to
    user_id, token = resolve_user_and_token(sup, chat_id)
    if not token:
        # No matching token — can't respond
        return

    if data.startswith("nav:"):
        handle_nav(token, cb_id, chat_id, message_id, data)
    elif data.startswith("act:"):
        handle_action(token, cb_id, callback, data, user_id=user_id)
    else:
        telegram_cards.answer_callback(token, cb_id)


def handle_nav(token, cb_id, chat_id, message_id, data):
    """data format: nav:<batch_id>:<idx>  or  nav:noop"""
    parts = data.split(":")
    if len(parts) < 2 or parts[1] == "noop":
        telegram_cards.answer_callback(token, cb_id)
        return
    if len(parts) != 3:
        telegram_cards.answer_callback(token, cb_id, text="無效")
        return

    batch_id, idx_str = parts[1], parts[2]
    try:
        idx = int(idx_str)
    except ValueError:
        telegram_cards.answer_callback(token, cb_id, text="無效")
        return

    sup = get_supabase()
    if sup is None:
        telegram_cards.answer_callback(token, cb_id, text="Supabase 未設定")
        return

    batch = telegram_cards.get_batch(sup, batch_id)
    if not batch:
        telegram_cards.answer_callback(token, cb_id, text="此批次已過期或不存在")
        return

    jobs = batch.get("jobs") or []
    if not jobs or idx < 0 or idx >= len(jobs):
        telegram_cards.answer_callback(token, cb_id, text="超出範圍")
        return

    source = (jobs[idx].get("Source") or "?").strip()
    text = telegram_cards.render_card(jobs, idx, source)
    jd_number = (jobs[idx].get("JD Number") or "").strip()
    keyboard = telegram_cards.build_keyboard(batch_id, idx, len(jobs), jd_number)

    ok = telegram_cards.edit_card(token, chat_id, message_id, text, keyboard)
    if ok:
        try:
            telegram_cards.update_batch_idx(sup, batch_id, idx)
        except Exception:
            pass
        telegram_cards.answer_callback(token, cb_id)
    else:
        telegram_cards.answer_callback(token, cb_id, text="編輯失敗")


def handle_action(token, cb_id, callback, data, user_id=None):
    """data format: act:save:<jd> | act:hide:<jd> | act:apply:<jd>"""
    parts = data.split(":", 2)
    if len(parts) < 3 or not parts[2].strip():
        telegram_cards.answer_callback(token, cb_id, text="無效")
        return
    kind, jd_number = parts[1], parts[2].strip()
    column_map = {"save": "saved", "hide": "hidden", "apply": "applied"}
    column = column_map.get(kind)
    if not column:
        telegram_cards.answer_callback(token, cb_id, text="未知動作")
        return

    sup = get_supabase()
    if sup is None:
        telegram_cards.answer_callback(token, cb_id, text="Supabase 未設定")
        return

    if user_id is None:
        telegram_cards.answer_callback(
            token, cb_id,
            text="未連結 Telegram。請去 Streamlit app 跑一次 scrape 自動連結。",
        )
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sup.table("job_actions").upsert({
            "user_id": user_id,
            "jd_number": jd_number,
            column: now_iso,
            "updated_at": now_iso,
        }).execute()
        label_map = {"save": "已儲存", "hide": "已隱藏", "apply": "已申請"}
        telegram_cards.answer_callback(token, cb_id, text=f"✓ {label_map[kind]}")
    except Exception as e:
        print(f"action upsert failed: {e}", file=sys.stderr)
        telegram_cards.answer_callback(token, cb_id, text="記錄失敗")


# ============================================================
# Local dev / Render fallback
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
