"""Design system tokens + CSS injection for the JobsDB Streamlit app.

Theme: Professional efficient — bright blue accent + slate grayscale.
Inspired by Bloomberg / Linear / Vercel.

Usage:
    import theme
    theme.apply()   # call once after st.set_page_config() on every page
"""

import streamlit as st


# ============================================================
# Tokens
# ============================================================

COLORS = {
    # Brand
    "primary":         "#2563EB",   # Blue-600
    "primary_hover":   "#1D4ED8",   # Blue-700
    "primary_active":  "#1E40AF",   # Blue-800
    "primary_subtle":  "#EFF6FF",   # Blue-50

    # Surfaces
    "bg":              "#F8FAFC",   # Slate-50
    "surface":         "#FFFFFF",
    "surface_alt":     "#F1F5F9",   # Slate-100
    "border":          "#E2E8F0",   # Slate-200
    "border_strong":   "#CBD5E1",   # Slate-300

    # Text
    "text_primary":    "#0F172A",   # Slate-900
    "text_secondary":  "#475569",   # Slate-600
    "text_muted":      "#94A3B8",   # Slate-400

    # Semantic
    "success":         "#16A34A",   # Green-600
    "success_subtle":  "#DCFCE7",
    "warning":         "#D97706",   # Amber-600
    "warning_subtle":  "#FEF3C7",
    "danger":          "#DC2626",   # Red-600
    "danger_subtle":   "#FEE2E2",
    "info":            "#0284C7",   # Sky-600
    "info_subtle":     "#E0F2FE",

    # Code
    "code_bg":         "#0F172A",
    "code_text":       "#E2E8F0",
}

FONTS = {
    "sans": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang HK', 'Microsoft JhengHei', 'Noto Sans HK', sans-serif",
    "mono": "'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace",
}

SPACE = {
    "xs":  "4px",
    "sm":  "8px",
    "md":  "12px",
    "lg":  "16px",
    "xl":  "24px",
    "2xl": "32px",
    "3xl": "48px",
}

RADIUS = {
    "sm":   "4px",
    "md":   "6px",
    "lg":   "8px",
    "xl":   "12px",
    "full": "9999px",
}

SHADOW = {
    "sm": "0 1px 2px rgba(15, 23, 42, 0.04)",
    "md": "0 2px 4px rgba(15, 23, 42, 0.06), 0 4px 8px rgba(15, 23, 42, 0.04)",
    "lg": "0 4px 12px rgba(15, 23, 42, 0.08)",
}


def tokens():
    """Return all tokens — used by the Style Guide page."""
    return {
        "colors": COLORS,
        "fonts": FONTS,
        "space": SPACE,
        "radius": RADIUS,
        "shadow": SHADOW,
    }


# ============================================================
# CSS
# ============================================================

CSS = f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {{
  --color-primary:        {COLORS['primary']};
  --color-primary-hover:  {COLORS['primary_hover']};
  --color-primary-active: {COLORS['primary_active']};
  --color-primary-subtle: {COLORS['primary_subtle']};
  --color-bg:             {COLORS['bg']};
  --color-surface:        {COLORS['surface']};
  --color-surface-alt:    {COLORS['surface_alt']};
  --color-border:         {COLORS['border']};
  --color-border-strong:  {COLORS['border_strong']};
  --color-text:           {COLORS['text_primary']};
  --color-text-secondary: {COLORS['text_secondary']};
  --color-text-muted:     {COLORS['text_muted']};
  --color-success:        {COLORS['success']};
  --color-warning:        {COLORS['warning']};
  --color-danger:         {COLORS['danger']};
  --color-info:           {COLORS['info']};
  --color-code-bg:        {COLORS['code_bg']};
  --color-code-text:      {COLORS['code_text']};
  --font-sans:            {FONTS['sans']};
  --font-mono:            {FONTS['mono']};
  --radius-sm:            {RADIUS['sm']};
  --radius-md:            {RADIUS['md']};
  --radius-lg:            {RADIUS['lg']};
  --shadow-sm:            {SHADOW['sm']};
  --shadow-md:            {SHADOW['md']};
}}

