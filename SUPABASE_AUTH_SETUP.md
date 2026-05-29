# Supabase Auth 設定（Phase 3）

從 anon-key + disabled-RLS 升級到 **Supabase Auth + RLS policies**。每個用戶只見自己嘅 batch / actions。

## ⚠ 先備份

跑下面 SQL 之前，**舊嘅 `telegram_batches` 同 `job_actions` 會被清空**（因為冇 user_id 唔可以遷移落 RLS 嘅 policy 入面）。
如果你想保留，先去 Supabase Table Editor download CSV。

## Step 1 — 跑 migration SQL

Supabase project → **SQL Editor** → 新 query → 貼以下：

```sql
-- ============================================================
-- 1. 清掉舊資料（無 user_id 嘅 row）
-- ============================================================
delete from telegram_batches;
delete from job_actions;


-- ============================================================
-- 2. 加 user_id 欄位（references auth.users）
-- ============================================================
alter table telegram_batches
  add column if not exists user_id uuid references auth.users on delete cascade;

alter table job_actions
  add column if not exists user_id uuid references auth.users on delete cascade;

-- job_actions 主鍵改成 (user_id, jd_number) — 同一個 jd 不同 user 可有不同狀態
alter table job_actions drop constraint if exists job_actions_pkey;
alter table job_actions add primary key (user_id, jd_number);


-- ============================================================
-- 3. 新增 chat_id ↔ user_id mapping 表
-- ============================================================
create table if not exists user_telegram (
  user_id    uuid primary key references auth.users on delete cascade,
  chat_id    text not null unique,
  created_at timestamptz default now()
);


-- ============================================================
-- 3b. Per-user 設定（自己嘅 Telegram bot token + chat_id）
-- ============================================================
create table if not exists user_settings (
  user_id          uuid primary key references auth.users on delete cascade,
  telegram_token   text,
  telegram_chat_id text,
  match_threshold  numeric default 0,
  updated_at       timestamptz default now()
);


-- ============================================================
-- 3c. Master jobs table (永久保存累積爬到嘅 job)
-- 取代本機 /tmp/jobs_master.xlsx（雲端 ephemeral 唔可靠）
-- ============================================================
create table if not exists master_jobs (
  user_id          uuid not null references auth.users on delete cascade,
  jd_number        text not null,
  source           text,
  job_title        text,
  company          text,
  salary           text,
  location         text,
  posted_date      text,
  posted_display   text,
  classification   text,
  work_type        text,
  responsibilities text,
  requirements     text,
  benefits         text,
  how_to_apply     text,
  url              text,
  match_score      numeric,
  match_keywords   text,
  scraped_at       timestamptz default now(),
  primary key (user_id, jd_number)
);

create index if not exists idx_master_user_scraped
  on master_jobs (user_id, scraped_at desc);


-- ============================================================
-- 4. 重啟 RLS 並建立 policies
-- ============================================================
alter table telegram_batches enable row level security;
alter table job_actions      enable row level security;
alter table user_telegram    enable row level security;
alter table user_settings    enable row level security;
alter table master_jobs      enable row level security;

-- 之前可能 disable 過 → 先 drop 舊 policy
drop policy if exists "users_own_batches"      on telegram_batches;
drop policy if exists "users_own_actions"      on job_actions;
drop policy if exists "users_own_telegram_map" on user_telegram;
drop policy if exists "users_own_settings"     on user_settings;
drop policy if exists "users_own_master"       on master_jobs;
drop policy if exists "anon_insert_batches"    on telegram_batches;
drop policy if exists "anon_select_batches"    on telegram_batches;
drop policy if exists "anon_update_batches"    on telegram_batches;
drop policy if exists "anon_insert_actions"    on job_actions;
drop policy if exists "anon_select_actions"    on job_actions;
drop policy if exists "anon_update_actions"    on job_actions;

-- 每個 logged-in user 只見/寫自己嘅 row
create policy "users_own_batches" on telegram_batches
  for all to authenticated
  using      (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "users_own_actions" on job_actions
  for all to authenticated
  using      (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "users_own_telegram_map" on user_telegram
  for all to authenticated
  using      (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "users_own_settings" on user_settings
  for all to authenticated
  using      (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "users_own_master" on master_jobs
  for all to authenticated
  using      (auth.uid() = user_id)
  with check (auth.uid() = user_id);
```

