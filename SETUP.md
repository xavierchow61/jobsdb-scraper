# HK Job Scraper — 安裝指南

歡迎使用 HK 求職爬蟲系統。呢個 README 帶你由零完成 setup。

## 系統做啲咩
- 自動爬 **JobsDB / CTgoodjobs / cpjobs** 三個招聘網
- 將所有 job 累積入一個 **Master Excel** 檔案，自動去重
- 對你嘅 **CV** 做 AI 語意匹配，計分排序
- **Telegram bot** 即時 push 新 job 卡片 + 可以喺手機開新搜尋
- 卡片有 [⭐ Save] [🚫 Hide] [✅ Applied] 按掣

---

## 你需要準備
- Windows 10/11 電腦
- 一個 Telegram account
- 你嘅 CV (PDF)
- 約 30 分鐘做一次性 setup

---

## Step 1. 裝 Python

1. 開 Microsoft Store → 搜 `Python 3.12` (或 3.13) → 撳 **取得 Get**
2. 開新 PowerShell → 打 `python --version` 應該見到版本號

## Step 2. 裝套件

開 PowerShell，cd 入你解壓嘅 `jobsdb-scraper` folder：
```powershell
cd C:\Users\<你個 username>\Downloads\jobsdb-scraper
pip install -r requirements.txt
```

`sentence-transformers` 同 `torch` 比較大 (~250MB)，要等 3-5 分鐘。

## Step 3. 開個 Telegram bot

1. 喺 Telegram 搜 `@BotFather` → start
2. 打 `/newbot`
3. 改名（任意）
4. 改 username（要以 `_bot` 結尾，e.g. `xavier_job_bot`）
5. BotFather 會 send 你**條 token**（一串長字符）── **記住** 條 token

## Step 4. 攞你嘅 chat ID

1. 揀返你新 bot，撳 **Start**
2. 隨便 send 一句嘢 (e.g. "hi") 畀個 bot
3. 喺瀏覽器開：
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   （將 `<TOKEN>` 換做你 step 3 嗰條 token）
4. 出嘅 JSON 入面搵：
   `"chat":{"id":987654321, ...}`
   嗰個數字 = 你嘅 **chat ID**

## Step 5. 第一次跑 GUI

雙擊 `JobsDB Scraper.bat`，個 GUI 會彈出。填：
- **Telegram Bot Token** → 貼 step 3 條 token
- **Telegram Chat ID** → 貼 step 4 個數字
- **CV 檔案** → 撳「瀏覽…」揀你 CV PDF
- **Master Excel 資料庫** → 預設 `jobs_master.xlsx`（喺同一個 folder）
- 其他設定預設就 OK

撳 **開始 Start** 一次（會跑一個小 scrape 同 save config）。

## Step 6. 啟動 Telegram bot listener

雙擊 `Start Bot Listener.bat`。會開一個黑色 console，等到見到：

```
[xx:xx:xx] Bot listening for chat_id=xxxxx
  Bot identity: @你個_bot
```

**唔好閂呢個 console** — 閂咗 bot 就唔再聽指令。

## Step 7. 喺 Telegram 試

返去你個 bot chat，打 `/help` → 應該見到指令列表

之後可以：
- `/scrape` — 一步一步引導開始爬
- `/cv` — 睇/改 CV keyword
- `/find SAP` — 喺 master 搵 job
- `/top 10` — 配對分數最高 10 個

---

## 啲檔案做咩嘅
| 檔案 | 用途 |
|---|---|
| `scraper.py` | 爬蟲核心 + Master Excel + Telegram sender |
| `cv_match.py` | CV 解析 + semantic / keyword scoring |
| `gui.pyw` | 桌面 GUI |
| `bot_listener.py` | Telegram bot 指令 listener |
| `JobsDB Scraper.bat` | 雙擊開 GUI |
| `Start Bot Listener.bat` | 雙擊啟動 bot 後台 |
| `industry_keywords_reference.xlsx` | 16 個行業 keyword 參考 (Excel 開) |
| `config.json` (跑完 GUI 自動產生) | 儲你 bot token + 設定 |
| `jobs_master.xlsx` (跑 scrape 自動產生) | 累積所有 job |

---

## 常見問題

**Q: 跑 GUI 撳 Start 冇反應 / Bot 唔覆**
- 檢查 `config.json` 入面 `tg_token` 同 `tg_chat` 有冇填
- 重啟 `Start Bot Listener.bat`
- 望住 console 見唔見 "Bot listening" 一句

**Q: Telegram 收唔到 卡片**
- 你嘅 bot 一定要 set 過 (上面 Step 3-4)
- chat ID 一定要係**你自己**個 ID，唔可以係 group ID
- 望 console 有冇 "telegram_sent" 大過 0

**Q: 第一次 scrape 好慢**
- 第一次會 download AI 模型（80MB），等 1-2 分鐘
- 之後每個 job ~0.5 秒 + 1.5 秒 delay

**Q: Excel 嘅 Master 開咗，scraper 寫唔到**
- 關咗 Excel 再跑 scraper（Excel 鎖住個檔）

**Q: 我份 CV match 分數普遍好低**
- 喺 Telegram 打 `/cv` 睇下你抽到啲咩 keyword
- 開 `industry_keywords_reference.xlsx` 揀你識嘅 keyword
- 打 `/cv add keyword1, keyword2, ...` 加返

---

## 注意

- 每個用戶要有**自己嘅 bot** ── token 唔可以 share（share 咗等於畀人控制你個 bot）
- 三個招聘網都係 public scrape，但禮貌起見每個 request 之間有 1.5 秒 delay
- 你嘅 CV / master 全部喺本地，唔會 upload 去任何 server
- AI semantic 模型亦係本地跑，唔需要 API key

如有 bug 或建議，搵返畀你個 zip 嘅人。
