"""Legacy redirect stub.

The Settings page used to live here. We collapsed it into 5 sub-tabs on
the main page (streamlit_app.py) — see commit 14108e2. Keep this file
around so old bookmarks (e.g. /⚙_Settings?match_threshold=60) don't
raise StreamlitPageNotFoundError; instead show a friendly notice with a
link back to the home page.
"""

import streamlit as st

import theme

st.set_page_config(page_title="設定 · 已移動", page_icon="↩", layout="wide")
theme.apply()
theme.render_sidebar_nav()

theme.glass_title(
    "設定已合併到首頁",
    emoji="↩",
    subtitle="所有設定（CV 上傳 / 比對分數 / Telegram / 進階）已搬入首頁的 sub-tabs",
)

theme.glass_card_open()
st.markdown(
    """
請點下方按鈕返回首頁。新的介面分成 5 個 sub-tabs：

1. 📄 **上傳 CV** — 上傳 + 編輯 / 新增關鍵字
2. 🎯 **比對分數** — 設定 Telegram 推送下限
3. 📨 **Telegram 通知** — Bot 狀態、啟用、測試
4. 🔍 **搜尋 & 開始** — 來源 / 關鍵字 / 地區 / 頁數 + 進階 + 開始爬蟲
5. 📊 **結果 & 日誌** — KPI / 日誌 / 下載
    """
)
st.page_link("streamlit_app.py", label="返回首頁", icon="🏠")
theme.glass_card_close()