點 Run。應該返 `Success`。

## Step 2 — 開啟 Email Auth provider

Supabase project → **Authentication → Providers** → **Email** → 確保 **Enabled** ✓

設定建議：
- ✓ Enable email confirmations（推薦）— 註冊後要驗證 email
- 如果你想方便測試，可以暫時 **Disable email confirmations** — 即時 auto-login

## Step 3 — Streamlit Cloud Secrets

之前已加 `[supabase] url + anon_key`。要確認 `anon_key` **係 anon key**（不是 service_role）。

```toml
[telegram]
token = "..."
chat_id = "..."

[supabase]
url = "https://splqyiiejosebqsfvtnv.supabase.co"
anon_key = "eyJ...anon..."   # ← 必須係 anon，唔可以係 service_role
```

Streamlit 用 anon key + 用戶 auth session → RLS policies 用 `auth.uid()` 識別用戶。

## Step 4 — Render Env Vars

Render dashboard → **Environment** tab，**改名**舊嘅 `SUPABASE_KEY` 做 `SUPABASE_SERVICE_ROLE_KEY`（或者保留 `SUPABASE_KEY`，code 已 fallback）：

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 之前一樣 |
| `SUPABASE_URL` | `https://splqyiiejosebqsfvtnv.supabase.co` |
| **`SUPABASE_SERVICE_ROLE_KEY`** | **新增** — 你嘅 service_role JWT |
| `SUPABASE_KEY` | 可以刪（已 fallback 到 service_role） |
| `WEBHOOK_SECRET` | （選） |

去 Supabase Settings → API 攞 service_role key。**呢個係 secret，不可放 client side！** Render env vars 安全。

點 **Save Changes** — Render 自動 redeploy。

## Step 5 — Verify

### 5.1 Streamlit Cloud

1. Refresh app
2. 應該見到 **登入 / 註冊 / 忘記密碼** tabs
3. 點 ✨ 註冊 → 用你嘅 email + 密碼註冊
4. 如果 email confirmation 開咗 → 去 email click confirm link → 返 Streamlit 登入
5. 登入成功 → 見到首頁 5 tabs + 右上角 `👤 your@email.com` + 🚪 登出 掣

### 5.2 First scrape after auth

1. Tab 🔍 搜尋 & 開始 → 跑一次 scrape
2. Log 應該見到：
   - `[tg-cards] ✓ 已推送 paginated card (batch=xxx, jobs=N)`
3. Supabase Table Editor → `user_telegram` table → 應該有一條新 row link 你嘅 user_id ↔ chat_id
4. `telegram_batches` table → 新 batch，`user_id` 填咗你嘅 uid

### 5.3 Telegram

1. 收到 paginated card
2. 點 ← / → 翻頁應該即時換內容（bot_listener 用 service_role 讀 batch）
3. 點 ⭐ Save → 應該見「✓ 已儲存」toast → `job_actions` table 有新 row（`user_id` 已填）

---

## Troubleshooting

### `auth.uid() = NULL` 喺 policy 入面

代表 client 唔識 attach auth session。Check：
- Supabase client 用緊 **anon key**（不是 service_role）
- `auth.set_session(access, refresh)` 喺每次 page render 都 attach 過

我嘅 `auth.get_supabase()` 已經自動處理。

### Render bot_listener 寫 `job_actions` 失敗

Check Render env：`SUPABASE_SERVICE_ROLE_KEY` 確定係 service_role（從 Supabase Settings → API → service_role）。Service_role bypass RLS，所以不會有 `auth.uid()` 問題。

如果用咗 anon key，會撞 RLS policy 因為 bot_listener 冇 auth session。

### 登入後立即被 log out

Email confirmation 開咗但你未 verify。去 email click link，或者 Supabase Dashboard → Authentication → Settings → 暫時 disable email confirmation。
