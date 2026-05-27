"""Glassmorphism design system for JobsDB HK Scraper.

Ported from personal-finance-app's style.py with the slate/blue professional
palette the user originally chose. Public API:

    theme.apply()                  # inject CSS + page chrome (call once per page)
    theme.glass_title(title, ...)  # gradient header
    theme.kpi_card(col, ...)       # frosted KPI card
    theme.glass_card_open/close()  # white frosted container
    theme.status_chip(text, kind)  # inline pill (idle/running/done)
    theme.cloud_banner_html()      # one-line warning banner
    theme.plotly_glass_layout(fig) # transparent chart layout
    theme.render_sidebar_nav()     # branded page_link sidebar
    theme.tokens()                 # token dict for Style Guide
"""

import streamlit as st


# ============================================================
# Palette — Professional Blue Glass
# ============================================================
# Slate background + bright blue accent + warm gold/coral highlights.
# Cohesive with the user's earlier "Bloomberg / Linear" pick, but in a
# glassmorphism dashboard treatment.

PALETTE = {
    # Background gradient layers (light pastel — no deep navy at bottom)
    "bg_a":           "#FAFCFF",     # near-white with hint of blue
    "bg_b":           "#EFF6FF",     # blue-50
    "bg_c":           "#DBEAFE",     # blue-100
    # Text (on light/white cards)
    "text":           "#0F172A",     # slate-900
    "subtext":        "#334155",     # slate-700
    "muted":          "#64748B",     # slate-500
    # Brand
    "accent":         "#3B82F6",     # blue-500 (was 600, slightly lighter)
    "accent_dark":    "#2563EB",     # blue-600
    "accent_subtle":  "#EFF6FF",
    # Semantic
    "success":        "#10B981",     # emerald-500
    "success_subtle": "#D1FAE5",
    "warning":        "#F59E0B",     # amber-500
    "warning_subtle": "#FEF3C7",
    "red":            "#F43F5E",     # rose-500 (softer than red-600)
    "red_subtle":     "#FFE4E6",
    "info":           "#0EA5E9",     # sky-500
    "info_subtle":    "#E0F2FE",
    # Surfaces
    "glass":          "rgba(255,255,255,0.85)",
    "glass_strong":   "rgba(255,255,255,0.95)",
    "glass_border":   "rgba(255,255,255,1)",
    "border":         "#E2E8F0",
    # Sidebar (medium blue gradient — bright but readable with white text)
    "sidebar_a":      "#60A5FA",     # blue-400
    "sidebar_b":      "#3B82F6",     # blue-500
    "sidebar_text":   "#FFFFFF",
    # Code / log block — soft slate paper (was dark + amber — too clashy)
    "code_bg":        "#F1F5F9",     # slate-100 (light glass paper)
    "code_text":      "#1E293B",     # slate-800 (dark mono on light)
}

FONTS = {
    "sans": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang HK', 'Microsoft JhengHei', 'Noto Sans HK', sans-serif",
    "mono": "'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace",
}

SPACE = {"xs": "4px", "sm": "8px", "md": "12px", "lg": "16px",
         "xl": "24px", "2xl": "32px", "3xl": "48px"}

RADIUS = {"sm": "6px", "md": "12px", "lg": "16px", "xl": "20px", "full": "9999px"}

SHADOW = {
    "sm": "0 1px 2px rgba(15, 23, 42, 0.04)",
    "md": "0 8px 24px rgba(37, 99, 235, 0.18)",
    "lg": "0 14px 36px rgba(37, 99, 235, 0.25)",
}