/* ===== Base ===== */
html, body, .stApp, [class*="css"] {{
  font-family: var(--font-sans) !important;
  color: var(--color-text);
}}
.stApp {{ background: var(--color-bg); }}
.block-container {{
  padding-top: 1.25rem !important;
  padding-bottom: 2rem !important;
  max-width: 1280px;
}}

/* ===== Typography (with !important to override Streamlit defaults) ===== */
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5,
[data-testid="stHeading"] h1, [data-testid="stHeading"] h2, [data-testid="stHeading"] h3 {{
  font-family: var(--font-sans) !important;
  color: var(--color-text) !important;
  letter-spacing: -0.01em !important;
}}
.stApp h1, [data-testid="stHeading"] h1 {{
  font-weight: 700 !important;
  font-size: 1.5rem !important;
  line-height: 1.25 !important;
  margin-bottom: 0.125rem !important;
  padding-bottom: 0 !important;
}}
.stApp h2, [data-testid="stHeading"] h2 {{
  font-weight: 600 !important;
  font-size: 1.0625rem !important;
  line-height: 1.4 !important;
  margin-top: 1rem !important;
  margin-bottom: 0.375rem !important;
  padding-bottom: 0 !important;
}}
.stApp h3, [data-testid="stHeading"] h3 {{
  font-weight: 600 !important;
  font-size: 0.9375rem !important;
  margin-top: 0.75rem !important;
  margin-bottom: 0.25rem !important;
}}

p, label, span {{ font-family: var(--font-sans); }}
code, pre, kbd {{ font-family: var(--font-mono) !important; font-size: 0.85em; }}

/* ===== Buttons ===== */
.stButton > button {{
  font-family: var(--font-sans);
  font-weight: 500;
  font-size: 0.8125rem !important;
  padding: 0.375rem 0.75rem !important;
  min-height: 0 !important;
  line-height: 1.4 !important;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: var(--shadow-sm);
  transition: all 120ms ease;
}}
.stButton > button:hover {{
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-subtle);
}}
.stButton > button:active {{ transform: translateY(1px); }}
.stButton > button:focus:not(:active) {{
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18);
}}
.stButton > button[kind="primary"] {{
  background: var(--color-primary);
  color: #fff !important;
  border-color: var(--color-primary);
}}
.stButton > button[kind="primary"]:hover {{
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
  color: #fff !important;
}}
.stButton > button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
.stDownloadButton > button {{
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-strong);
  font-weight: 500;
}}

/* ===== Inputs ===== */
.stTextInput input,
.stNumberInput input,
.stDateInput input,
.stTextArea textarea {{
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--color-border) !important;
  background: var(--color-surface) !important;
  font-family: var(--font-sans) !important;
  font-size: 0.875rem !important;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}}
.stTextInput input:focus,
.stNumberInput input:focus,
.stTextArea textarea:focus {{
  border-color: var(--color-primary) !important;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15) !important;
  outline: none !important;
}}
.stSelectbox > div > div {{
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--color-border) !important;
  font-size: 0.875rem !important;
}}
label, .stCheckbox label p {{
  font-weight: 500 !important;
  font-size: 0.8125rem !important;
  color: var(--color-text-secondary) !important;
}}

/* ===== Sidebar ===== */
[data-testid="stSidebar"] {{
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
}}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
  font-size: 0.75rem !important;
  font-weight: 600 !important;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted) !important;
  margin-top: 1rem;
}}
[data-testid="stSidebar"] .stExpander summary {{
  font-size: 0.875rem;
  font-weight: 500;
}}

/* ===== Metrics ===== */
[data-testid="stMetric"] {{
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 1rem 1.125rem;
  box-shadow: var(--shadow-sm);
}}
[data-testid="stMetricValue"] {{
  font-family: var(--font-mono) !important;
  font-weight: 600 !important;
  font-size: 1.5rem !important;
  color: var(--color-text) !important;
}}
[data-testid="stMetricLabel"] {{
  text-transform: uppercase;
  letter-spacing: 0.6px;
  font-size: 0.6875rem !important;
  font-weight: 600 !important;
  color: var(--color-text-muted) !important;
}}

