# Render deployment — `bot_listener_cloud.py`

把 Telegram callback handler 部署去 Render 免費 web service。**5–10 分鐘**搞掂。

## Why Render

| 元件 | 喺邊度 | 點解 |
|---|---|---|
| Scraper（推 Telegram card） | Streamlit Cloud | 已 work |
| **bot_listener_cloud**（接 ← / → / Save / Hide / Apply 嘅 callback） | **Render web service** | Streamlit Cloud 唔俾跑 long-running worker |
| Supabase（共享 job batch 資料） | Supabase cloud | 兩個 service 嘅 single source of truth |

bot_listener_cloud 用 **Telegram webhook**（HTTP POST）而唔係 long-polling，所以可以 fit 落 Render 免費 web tier。

---

## Step 1 — Connect GitHub

1. 去 [render.com](https://render.com) → 用 GitHub login
2. **New +** → **Blueprint**
3. Connect repository：`xavierchow61/jobsdb-scraper`
4. Render 自動讀 `render.yaml` → 建議 `jobradar-bot` web service

如果你唔想用 Blueprint，亦可以 manual：
- New + → Web Service → connect repo
- Runtime: Python 3
- Build: `pip install -r requirements.txt`
- Start: `gunicorn bot_listener_cloud:app --bind 0.0.0.0:$PORT --workers 1 --timeout 30`

## Step 2 — 設 environment variables

去新 service 嘅 **Environment** tab，加：

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 你嘅 BotFather token（同 Streamlit 嗰個一樣） |
| `SUPABASE_URL` | `https://splqyiiejosebqsfvtnv.supabase.co` |
| `SUPABASE_KEY` | 你嘅 anon (public) key |
| `WEBHOOK_SECRET` | （選）隨便一段 random string；唔填亦 work |

點 **Save Changes** — Render 自動 redeploy。

## Step 3 — Verify service 啟動

Render 部署需要 1-3 分鐘。Logs tab 應該見到：
```
Listening at: http://0.0.0.0:10000
```

開瀏覽器：`https://<your-service>.onrender.com/`

應該見：
```json
{
  "status": "ok",
  "service": "jobradar-bot-listener",
  "supabase_ok": true,
  "telegram_token_ok": true
}
```

如果 `supabase_ok=false` 或 `telegram_token_ok=false`，去 Environment tab 檢查 env vars。

## Step 4 — 登記 Telegram webhook

呢一步 link Telegram → 你個 Render service。

**方法 A** — 用內建 endpoint（推薦）：
```
https://<your-service>.onrender.com/set-webhook
```
直接喺瀏覽器開呢個 URL，會自動將 webhook 設成 `https://<your-service>.onrender.com/webhook`。回傳：
```json
{
  "webhook_url": "https://<your-service>.onrender.com/webhook",
  "telegram_response": {"ok": true, "result": true, "description": "Webhook was set"}
}
```

**方法 B** — 用 curl 手動：
```bash
curl -F "url=https://<your-service>.onrender.com/webhook" \
     https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook
```

## Step 5 — 完整流程測試

1. Streamlit Cloud app → 跑一次 scrape
2. Telegram chat 收到一條 message：
   ```
   📦 第 1 / 25 張  ·  cpjobs
   
   📋 [Job title]
   🏢 [Company]
   ...
   
   [← 上一張] [1/25] [下一張 →]
   [⭐ Save] [🚫 Hide] [✅ Applied]
   ```
3. 按 **下一張 →** — message 應該即場 edit 換成第 2 張（半秒內）
4. 按 **⭐ Save** — 應該見到 toast「✓ 已儲存」
5. 喺 Supabase → Table Editor → `job_actions` table，應該見到一條新 row

---

## Troubleshooting

### 按 ← / → 冇反應

**原因 1**：Render service 訓緊（idle > 15 min）。 第一次 wake 需要 30-50 秒。Telegram 會重試。再撳一次。

**原因 2**：Webhook 未設定。去 `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` 睇下，應該返你嘅 Render URL。如果係空，重做 Step 4。

**原因 3**：Supabase 唔通。去 `/` health check，睇 `supabase_ok` 係咪 true。

### 想睇 Telegram 點 callback 你

```
https://api.telegram.org/bot<TOKEN>/getWebhookInfo
```

返：
```json
{
  "ok": true,
  "result": {
    "url": "https://<your-service>.onrender.com/webhook",
    "pending_update_count": 0,
    "last_error_date": null
  }
}
```

如果 `last_error_message` 顯示嘢，係 webhook 有 bug。睇 Render logs。

### Service 經常訓覺

Render free tier 訓覺後喚醒慢。Options：
- **Uptime monitor**：免費 [uptimerobot.com](https://uptimerobot.com)，set 14 分鐘 ping `https://<service>.onrender.com/`，可以 keep alive
- **Upgrade**：Render Starter $7/月，always-on

### 想 disable webhook（回到本機 polling）

```bash
curl https://api.telegram.org/bot<TOKEN>/deleteWebhook
```

之後 `bot_listener.py`（本機 polling 版本）可以正常運行。