def tokens():
    """Compat: returns token dict for the Style Guide page."""
    # Map glass palette keys back to the previous semantic key names
    colors = {
        "primary": PALETTE["accent"],
        "primary_hover": PALETTE["accent_dark"],
        "primary_active": PALETTE["sidebar_b"],
        "primary_subtle": PALETTE["accent_subtle"],
        "bg": PALETTE["bg_a"],
        "surface": "#FFFFFF",
        "surface_alt": PALETTE["accent_subtle"],
        "border": PALETTE["border"],
        "border_strong": PALETTE["muted"],
        "text_primary": PALETTE["text"],
        "text_secondary": PALETTE["subtext"],
        "text_muted": PALETTE["muted"],
        "success": PALETTE["success"],
        "success_subtle": PALETTE["success_subtle"],
        "warning": PALETTE["warning"],
        "warning_subtle": PALETTE["warning_subtle"],
        "danger": PALETTE["red"],
        "danger_subtle": PALETTE["red_subtle"],
        "info": PALETTE["info"],
        "info_subtle": PALETTE["info_subtle"],
        "code_bg": PALETTE["code_bg"],
        "code_text": PALETTE["code_text"],
    }
    return {
        "colors": colors,
        "fonts": FONTS,
        "space": SPACE,
        "radius": RADIUS,
        "shadow": SHADOW,
    }


# ============================================================
# CSS injection
# ============================================================

def _build_css():
    P = PALETTE
    return f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

/* ============ Background gradient + floating orbs ============ */
.stApp {{
  background: linear-gradient(135deg, {P['bg_a']} 0%, {P['bg_b']} 50%, {P['bg_c']} 100%);
  background-attachment: fixed;
  color: {P['text']};
  font-family: {FONTS['sans']};
}}
.stApp::before {{
  content: ""; position: fixed; top: -10%; right: -10%;
  width: 600px; height: 600px;
  background: radial-gradient(circle, rgba(245,158,11,0.14) 0%, transparent 70%);
  border-radius: 50%; z-index: 0; pointer-events: none;
  animation: floatA 18s ease-in-out infinite;
}}
.stApp::after {{
  content: ""; position: fixed; bottom: -10%; left: -10%;
  width: 500px; height: 500px;
  background: radial-gradient(circle, rgba(244,63,94,0.10) 0%, transparent 70%);
  border-radius: 50%; z-index: 0; pointer-events: none;
  animation: floatB 22s ease-in-out infinite;
}}
@keyframes floatA {{ 0%,100% {{ transform: translate(0,0); }} 50% {{ transform: translate(-30px,40px); }} }}
@keyframes floatB {{ 0%,100% {{ transform: translate(0,0); }} 50% {{ transform: translate(40px,-30px); }} }}

/* ============ Hide default Streamlit chrome ============ */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: transparent !important; backdrop-filter: blur(8px); }}
[data-testid="stSidebarNav"] {{ display: none !important; }}

/* ============ Main container ============ */
.main .block-container {{
  padding-top: 2rem !important;
  padding-bottom: 3rem !important;
  max-width: 1400px;
  position: relative; z-index: 1;
}}

/* ============ Text base (dark on light bg) ============ */
.stApp, .stApp p, .stApp span, .stApp label, .stApp li,
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ color: {P['text']}; }}
.stApp h2, .stApp h3 {{ font-weight: 700; letter-spacing: -0.01em; }}
[data-testid="stCaptionContainer"] {{ color: {P['muted']} !important; }}

