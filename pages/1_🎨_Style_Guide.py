"""Living Style Guide — documents the design system tokens & components.

Open via the multi-page sidebar (auto-discovered by Streamlit).
"""

import streamlit as st

import theme

st.set_page_config(page_title="Style Guide", page_icon="🎨", layout="wide")
theme.apply()

t = theme.tokens()
C, F, SP, R, SH = t["colors"], t["fonts"], t["space"], t["radius"], t["shadow"]


def section_header(num, title, subtitle=""):
    st.markdown(
        f"""<div style="margin: 2rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 1px solid {C['border']};">
        <div style="font-family:{F['mono']}; font-size:11px; color:{C['text_muted']}; letter-spacing:0.6px; text-transform:uppercase;">{num}</div>
        <h2 style="margin:4px 0 4px; font-size:1.5rem; font-weight:700; color:{C['text_primary']};">{title}</h2>
        <div style="color:{C['text_secondary']}; font-size:0.875rem;">{subtitle}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def swatch(hex_code, label, on_dark=False):
    text_color = "#FFFFFF" if on_dark else C["text_primary"]
    return f"""
    <div style="background:{hex_code}; border:1px solid {C['border']}; border-radius:{R['lg']}; padding:14px 16px; box-shadow:{SH['sm']}; margin-bottom:8px;">
      <div style="font-family:{F['sans']}; font-weight:600; font-size:13px; color:{text_color};">{label}</div>
      <div style="font-family:{F['mono']}; font-size:11px; color:{text_color}; opacity:0.75; margin-top:2px;">{hex_code}</div>
    </div>"""


# ============================================================
# Header
# ============================================================
st.markdown(
    f"""<div style="padding:1.5rem 0 1rem;">
    <div style="font-family:{F['mono']}; font-size:11px; color:{C['primary']}; letter-spacing:1px; text-transform:uppercase;">Living Style Guide · v1.0</div>
    <h1 style="margin:6px 0 4px; font-size:2.25rem; font-weight:700;">JobsDB HK 設計系統</h1>
    <div style="color:{C['text_secondary']}; font-size:1rem; max-width:640px;">
      Professional · Efficient · Slate &amp; Blue. 設計 tokens、字體、間距、按鈕、表單、卡片變體全部喺呢度文檔化。Components 喺 streamlit_app.py 入面用 <code>theme.apply()</code> 注入。
    </div>
    </div>""",
    unsafe_allow_html=True,
)

# ============================================================
# 01 Colors
# ============================================================
section_header("01", "Colors", "Semantic tokens — use the role, not the hex.")

st.markdown("##### Brand")
cols = st.columns(4)
for col, key, label in zip(
    cols,
    ["primary", "primary_hover", "primary_active", "primary_subtle"],
    ["primary", "hover", "active", "subtle"],
):
    on_dark = key in ("primary", "primary_hover", "primary_active")
    col.markdown(swatch(C[key], label, on_dark=on_dark), unsafe_allow_html=True)

st.markdown("##### Surfaces")
cols = st.columns(5)
for col, key, label in zip(
    cols,
    ["bg", "surface", "surface_alt", "border", "border_strong"],
    ["bg", "surface", "surface_alt", "border", "border_strong"],
):
    col.markdown(swatch(C[key], label, on_dark=False), unsafe_allow_html=True)

st.markdown("##### Text")
cols = st.columns(3)
for col, key, label in zip(
    cols,
    ["text_primary", "text_secondary", "text_muted"],
    ["primary", "secondary", "muted"],
):
    on_dark = key in ("text_primary", "text_secondary")
    col.markdown(swatch(C[key], label, on_dark=on_dark), unsafe_allow_html=True)

st.markdown("##### Semantic")
cols = st.columns(4)
for col, key, label in zip(
    cols,
    ["success", "warning", "danger", "info"],
    ["success", "warning", "danger", "info"],
):
    col.markdown(swatch(C[key], label, on_dark=True), unsafe_allow_html=True)

# ============================================================
# 02 Typography
# ============================================================
section_header("02", "Typography", "Inter for UI, JetBrains Mono for code & metrics.")

samples = [
    ("Display", "32px", "700", F["sans"], "JobsDB HK 爬蟲"),
    ("H1",      "24px", "700", F["sans"], "搜尋結果"),
    ("H2",      "20px", "600", F["sans"], "爬蟲設定"),
    ("H3",      "16px", "600", F["sans"], "Telegram 通知"),
    ("Body",    "14px", "400", F["sans"], "輸入關鍵字然後點 開始 開始爬蟲。"),
    ("Small",   "12px", "400", F["sans"], "Master xlsx 路徑會自動更新。"),
    ("Caption", "11px", "600", F["sans"], "POSTED DATE"),
    ("Mono",    "14px", "500", F["mono"], "scraper.scrape(args, stop_event)"),
]

for label, size, weight, font, text in samples:
    extras = "text-transform: uppercase; letter-spacing: 0.6px;" if label == "Caption" else ""
    st.markdown(
        f"""<div style="display:flex; align-items:baseline; gap:24px; padding:10px 0; border-bottom:1px dashed {C['border']};">
        <div style="font-family:{F['mono']}; font-size:11px; color:{C['text_muted']}; letter-spacing:0.6px; text-transform:uppercase; width:80px; flex-shrink:0;">{label}</div>
        <div style="font-family:{F['mono']}; font-size:11px; color:{C['text_muted']}; width:90px; flex-shrink:0;">{size} / {weight}</div>
        <div style="font-family:{font}; font-size:{size}; font-weight:{weight}; color:{C['text_primary']}; {extras}">{text}</div>
        </div>""",
        unsafe_allow_html=True,
    )

# ============================================================
# 03 Spacing
# ============================================================
section_header("03", "Spacing scale", "4px base — use tokens, not raw pixels.")
for name, val in SP.items():
    px = int(val.replace("px", ""))
    st.markdown(
        f"""<div style="display:flex; align-items:center; gap:16px; padding:6px 0;">
        <div style="font-family:{F['mono']}; font-size:12px; width:60px; color:{C['text_secondary']}; font-weight:500;">{name}</div>
        <div style="background:{C['primary']}; height:14px; width:{px}px; border-radius:2px;"></div>
        <div style="font-family:{F['mono']}; font-size:12px; color:{C['text_muted']};">{val}</div>
        </div>""",
        unsafe_allow_html=True,
    )

# ============================================================
# 04 Radius & Shadow
# ============================================================
section_header("04", "Radius & Shadow", "Corner radii and elevation tokens.")

st.markdown("##### Radius")
cols = st.columns(len(R))
for col, (name, val) in zip(cols, R.items()):
    rad = "32px" if name == "full" else val
    col.markdown(
        f"""<div style="background:{C['surface']}; border:1px solid {C['border']}; border-radius:{rad}; height:64px; display:flex; align-items:center; justify-content:center; box-shadow:{SH['sm']};">
        <div style="font-family:{F['mono']}; font-size:11px; color:{C['text_secondary']};">{name} · {val}</div>
        </div>""",
        unsafe_allow_html=True,
    )

st.markdown("##### Shadow")
cols = st.columns(len(SH))
for col, (name, val) in zip(cols, SH.items()):
    col.markdown(
        f"""<div style="background:{C['surface']}; border-radius:{R['lg']}; height:72px; box-shadow:{val}; display:flex; align-items:center; justify-content:center; margin:12px 4px;">
        <div style="font-family:{F['mono']}; font-size:11px; color:{C['text_secondary']};">shadow-{name}</div>
        </div>""",
        unsafe_allow_html=True,
    )

# ============================================================
# 05 Buttons
# ============================================================
section_header("05", "Buttons & states", "Primary / secondary / disabled, with hover & focus.")
c1, c2, c3, c4 = st.columns(4)
c1.button("▶ Primary", type="primary", key="sg_primary")
c2.button("Secondary", key="sg_secondary")
c3.button("Disabled", disabled=True, key="sg_disabled")
c4.button("🔔 With icon", key="sg_icon")
st.caption("Hover above to see border/background transitions (120ms ease).")

# ============================================================
# 06 Form components
# ============================================================
section_header("06", "Form components", "Inputs, selectors, checkbox, textarea, file uploader.")
c1, c2 = st.columns(2)
c1.text_input("Keyword", value="Accountant", key="sg_kw")
c2.selectbox("Source", ["jobsdb", "ctgoodjobs", "cpjobs"], key="sg_source")
c1.number_input("Max pages", 0, 999, 0, key="sg_pages")
c2.number_input("Delay (s)", 0.5, 10.0, 1.5, 0.5, key="sg_delay")
st.checkbox("Full JD", value=True, key="sg_fulljd")
st.text_area("Notes", placeholder="Optional context…", key="sg_notes", height=80)
st.file_uploader("Upload CV", type=["pdf", "txt"], key="sg_cv")

# ============================================================
# 07 Cards & Metrics
# ============================================================
section_header("07", "Card variants", "Metric cards, alerts, info panels.")

st.markdown("##### Metric cards")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total jobs", "1,284", "+24")
c2.metric("Saved", "47")
c3.metric("Applied", "12", "+3")
c4.metric("Hidden", "8")

st.markdown("##### Alert cards")
st.info("ℹ Master xlsx 路徑會自動讀取現有 JD 去 dedupe。")
st.success("✓ Scrape 完成 — 24 條新 job 已加入 master。")
st.warning("⚠ Master xlsx is locked (open in Excel?). 暫存緊。")
st.error("✗ Telegram token 無效，請檢查 BotFather。")

st.markdown("##### Custom panel")
st.markdown(
    f"""<div style="background:{C['surface']}; border:1px solid {C['border']}; border-left: 3px solid {C['primary']}; border-radius:{R['md']}; padding:16px 18px; box-shadow:{SH['sm']};">
    <div style="font-family:{F['mono']}; font-size:11px; color:{C['primary']}; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:6px;">Pro Tip</div>
    <div style="color:{C['text_primary']}; font-size:0.9rem;">用 <code style="background:{C['surface_alt']}; padding:2px 6px; border-radius:4px;">--match-threshold 60</code> 過濾 CV 唔啱嘅 job，唔好曬 Telegram。</div>
    </div>""",
    unsafe_allow_html=True,
)

# ============================================================
# 08 Code / Log
# ============================================================
section_header("08", "Code & log blocks", "Dark slate background, monospace.")
st.code(
    """Fetching page 1: https://hk.jobsdb.com/Accountant-jobs?page=1
  page 1: 24 new (cumulative new: 24, dup skipped this run: 0)
Fetching page 2: https://hk.jobsdb.com/Accountant-jobs?page=2
  page 2: 18 new (cumulative new: 42, dup skipped this run: 6)
Done. new=42, dup_skipped=6, telegram_sent=42. CSV: jobsdb_Accountant_20260527_103015.csv""",
    language="log",
)

# ============================================================
# 09 Raw tokens
# ============================================================
section_header("09", "Raw tokens", "Source of truth — copy into Figma / Tailwind / other tools.")
with st.expander("Show JSON dump"):
    st.json(t)
