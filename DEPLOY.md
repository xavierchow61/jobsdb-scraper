# Deploy to Streamlit Community Cloud

Step-by-step guide to host your JobsDB scraper at `https://<your-app>.streamlit.app` — free.

---

## ⚠ 先了解 Cloud 限制

| 項目 | 限制 |
|---|---|
| RAM | 1 GB |
| Disk | Ephemeral（重啟 = 清光） |
| `sentence-transformers` | **唔裝**（~800MB，會 OOM）— CV match 自動 fallback 去 keyword-only |
| `jobs_master.xlsx` | 唔 persist，每次完要 manually download |
| `bot_listener.py` | **唔可以**喺 Cloud 行（要本機跑） |
| IP | Datacenter IP，有機會俾 JobsDB / CTgoodjobs block |
| Repo | 要 **public**（free tier）|

---

## 1️⃣ Push 上 GitHub

```powershell
cd C:\Users\xavie\jobsdb-scraper

# 第一次 init repo
git init
git branch -M main

# 確認 .gitignore 有保護 config.json / xlsx / pdf
git status

# 應該見到：
#   streamlit_app.py
#   scraper.py
#   theme.py
#   cv_match.py
#   bot.py / bot_listener.py        ← 上唔上都得，cloud 唔會用
#   requirements.txt
#   .streamlit/config.toml
#   .streamlit/secrets.toml.example
#   pages/1_🎨_Style_Guide.py
#   DEPLOY.md / SETUP.md
#   .gitignore
#
# 唔應該見到：
#   config.json                       ← 有 secrets
#   jobs_master.xlsx                  ← 本地 data
#   *.pdf                             ← CV
#   .streamlit/secrets.toml           ← 本地 secrets

git add .
git commit -m "Initial Streamlit version"

# 新建 GitHub repo (用 gh CLI 或者去 github.com/new)
gh repo create jobsdb-scraper --public --source=. --push
```

如果未裝 GitHub CLI，去 [github.com/new](https://github.com/new) 開 repo，跟住：
```powershell
git remote add origin https://github.com/<your-username>/jobsdb-scraper.git
git push -u origin main
```

---

## 2️⃣ 部署到 Streamlit Cloud

1. 去 **[share.streamlit.io](https://share.streamlit.io)** 用 GitHub login
2. 點 **New app**
3. 填：
   - **Repository**: `<your-username>/jobsdb-scraper`
   - **Branch**: `main`
   - **Main file path**: `streamlit_app.py`
   - **App URL**（可選自訂）: `jobsdb-hk` → 出嚟係 `https://jobsdb-hk.streamlit.app`
4. **Advanced settings** → **Python version**: `3.12`
5. 點 **Deploy**

第一次 deploy 要 2-5 分鐘裝 dependencies。睇 logs 確認 build 成功。

---

## 3️⃣ 設定 Secrets（Telegram bot）

部署完之後：

1. 喺 app dashboard 點 **⋮ → Settings → Secrets**
2. Copy `.streamlit/secrets.toml.example` 個內容，**改成你嘅實際 token**：

```toml
[telegram]
token = "你嘅_BotFather_token"
chat_id = "你嘅_chat_id"

[defaults]
source = "cpjobs"
keyword = "Accountant"
location = "Hong Kong Island"
max_pages = 1
delay = 1.5
full_jd = true
match_threshold = 0
```

3. 點 **Save** — app 自動 reload。

---

## 4️⃣ Verify

打開你個 `.streamlit.app` URL：
- 應該見到 ☁ Cloud mode warning
- Sidebar 默認 Telegram token / chat_id 已填好（由 secrets 讀）
- 試按 **🔔 Test Telegram** 確認通訊
- 試 scrape 1 頁，確認攞到 job
- 完咗按 **⬇ 下載 Master xlsx** 儲低（cloud 唔 persist）

---

## 🔄 之後更新 code

```powershell
git add .
git commit -m "Update XYZ"
git push
```

Streamlit Cloud 自動偵測 push，rebuild + redeploy（30 秒 - 2 分鐘）。

---

## 🚧 Troubleshooting

### Build 失敗，log 顯示 `curl_cffi` 唔 install
試 pin 個 version：`curl_cffi==0.7.4` 喺 `requirements.txt`

### 攞到 jobsdb HTTP 403
Datacenter IP 俾 JobsDB block 咗。Options：
- 試下 cpjobs / ctgoodjobs 兩個 source（佢哋通常冇 block）
- 搬去 paid tier（Render / Fly.io 用 residential proxy）
- 自 host 本機 + ngrok 暴露

### RAM OOM
- 確認 `sentence-transformers` 喺 requirements.txt **冇** uncomment
- 一次 scrape 唔好超過 5-10 頁
- 如果係 master xlsx 太大（>5000 jobs），考慮 split

### Master xlsx 想保留
Cloud 唔 persist。Options：
- 每次完手動下載
- 改 code 寫去 Google Drive / S3 / Dropbox（要加 OAuth flow）
- 搬去 paid tier 用 persistent disk

---

## 🆚 Local vs Cloud feature 對比

| Feature | Local (Windows GUI) | Local Streamlit | Cloud Streamlit |
|---|:---:|:---:|:---:|
| JobsDB / CT / cpjobs scrape | ✓ | ✓ | ✓ (可能被 block) |
| Master xlsx persistence | ✓ | ✓ | ✗（要手動下載） |
| Telegram 通知 | ✓ | ✓ | ✓ |
| CV semantic match | ✓ | ✓ | ✗（keyword fallback） |
| CV keyword match | ✓ | ✓ | ✓ |
| Bot listener（Save/Hide/Apply 掣） | ✓ | ✗ | ✗ |
| 定時開始 `--at` | ✓ | ✓ | ✓（要 keep tab 開） |