/* ============ Sidebar — deep blue gradient + white pill links ============ */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, {P['sidebar_a']} 0%, {P['sidebar_b']} 100%) !important;
  backdrop-filter: blur(8px);
  border-right: 1px solid rgba(255,255,255,0.4);
  box-shadow: 2px 0 12px rgba(59,130,246,0.18);
  position: sticky !important; top: 0 !important; height: 100vh !important;
}}
[data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapsedControl"] {{ display: none !important; }}
[data-testid="stSidebar"] * {{ color: {P['sidebar_text']} !important; }}
[data-testid="stSidebar"] a {{
  background: rgba(255,255,255,0.10) !important;
  border: 1px solid rgba(255,255,255,0.22) !important;
  border-radius: 10px !important;
  padding: 8px 14px !important;
  margin-bottom: 4px !important;
  transition: all 0.25s ease !important;
  font-size: 0.95rem !important;
  min-height: 42px !important; line-height: 1.2 !important;
  display: flex !important; align-items: center !important;
}}
[data-testid="stSidebar"] a:hover {{
  background: rgba(255,255,255,0.22) !important;
  border-color: rgba(255,255,255,0.45);
  transform: translateX(3px);
}}
[data-testid="stSidebar"] a[aria-current="page"] {{
  background: linear-gradient(135deg, rgba(255,255,255,0.30), rgba(255,255,255,0.15)) !important;
  border: 1px solid rgba(255,255,255,0.65) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.4), 0 0 0 2px rgba(245,158,11,0.4) !important;
}}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.18) !important; margin: 0.6rem 0 !important; }}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding-top: 0.8rem !important; }}

/* Sidebar form widgets readable on dark bg */
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] textarea {{
  background: rgba(255,255,255,0.92) !important;
  color: {P['text']} !important;
  border: 1px solid rgba(255,255,255,0.4) !important;
  border-radius: 8px !important;
}}
[data-testid="stSidebar"] input::placeholder {{ color: {P['muted']} !important; }}
[data-testid="stSidebar"] [data-baseweb="select"] * {{ color: {P['text']} !important; }}

/* ============ Buttons ============ */
.stButton > button {{
  background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(255,255,255,0.85));
  color: {P['text']} !important;
  border: 1.5px solid rgba(255,255,255,1);
  border-radius: 12px;
  font-weight: 600;
  font-size: 0.875rem !important;
  padding: 0.5rem 1rem !important;
  min-height: 0 !important;
  box-shadow: 0 4px 14px rgba(37,99,235,0.18), inset 0 1px 0 rgba(255,255,255,0.9);
  transition: all 0.2s ease;
}}
.stButton > button:hover {{
  transform: translateY(-2px);
  box-shadow: 0 8px 22px rgba(37,99,235,0.30), inset 0 1px 0 rgba(255,255,255,0.9);
}}
.stButton > button[kind="primary"] {{
  background: linear-gradient(135deg, {P['accent']} 0%, {P['accent_dark']} 100%) !important;
  color: white !important; border-color: {P['accent_dark']} !important;
}}
.stButton > button[kind="primary"]:hover {{
  background: linear-gradient(135deg, {P['accent_dark']} 0%, {P['sidebar_b']} 100%) !important;
}}
.stButton > button:disabled {{ opacity: 0.45; cursor: not-allowed; transform: none; }}
.stDownloadButton > button {{ font-weight: 600; }}

/* ============ Inputs (main area) ============ */
.main input, .main [data-baseweb="select"] > div, .main textarea {{
  background: rgba(255,255,255,0.95) !important;
  border: 1.5px solid rgba(255,255,255,1) !important;
  border-radius: 10px !important;
  color: {P['text']} !important;
  box-shadow: 0 2px 8px rgba(37,99,235,0.12);
}}
.main input:focus, .main textarea:focus {{
  border-color: {P['accent']} !important;
  box-shadow: 0 0 0 3px rgba(37,99,235,0.2) !important;
}}

/* ============ File uploader ============ */
[data-testid="stFileUploader"] {{
  background: rgba(255,255,255,0.85);
  backdrop-filter: blur(14px);
  border: 2.5px dashed {P['accent']};
  border-radius: 16px;
  padding: 1.2rem;
}}
[data-testid="stFileUploader"] button {{
  background: linear-gradient(135deg, {P['accent']}, {P['accent_dark']}) !important;
  color: white !important;
}}
[data-testid="stFileUploaderDropzone"] * {{ color: {P['text']} !important; }}