/* ===== Expanders ===== */
[data-testid="stExpander"] {{
  border: 1px solid var(--color-border) !important;
  border-radius: var(--radius-md) !important;
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}}
[data-testid="stExpander"] summary:hover {{ color: var(--color-primary); }}

/* ===== Code block / log ===== */
.stCodeBlock, pre, [data-testid="stCodeBlock"] {{
  background: var(--color-code-bg) !important;
  border-radius: var(--radius-lg) !important;
  border: 1px solid #1E293B !important;
  font-size: 0.8125rem !important;
}}
.stCodeBlock code, pre code, [data-testid="stCodeBlock"] code {{
  color: var(--color-code-text) !important;
  font-family: var(--font-mono) !important;
}}

/* ===== Alerts (st.info/success/warning/error) ===== */
[data-testid="stAlert"] {{
  border-radius: var(--radius-md);
  border-left: 3px solid;
  font-size: 0.8125rem !important;
  padding: 0.5rem 0.75rem !important;
  box-shadow: var(--shadow-sm);
}}
[data-testid="stAlert"] p {{ margin: 0 !important; line-height: 1.5; }}

/* ===== Status chip (custom utility for compact status badge) ===== */
.status-chip {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 9999px;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 500;
  border: 1px solid;
  white-space: nowrap;
}}
.status-chip .dot {{
  width: 6px; height: 6px; border-radius: 50%;
  flex-shrink: 0;
}}
.status-chip.idle    {{ color: {COLORS['text_muted']}; border-color: {COLORS['border']}; background: {COLORS['surface']}; }}
.status-chip.idle .dot    {{ background: {COLORS['text_muted']}; }}
.status-chip.running {{ color: {COLORS['info']}; border-color: {COLORS['info']}; background: {COLORS['info_subtle']}; }}
.status-chip.running .dot {{ background: {COLORS['info']}; animation: chipPulse 1.4s ease-in-out infinite; }}
.status-chip.done    {{ color: {COLORS['success']}; border-color: {COLORS['success']}; background: {COLORS['success_subtle']}; }}
.status-chip.done .dot    {{ background: {COLORS['success']}; }}
@keyframes chipPulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.35; }} }}

/* ===== Compact cloud banner ===== */
.cloud-banner {{
  background: {COLORS['warning_subtle']};
  border: 1px solid #FDE68A;
  border-left: 3px solid {COLORS['warning']};
  border-radius: var(--radius-md);
  padding: 6px 12px;
  font-size: 0.75rem;
  color: {COLORS['text_secondary']};
  margin: 0 0 12px;
}}
.cloud-banner b {{ color: {COLORS['text_primary']}; }}
.cloud-banner code {{
  background: rgba(0,0,0,0.05);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.95em;
}}

/* ===== App header (replaces st.title for tighter control) ===== */
.app-title {{
  font-family: var(--font-sans);
  font-size: 1.375rem;
  font-weight: 700;
  letter-spacing: -0.015em;
  color: {COLORS['text_primary']};
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}}
.app-title .badge {{
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: 500;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  background: {COLORS['primary_subtle']};
  color: {COLORS['primary']};
  padding: 2px 6px;
  border-radius: 4px;
}}
.app-subtitle {{
  font-size: 0.75rem;
  color: {COLORS['text_muted']};
  margin: 2px 0 14px;
}}

/* ===== File uploader ===== */
[data-testid="stFileUploader"] section {{
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface-alt);
}}

/* ===== Divider ===== */
hr {{ border-color: var(--color-border); }}

/* ===== Caption ===== */
.stCaption, [data-testid="stCaptionContainer"] {{
  color: var(--color-text-muted) !important;
  font-size: 0.8125rem;
}}
</style>"""


def apply():
    """Inject design tokens + CSS into the current Streamlit page.

    Call once near the top of every page, after st.set_page_config().
    """
    st.markdown(CSS, unsafe_allow_html=True)