/* ============ Expander / Form / Alert containers ============ */
[data-testid="stExpander"], div[data-testid="stForm"] {{
  background: rgba(255,255,255,0.92) !important;
  backdrop-filter: blur(14px);
  border: 2px solid rgba(255,255,255,1) !important;
  border-radius: 16px !important;
  box-shadow: 0 8px 24px rgba(37,99,235,0.15);
}}
[data-testid="stAlert"] {{
  border-radius: 12px;
  border-left: 3px solid;
  font-size: 0.875rem !important;
  padding: 0.6rem 0.85rem !important;
  background: rgba(255,255,255,0.92) !important;
  backdrop-filter: blur(10px);
  box-shadow: 0 4px 12px rgba(37,99,235,0.10);
}}
[data-testid="stAlert"] p {{ margin: 0 !important; line-height: 1.5; }}

/* ============ Plotly + Dataframe ============ */
[data-testid="stPlotlyChart"], [data-testid="stDataFrame"] {{
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(14px);
  border: 2px solid rgba(255,255,255,1);
  border-radius: 16px;
  padding: 0.6rem;
  box-shadow: 0 8px 24px rgba(37,99,235,0.15);
}}

/* ============ Metric cards (default stMetric — kept for fallback) ============ */
[data-testid="stMetric"] {{
  background: rgba(255,255,255,0.95) !important;
  border: 2px solid rgba(255,255,255,1);
  border-radius: 16px;
  padding: 1rem 1.2rem;
  box-shadow: 0 8px 24px rgba(37,99,235,0.18);
}}
[data-testid="stMetricValue"] {{
  font-family: {FONTS['sans']} !important;
  font-weight: 800 !important;
  font-size: 1.85rem !important;
  color: {P['accent']} !important;
}}
[data-testid="stMetricLabel"] {{
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 0.72rem !important;
  font-weight: 600 !important;
  color: {P['muted']} !important;
}}

/* ============ Code block (log) — light glass paper, no color clash ============ */
.stCodeBlock, pre, [data-testid="stCodeBlock"] {{
  background: rgba(241,245,249,0.95) !important;
  border: 2px solid rgba(255,255,255,1) !important;
  border-radius: 14px !important;
  box-shadow: 0 8px 24px rgba(37,99,235,0.12);
}}
.stCodeBlock code, pre code, [data-testid="stCodeBlock"] code {{
  color: {P['code_text']} !important;
  font-family: {FONTS['mono']} !important;
  font-size: 0.8rem !important;
}}

/* ============ Page links (top sub-nav, if used) ============ */
.main [data-testid="stPageLink"] a {{
  background: linear-gradient(135deg, rgba(37,99,235,0.12), rgba(29,78,216,0.05)) !important;
  border: 2px solid rgba(37,99,235,0.4) !important;
  border-radius: 14px !important;
  padding: 0.7rem 1.2rem !important;
  font-weight: 700 !important;
  color: {P['accent_dark']} !important;
  box-shadow: 0 4px 14px rgba(37,99,235,0.15);
}}
.main [data-testid="stPageLink"] a:hover {{
  background: linear-gradient(135deg, {P['accent']}, {P['accent_dark']}) !important;
  color: white !important; transform: translateY(-2px);
}}
.main [data-testid="stPageLink"] a:hover * {{ color: white !important; }}

/* ============ Status chip (custom utility) ============ */
.status-chip {{
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 12px;
  border-radius: 9999px;
  font-family: {FONTS['mono']};
  font-size: 0.75rem; font-weight: 600;
  border: 1.5px solid; white-space: nowrap;
  backdrop-filter: blur(8px);
}}
.status-chip .dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
.status-chip.idle    {{ color: {P['muted']}; border-color: rgba(100,116,139,0.4); background: rgba(255,255,255,0.85); }}
.status-chip.idle .dot    {{ background: {P['muted']}; }}
.status-chip.running {{ color: {P['accent']}; border-color: {P['accent']}; background: rgba(239,246,255,0.95); }}
.status-chip.running .dot {{ background: {P['accent']}; animation: chipPulse 1.4s ease-in-out infinite; }}
.status-chip.done    {{ color: {P['success']}; border-color: {P['success']}; background: rgba(220,252,231,0.95); }}
.status-chip.done .dot    {{ background: {P['success']}; }}
@keyframes chipPulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.35; }} }}

/* ============ Cloud banner (compact) ============ */
.cloud-banner {{
  background: linear-gradient(135deg, rgba(254,243,199,0.95), rgba(255,255,255,0.85));
  backdrop-filter: blur(14px);
  border: 2px solid rgba(245,158,11,0.4);
  border-left: 4px solid {P['warning']};
  border-radius: 12px;
  padding: 8px 14px;
  font-size: 0.78rem;
  color: {P['subtext']};
  margin: 0 0 14px;
  box-shadow: 0 4px 14px rgba(245,158,11,0.15);
}}
.cloud-banner b {{ color: {P['text']}; }}

/* ============ Mini section label ============ */
.section-label {{
  font-family: {FONTS['mono']};
  font-size: 0.7rem; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: {P['accent_dark']};
  margin: 18px 0 8px;
  display: flex; align-items: center; gap: 6px;
}}
.section-label::before {{
  content: ""; width: 3px; height: 14px;
  background: linear-gradient(180deg, {P['accent']}, {P['accent_dark']});
  border-radius: 2px;
}}

/* ============ Scrollbar ============ */
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: rgba(37,99,235,0.08); }}
::-webkit-scrollbar-thumb {{
  background: linear-gradient(180deg, {P['accent']}, {P['accent_dark']});
  border-radius: 5px;
}}
</style>"""


def apply():
    """Inject CSS + render the branded sidebar. Call once per page."""
    st.markdown(_build_css(), unsafe_allow_html=True)


# ============================================================
# Components
# ============================================================

def glass_title(title, emoji="", subtitle="", badge=""):
    """Header with solid color (no gradient — softer, less clashy)."""
    sub_html = (
        f'<p style="color:{PALETTE["muted"]};font-size:0.95rem;'
        f'margin-top:0.3rem;margin-bottom:0;font-weight:500;">{subtitle}</p>'
    ) if subtitle else ""
    badge_html = (
        f'<span style="font-family:{FONTS["mono"]};font-size:0.65rem;'
        f'font-weight:600;letter-spacing:0.08em;'
        f'background:{PALETTE["accent_subtle"]};color:{PALETTE["accent_dark"]};'
        f'padding:3px 8px;border-radius:6px;margin-left:10px;'
        f'vertical-align:middle;">{badge}</span>'
    ) if badge else ""
    html = (
        f'<div style="margin-bottom:1rem;position:relative;z-index:1;">'
        f'<h1 style="'
        f'color:{PALETTE["accent_dark"]};'
        'font-size:2.1rem;font-weight:800;'
        'letter-spacing:0.04em;margin:0;line-height:1.1;display:inline-block;'
        f'">{emoji} {title}</h1>{badge_html}{sub_html}</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def kpi_card(col, label, value, color=None, emoji="", delta=None):
    """Frosted KPI card with corner glow."""
    if color is None:
        color = PALETTE["accent"]
    if isinstance(value, int):
        value_str = f"{value:,}"
    elif isinstance(value, float):
        value_str = f"{value:,.1f}"
    else:
        value_str = str(value)
    delta_html = (
        f'<div style="color:{PALETTE["muted"]};font-size:0.75rem;'
        f'margin-top:6px;font-weight:500;">{delta}</div>'
    ) if delta else ""
    hover_in = (
        "this.style.transform='translateY(-4px)';"
        "this.style.boxShadow='0 14px 36px rgba(37,99,235,0.30)';"
    )
    hover_out = (
        "this.style.transform='translateY(0)';"
        "this.style.boxShadow='0 8px 24px rgba(37,99,235,0.18)';"
    )
    html = (
        f'<div style="'
        'background:white;'
        'border:2px solid rgba(255,255,255,1);'
        'border-radius:16px;padding:1rem 1.25rem;'
        'box-shadow:0 8px 24px rgba(37,99,235,0.18),'
        ' inset 0 1px 0 rgba(255,255,255,0.9);'
        'position:relative;overflow:hidden;'
        'transition:all 0.25s ease;"'
        f' onmouseover="{hover_in}" onmouseout="{hover_out}">'
        f'<div style="position:absolute;top:-25px;right:-25px;'
        'width:80px;height:80px;'
        f'background:radial-gradient(circle,{color}33 0%,transparent 75%);'
        'border-radius:50%;"></div>'
        f'<div style="color:{PALETTE["muted"]};font-size:0.72rem;'
        'font-weight:600;letter-spacing:0.06em;text-transform:uppercase;'
        'position:relative;z-index:1;">'
        f'{emoji} {label}</div>'
        f'<div style="color:{color};font-size:1.85rem;font-weight:800;'
        f'margin-top:6px;line-height:1.1;position:relative;z-index:1;'
        f'font-variant-numeric:tabular-nums;">'
        f'{value_str}</div>'
        f'{delta_html}'
        '</div>'
    )
    col.markdown(html, unsafe_allow_html=True)


def glass_card_open(padding="1.2rem"):
    """Open a frosted-glass container (must pair with glass_card_close)."""
    st.markdown(
        f'<div style="background:rgba(255,255,255,0.92);'
        'backdrop-filter:blur(14px);'
        'border:2px solid rgba(255,255,255,1);'
        f'border-radius:16px;padding:{padding};'
        'box-shadow:0 8px 24px rgba(37,99,235,0.16);'
        'margin-bottom:1rem;position:relative;z-index:1;">',
        unsafe_allow_html=True,
    )


def glass_card_close():
    st.markdown("</div>", unsafe_allow_html=True)


def section_label(text):
    """Mini uppercase section header with side accent bar."""
    st.markdown(f'<div class="section-label">{text}</div>', unsafe_allow_html=True)


def status_chip(text, kind="idle"):
    """Return HTML string for an inline status pill."""
    return f'<span class="status-chip {kind}"><span class="dot"></span>{text}</span>'


def cloud_banner_html(text):
    """Return HTML string for the compact cloud-mode warning banner."""
    return f'<div class="cloud-banner">{text}</div>'


def plotly_glass_layout(fig, height=380):
    """Apply transparent layout so Plotly chart sits inside our glass card."""
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PALETTE["text"], family="Inter, sans-serif"),
        legend=dict(
            bgcolor="rgba(255,255,255,0.7)",
            bordercolor="rgba(37,99,235,0.3)",
            borderwidth=1,
            font=dict(color=PALETTE["text"]),
        ),
        xaxis=dict(
            gridcolor="rgba(37,99,235,0.10)",
            linecolor="rgba(37,99,235,0.3)",
            tickfont=dict(color=PALETTE["subtext"]),
        ),
        yaxis=dict(
            gridcolor="rgba(37,99,235,0.10)",
            linecolor="rgba(37,99,235,0.3)",
            tickfont=dict(color=PALETTE["subtext"]),
        ),
        margin=dict(t=30, b=40, l=50, r=20),
    )


# ============================================================
# Sidebar nav (called from each page after apply())
# ============================================================

def render_sidebar_nav():
    """Branded sidebar with manual page_links — replaces default file-based nav."""
    with st.sidebar:
        st.markdown(
            '<div style="text-align:center;padding:0.6rem 0 0.8rem;'
            'color:white;font-size:1.3rem;font-weight:800;'
            'letter-spacing:0.18em;'
            'text-shadow:0 2px 6px rgba(0,0,0,0.2);">'
            '🎯 JOB RADAR</div>',
            unsafe_allow_html=True,
        )
        st.page_link("streamlit_app.py", label="儀表板", icon="🏠")
        st.page_link("pages/0_⚙_Settings.py", label="設定", icon="⚙")
        st.divider()
