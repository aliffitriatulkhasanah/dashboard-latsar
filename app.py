"""
Dashboard Data Strategis - Kabupaten Tanah Laut
=================================================
Revisi menyeluruh v2: perbaikan bug render HTML, integritas data (NaN handling),
dan peningkatan UI/UX (tipografi, warna, komponen kartu/panel, header konsisten).

CATATAN PENTING soal bug sebelumnya ("</div>" muncul sebagai teks di kartu):
Streamlit merender st.markdown() melalui parser Markdown dulu sebelum HTML mentah
ditampilkan. Baris yang berindentasi >=4 spasi dianggap Markdown sebagai *code block*,
sehingga sebagian tag HTML ikut ter-escape jadi teks literal. Karena f-string
multiline di kode lama mengikuti indentasi kode Python, baris yang "kosong"
(saat trend tidak ada) memicu ini secara tidak konsisten antar kartu.
FIX: semua HTML custom di bawah dibangun sebagai satu baris rata kiri (tanpa
indentasi/newline internal) - lihat helper _html() dan setiap komponen kartu.
"""

import streamlit as st
import pandas as pd
import numpy as np
import json
import os
import html
import base64
import datetime
from streamlit_echarts import st_echarts, JsCode, Map

# ==============================================================================
# 1. KONFIGURASI HALAMAN & KONSTANTA
# ==============================================================================
st.set_page_config(
    page_title="Dashboard Data Strategis BPS Tanah Laut",
    page_icon="bps.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

SHEET_ID = st.secrets.get("SHEET_ID")
PRIMARY = "#4F46E5"
SECONDARY = "#7C3AED"
ACCENT = "#F59E0B"
COLORS = ["#4F46E5", "#F59E0B", "#10B981", "#EC4899", "#06B6D4"]
CARD_ACCENTS = ["#4F46E5", "#F59E0B", "#EC4899", "#06B6D4", "#10B981"]
GEOJSON_PATH = "tanah_laut.geojson"
LOGO_PATH = "bps.png"

REQUIRED_COLUMNS = {
    "Demografi": ["kecamatan", "tahun", "jumlah_penduduk", "lk", "pr", "kepadatan"],
    "Kesejahteraan": ["tahun", "p0", "jml_miskin", "garis_kemiskinan"],
    "PDRB": ["tahun", "sektor", "nilai_adhb", "nilai_adhk", "pe_kalsel"],
    "Inflasi_NTP": ["tahun", "bulan", "inflasi_yoy", "inflasi_mtm", "ntp"],
    "Pertanian": ["tahun", "komoditas", "luas_panen", "produksi"],
}

BREADCRUMB_ICON = {
    "Dashboard Utama": "🏠",
    "Demografi & Sosial": "👥",
    "Ekonomi": "💰",
    "Sektor Pertanian": "🌾",
}

# ==============================================================================
# 2. UTIL: render HTML tanpa jebakan indentasi Markdown
# ==============================================================================
def _html(*parts: str) -> str:
    """Gabungkan potongan HTML jadi SATU baris rata kiri, lalu render.
    Ini menghindari bug Streamlit-Markdown di mana baris berindentasi >=4 spasi
    (termasuk baris kosong/whitespace) dianggap code-block dan HTML-nya bocor
    sebagai teks literal."""
    st.markdown("".join(parts), unsafe_allow_html=True)


# ==============================================================================
# 3. CSS / TEMA
# ==============================================================================
def inject_css(dark: bool):
    bg = "#0B1120" if dark else "#F7F9FC"
    surface = "#161B29" if dark else "#FFFFFF"
    sidebar_bg = "#111827" if dark else "#FFFFFF"
    text = "#E5E7EB" if dark else "#1F2937"
    text_muted = "#9CA3AF" if dark else "#6B7280"
    border = "rgba(255,255,255,0.08)" if dark else "rgba(15,23,42,0.08)"
    shadow = "0 1px 3px rgba(0,0,0,0.4)" if dark else "0 1px 3px rgba(15,23,42,0.06)"
    stripe = "rgba(255,255,255,0.02)" if dark else "rgba(15,23,42,0.015)"

    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {{ color-scheme: {"dark" if dark else "light"} !important; }}
html, body, [class*="css"] {{ font-family: 'Inter', -apple-system, sans-serif !important; }}
#MainMenu, footer {{visibility: hidden;}}
[data-testid="stHeader"] {{background-color: transparent !important;}}
.block-container {{padding-top: 1.2rem !important; padding-bottom: 3rem !important; max-width: 97% !important;}}
.stApp {{ background-color: {bg} !important; }}
[data-testid="stSidebar"] {{ background-color: {sidebar_bg} !important; border-right: 1px solid {border}; }}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.5rem !important; }}
h1, h2, h3, h4, p, label, span, .stMarkdown {{ color: {text}; }}
.stCaption, [data-testid="stCaptionContainer"] {{ color: {text_muted} !important; }}

/* ---- Hero header per halaman ---- */
.app-hero {{
    background: linear-gradient(120deg, {PRIMARY} 0%, {SECONDARY} 55%, #DB2777 100%);
    border-radius: 14px; padding: 22px 28px; margin-bottom: 22px;
    box-shadow: 0 8px 24px rgba(79,70,229,0.28);
}}
.app-hero .breadcrumb {{ color: rgba(255,255,255,0.75); font-size: 0.82rem; font-weight: 600; letter-spacing: 0.4px; text-transform: uppercase; margin-bottom: 4px; }}
.app-hero .title {{ color: #FFFFFF; font-size: 1.55rem; font-weight: 800; line-height: 1.25; margin: 0; }}
.app-hero .subtitle {{ color: rgba(255,255,255,0.85); font-size: 0.9rem; margin-top: 6px; }}

/* ---- Kartu metrik ---- */
.metric-card {{ background-color: {surface}; border: 1px solid {border}; border-left: 4px solid {PRIMARY}; border-radius: 12px; padding: 16px 16px 14px 16px; height: 128px; box-shadow: {shadow}; display: flex; flex-direction: column; justify-content: space-between; transition: transform 0.15s ease; }}
.metric-card:hover {{ transform: translateY(-2px); }}
.metric-card .m-top {{ display:flex; align-items:center; gap:8px; }}
.metric-card .m-icon {{ font-size: 1.1rem; }}
.metric-card .m-label {{ font-size: 0.74rem; font-weight: 700; color: {text_muted}; line-height: 1.25; text-transform: uppercase; letter-spacing: 0.4px; }}
.metric-card .m-value {{ font-size: 1.65rem; font-weight: 800; color: {text}; line-height: 1.1; margin-top: 6px; }}
.metric-card .m-trend {{ font-size: 0.76rem; font-weight: 700; }}
.m-up {{ color: #10B981; }} .m-down {{ color: #EF4444; }} .m-flat {{ color: {text_muted}; }}

/* ---- Kotak interpretasi otomatis ---- */
.insight-box {{ background-color: {surface}; border: 1px solid {border}; border-left: 4px solid {ACCENT}; padding: 14px 18px; border-radius: 10px; margin: 6px 0 22px 0; box-shadow: {shadow}; }}
.insight-title {{ font-weight: 800; margin-bottom: 3px; font-size: 0.88rem; color: {text}; }}
.insight-text {{ font-size: 0.88rem; color: {text_muted}; line-height: 1.5; }}

/* ---- Panel section (pembungkus chart) ---- */
.panel-title {{ font-size: 1.02rem; font-weight: 700; color: {text}; margin-bottom: 2px; }}
.panel-sub {{ font-size: 0.8rem; color: {text_muted}; margin-bottom: 10px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 12px !important; border-color: {border} !important; background-color: {surface} !important; box-shadow: {shadow}; }}

/* ---- Tabel kustom ---- */
.custom-table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 0.88em; border-radius: 8px; overflow: hidden; box-shadow: {shadow}; }}
.custom-table thead tr {{ background-color: {PRIMARY}; text-align: left; }}
.custom-table th, .custom-table td {{ padding: 9px 14px; color: {text}; }}
.custom-table thead th {{ color: #FFFFFF !important; }}
.custom-table tbody tr {{ border-bottom: 1px solid {border}; }}
.custom-table tbody tr:nth-of-type(even) {{ background-color: {stripe}; }}
.custom-table tbody tr:last-of-type {{ border-bottom: 2px solid {PRIMARY}; }}
div[data-testid="column"] .stButton > button {{ padding: 0.25rem 0.6rem; font-size: 0.82rem; }}

.data-error {{ background-color: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25); border-left: 4px solid #EF4444; padding: 12px 16px; border-radius: 8px; margin-bottom: 14px; font-size: 0.86rem; }}
.data-info {{ background-color: rgba(37,99,235,0.08); border: 1px solid rgba(37,99,235,0.2); border-left: 4px solid {PRIMARY}; padding: 10px 16px; border-radius: 8px; margin-bottom: 14px; font-size: 0.85rem; }}
.footer-note {{ text-align:center; opacity:0.55; font-size:0.76rem; margin-top:36px; color: {text_muted}; }}

/* ---- Sidebar polish ---- */
section[data-testid="stSidebar"] .stSelectbox label, section[data-testid="stSidebar"] .stSlider label {{ font-weight: 700; font-size: 0.82rem; }}
.sidebar-brand {{ text-align:center; padding: 4px 0 14px 0; }}
.logo-badge {{ width: 60px; height: 60px; margin: 0 auto; border-radius: 16px; background: linear-gradient(135deg, {PRIMARY} 0%, {SECONDARY} 100%); display: flex; align-items: center; justify-content: center; color: #FFFFFF; font-weight: 800; font-size: 1.15rem; letter-spacing: 0.5px; box-shadow: 0 6px 16px rgba(79,70,229,0.35); }}
.logo-img {{ width: 64px; height: 64px; object-fit: contain; background: #FFFFFF; border-radius: 16px; padding: 8px; box-shadow: 0 6px 16px rgba(30,64,175,0.2); display: block; margin: 0 auto; }}
.logo-caption {{ font-size: 0.86rem; font-weight: 700; color: {text}; margin-top: 8px; }}
.sidebar-caption {{ text-align:center; font-size:0.78rem; color:{text_muted}; margin-top:4px; }}
a.sidebar-link {{ display:block; text-decoration:none !important; }}
a.sidebar-link:hover {{ color:{PRIMARY} !important; text-decoration:underline !important; }}
.nav-group-title {{ font-size: 0.75rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; color: {text_muted}; margin: 14px 0 4px 0; }}

/* ---- Widget bawaan Streamlit: paksa ikut tema ----
   Streamlit punya DUA kemungkinan implementasi selectbox tergantung versi:
   1) BaseWeb lama -> div[data-baseweb="select"]
   2) React Aria Components (versi lebih baru, dipakai Streamlit Cloud saat
      lokal masih versi lama) -> .react-aria-ComboBox / [data-rac] / role=combobox
   Keduanya di-cover sekaligus dengan wildcard + !important supaya app tetap
   konsisten temanya di lokal MAUPUN saat di-deploy, berapa pun versi Streamlit
   yang terpasang di masing-masing environment. */

/* -- BaseWeb (Streamlit versi lama) -- */
div[data-baseweb="select"], div[data-baseweb="select"] * {{ background-color: {surface} !important; color: {text} !important; }}
div[data-baseweb="select"] > div {{ border-color: {border} !important; }}
div[data-baseweb="select"] svg {{ fill: {text_muted} !important; }}
div[data-baseweb="popover"], div[data-baseweb="popover"] *,
div[data-baseweb="menu"], div[data-baseweb="menu"] * {{ background-color: {surface} !important; color: {text} !important; }}
div[data-baseweb="popover"] {{ border: 1px solid {border} !important; }}

/* -- React Aria Components (Streamlit versi baru) -- */
[data-testid="stSelectbox"] [role="group"] {{ background-color: {surface} !important; border: 1px solid {border} !important; border-radius: 8px !important; }}
[data-testid="stSelectbox"] [role="group"], [data-testid="stSelectbox"] [role="group"] * {{ color: {text} !important; }}
[data-testid="stSelectbox"] input[role="combobox"] {{ background-color: transparent !important; color: {text} !important; }}
[data-testid="stSelectbox"] input[role="combobox"]::placeholder {{ color: {text_muted} !important; }}
[data-testid="stSelectbox"] button svg {{ fill: {text_muted} !important; }}
[data-testid="stSelectbox"] [data-rac] {{ background-color: {surface} !important; }}

/* -- Popup/listbox dropdown, apapun implementasinya -- */
[role="listbox"], [role="listbox"] * {{ background-color: {surface} !important; color: {text} !important; }}
[role="listbox"] {{ border: 1px solid {border} !important; border-radius: 8px !important; }}
[role="option"]:hover, [role="option"]:hover * {{ background-color: {stripe if dark else "rgba(37,99,235,0.08)"} !important; }}
[role="option"][aria-selected="true"], [role="option"][aria-selected="true"] * {{ background-color: {"rgba(59,95,224,0.25)" if dark else "rgba(37,99,235,0.12)"} !important; color: {text} !important; font-weight: 600; }}

.stButton > button, .stDownloadButton > button {{ background-color: {surface} !important; color: {text} !important; border: 1px solid {border} !important; box-shadow: {shadow}; }}
.stButton > button:hover, .stDownloadButton > button:hover {{ border-color: {PRIMARY} !important; }}
.stButton > button p, .stDownloadButton > button p {{ color: inherit !important; }}
div[data-testid="stSlider"] [data-testid="stTickBarMin"], div[data-testid="stSlider"] [data-testid="stTickBarMax"] {{ color: {text_muted} !important; }}
.stRadio label p, .stRadio div[role="radiogroup"] label {{ color: {text} !important; }}
[data-testid="stWidgetLabel"] p {{ color: {text} !important; }}

/* ---- Expander (mis. "Kamus Istilah") - belum pernah di-cover sebelumnya,
   makanya headernya masih pakai warna gelap default Streamlit walau app
   sedang light mode. */
[data-testid="stExpander"] {{ background-color: {surface} !important; border: 1px solid {border} !important; border-radius: 10px !important; overflow: hidden; }}
[data-testid="stExpander"] summary {{ background-color: {surface} !important; }}
[data-testid="stExpander"] summary:hover {{ background-color: {stripe} !important; }}
[data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {{ color: {text} !important; }}
[data-testid="stExpander"] summary svg {{ fill: {text_muted} !important; }}
[data-testid="stExpanderDetails"] {{ background-color: {surface} !important; color: {text} !important; }}

/* ---- Tooltip (dari parameter help= pada tombol/widget) - belum pernah
   di-cover, makanya muncul kotak hitam aneh saat hover apapun tema-nya.
   Pakai role="tooltip" DAN partial-match data-testid karena implementasinya
   ternyata beda lagi antar versi Streamlit (pola yang sama seperti kasus
   tombol collapse sidebar sebelumnya). */
[role="tooltip"], [role="tooltip"] *,
[data-testid*="ooltip" i], [data-testid*="ooltip" i] * {{
    background-color: {"#1F2937" if not dark else "#F9FAFB"} !important;
    color: {"#F9FAFB" if not dark else "#1F2937"} !important;
}}
[role="tooltip"], [data-testid*="ooltip" i] {{ border-radius: 6px !important; font-size: 0.8rem !important; border: none !important; }}

/* ---- Tombol collapse/expand sidebar: kontras kurang di mode terang ----
   Pakai partial-match [data-testid*="ollaps"] karena nama testid berbeda
   antar versi Streamlit (stSidebarCollapseButton / stSidebarCollapsedControl /
   collapsedControl, dst) - ini menyapu semua variasinya. */
[data-testid*="ollaps" i] {{ color: {"#E5E7EB" if dark else "#334155"} !important; }}
[data-testid*="ollaps" i] svg {{ fill: {"#E5E7EB" if dark else "#334155"} !important; stroke: {"#E5E7EB" if dark else "#334155"} !important; }}
[data-testid*="ollaps" i] button {{
    background-color: {surface} !important; border: 1.5px solid {border} !important; border-radius: 8px !important;
    box-shadow: {shadow};
}}
[data-testid*="ollaps" i] button:hover {{ border-color: {PRIMARY} !important; }}
[data-testid*="ollaps" i] button:hover svg {{ fill: {PRIMARY} !important; stroke: {PRIMARY} !important; }}

/* Streamlit versi baru pakai Material Symbols (font ligature, bukan svg) untuk
   ikon expand/collapse sidebar - disasar langsung lewat stIconMaterial */
[data-testid="stExpandSidebarButton"], [data-testid="stExpandSidebarButton"] *,
[data-testid="stCollapseSidebarButton"], [data-testid="stCollapseSidebarButton"] *,
[data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapseButton"] *,
[data-testid="stIconMaterial"] {{
    color: {"rgba(250,250,250,0.9)" if dark else "#334155"} !important;
}}
[data-testid="stExpandSidebarButton"]:hover [data-testid="stIconMaterial"],
[data-testid="stCollapseSidebarButton"]:hover [data-testid="stIconMaterial"],
[data-testid="stSidebarCollapseButton"]:hover [data-testid="stIconMaterial"] {{
    color: {PRIMARY} !important;
}}
</style>
""",
        unsafe_allow_html=True,
    )


MAP_TOOLTIP = JsCode(
    """
function(params) {
    if (!params.data) return '<b>' + params.name + '</b><br/>Data Tidak Tersedia';
    let pddk = params.data.pddk !== undefined ? Number(params.data.pddk).toLocaleString('id-ID') : '-';
    let tpt = params.data.tpt !== undefined ? params.data.tpt : '-';
    let miskin = params.data.miskin !== undefined ? params.data.miskin : '-';
    return '<div style="padding:6px 2px;"><b>' + params.name + '</b><br/>' +
           '<hr style="margin:5px 0; border-top:1px solid rgba(255,255,255,0.2);"/>' +
           '\u2022 Jml Pddk: <b>' + pddk + ' Jiwa</b><br/>' +
           '\u2022 TPT: <b>' + tpt + '%</b><br/>' +
           '\u2022 Pddk Miskin: <b>' + miskin + '%</b></div>';
}
"""
)
FMT_ID = JsCode(
    """
function(params) {
    if (Array.isArray(params)) {
        let res = '<b>' + params[0].name + '</b>';
        for (let i = 0; i < params.length; i++) { res += '<br/>' + params[i].marker + params[i].seriesName + ': <b>' + Number(params[i].value).toLocaleString('id-ID') + '</b>'; }
        return res;
    } else {
        return '<b>' + params.name + '</b><br/>' + params.marker + (params.seriesName || '') + ': <b>' + Number(params.value).toLocaleString('id-ID') + '</b>';
    }
}
"""
)

# ==============================================================================
# 4. UTILITAS DATA
# ==============================================================================
def clean_numeric(val):
    """Konversi ke float; nilai kosong/invalid jadi NaN (BUKAN 0) supaya
    tidak menyamarkan data yang sebenarnya hilang saat divisualisasikan."""
    if pd.isna(val):
        return np.nan
    v = str(val).strip().replace(" ", "")
    if v.lower() in ["nan", "none", "null", "-", ""]:
        return np.nan
    if "," in v and "." in v:
        v = v.replace(",", "")
    elif "," in v:
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return np.nan


def fmt_id(value, decimals=0):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    try:
        s = f"{value:,.{decimals}f}" if decimals else f"{value:,.0f}"
        return s.replace(",", "#").replace(".", ",").replace("#", ".")
    except (TypeError, ValueError):
        return str(value)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_data(sheet_name: str):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
    except Exception as e:
        return pd.DataFrame(), f"Gagal mengambil sheet '{sheet_name}': {e}"

    if df.empty:
        return df, f"Sheet '{sheet_name}' kosong atau tidak ditemukan."

    df.columns = df.columns.str.strip().str.lower()
    missing = [c for c in REQUIRED_COLUMNS.get(sheet_name, []) if c not in df.columns]
    if missing:
        return df, f"Sheet '{sheet_name}' kehilangan kolom: {', '.join(missing)}."

    if "tahun" in df.columns:
        df["tahun"] = pd.to_numeric(df["tahun"], errors="coerce")
        df = df.dropna(subset=["tahun"])
        df["tahun"] = df["tahun"].astype(int)

    text_cols = {"kecamatan", "sektor", "komoditas", "bulan", "tahun"}
    for col in df.columns:
        if col not in text_cols:
            df[col] = df[col].apply(clean_numeric)

    return df, None


def get_df(sheet_name: str) -> pd.DataFrame:
    df, err = fetch_data(sheet_name)
    if err:
        _html(f"<div class='data-error'>⚠️ {html.escape(err)}</div>")
    return df


@st.cache_resource(show_spinner=False)
def load_geojson():
    if os.path.exists(GEOJSON_PATH):
        with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


@st.cache_resource(show_spinner=False)
def load_logo_base64():
    """Baca bps.png (harus sejajar dengan app.py) dan encode ke base64
    supaya bisa ditampilkan tanpa request eksternal. None jika file tidak ada."""
    if os.path.exists(LOGO_PATH):
        with open(LOGO_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None


def apply_filter(df: pd.DataFrame, year_range):
    if df.empty or "tahun" not in df.columns:
        return df
    return df[(df["tahun"] >= year_range[0]) & (df["tahun"] <= year_range[1])]


# ==============================================================================
# 5. KOMPONEN UI
# ==============================================================================
def page_header(icon: str, title: str, breadcrumb: str, subtitle: str = ""):
    sub_html = f"<div class='subtitle'>{html.escape(subtitle)}</div>" if subtitle else ""
    _html(
        "<div class='app-hero'>",
        f"<div class='breadcrumb'>{html.escape(breadcrumb)}</div>",
        f"<p class='title'>{icon} {html.escape(title)}</p>",
        sub_html,
        "</div>",
    )


def metric_card(col, icon: str, label: str, value: str, trend: str = None, trend_dir: str = "flat", accent: str = None):
    trend_html = ""
    if trend:
        cls = {"up": "m-up", "down": "m-down", "flat": "m-flat"}.get(trend_dir, "m-flat")
        arrow = {"up": "▲", "down": "▼", "flat": "▬"}.get(trend_dir, "▬")
        trend_html = f"<div class='m-trend {cls}'>{arrow} {html.escape(trend)}</div>"
    style = f" style='border-left-color:{accent};'" if accent else ""
    with col:
        _html(
            f"<div class='metric-card'{style}>",
            f"<div class='m-top'><span class='m-icon'>{icon}</span>"
            f"<span class='m-label'>{html.escape(label)}</span></div>",
            f"<div><div class='m-value'>{html.escape(value)}</div>{trend_html}</div>",
            "</div>",
        )


def insight_box(title: str, text: str):
    _html(
        "<div class='insight-box'>",
        f"<div class='insight-title'>💡 {html.escape(title)}</div>",
        f"<div class='insight-text'>{html.escape(text)}</div>",
        "</div>",
    )


def panel_title(title: str, subtitle: str = ""):
    sub = f"<div class='panel-sub'>{html.escape(subtitle)}</div>" if subtitle else ""
    _html(f"<div class='panel-title'>{html.escape(title)}</div>", sub)


def render_custom_table(df: pd.DataFrame, key: str = "tbl", page_size: int = 10):
    if df.empty:
        st.info("Tidak ada data untuk ditampilkan pada rentang/filter ini.")
        return

    total_rows = len(df)
    total_pages = max(1, -(-total_rows // page_size))  # ceil div
    state_key = f"page_{key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = 1
    # clamp jika data berubah (mis. filter tahun/kecamatan diganti) sehingga halaman lama tidak valid lagi
    st.session_state[state_key] = max(1, min(st.session_state[state_key], total_pages))
    current_page = st.session_state[state_key]

    start = (current_page - 1) * page_size
    end = min(start + page_size, total_rows)
    df_page = df.iloc[start:end]

    thead = "".join(f"<th>{html.escape(str(c))}</th>" for c in df_page.columns)
    rows = []
    for _, row in df_page.iterrows():
        cells = []
        for col_name, val in zip(df_page.columns, row):
            is_tahun_col = str(col_name).strip().lower() == "tahun"
            if pd.isna(val):
                text = "-"
            elif is_tahun_col and isinstance(val, (int, float, np.integer, np.floating)):
                text = str(int(val))  # kolom tahun: bilangan bulat polos, tanpa pemisah ribuan
            elif isinstance(val, (int, np.integer)):
                text = fmt_id(val, 0)
            elif isinstance(val, (float, np.floating)):
                # bilangan bulat (mis. 2020.0, 42633.0) ditampilkan tanpa koma;
                # yang memang punya pecahan (mis. 4.16) tetap pakai koma desimal
                text = fmt_id(val, 0) if float(val).is_integer() else fmt_id(val, 2)
            else:
                text = str(val)
            cells.append(f"<td>{html.escape(text)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    _html(f"<table class='custom-table'><thead><tr>{thead}</tr></thead><tbody>{''.join(rows)}</tbody></table>")

    if total_pages > 1:
        c_prev, c_info, c_next = st.columns([1, 5, 1])
        with c_prev:
            if st.button("◀", key=f"prev_{key}", disabled=current_page <= 1, use_container_width=True):
                st.session_state[state_key] -= 1
                st.rerun()
        with c_info:
            _html(
                f"<div style='text-align:center; padding-top:8px; font-size:0.85rem; white-space:nowrap;'>"
                f"Baris <b>{start + 1}-{end}</b> dari <b>{total_rows}</b> &nbsp;·&nbsp; "
                f"Hal. <b>{current_page}</b>/<b>{total_pages}</b></div>"
            )
        with c_next:
            if st.button("▶", key=f"next_{key}", disabled=current_page >= total_pages, use_container_width=True):
                st.session_state[state_key] += 1
                st.rerun()
    else:
        _html(f"<div style='text-align:center; font-size:0.8rem; opacity:0.6; margin-bottom:6px;'>{total_rows} baris</div>")

    st.download_button(
        "📥 Unduh CSV (semua baris)", data=df.to_csv(index=False).encode("utf-8"),
        file_name="data_export.csv", mime="text/csv", use_container_width=True, key=f"dl_{key}",
    )


def trend_info(current, previous):
    if previous is None or pd.isna(previous) or previous == 0 or pd.isna(current):
        return None, "flat"
    delta = current - previous
    pct = (delta / previous) * 100
    direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
    return f"{pct:+.2f}% dari periode sebelumnya", direction


def section_guard(label: str):
    class _Guard:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is None:
                return False
            # PENTING: st.rerun() / st.stop() bekerja dengan melempar exception
            # internal milik Streamlit sendiri (mis. RerunException) yang HARUS
            # diteruskan, bukan ditangkap di sini - kalau ikut ditelan, rerun jadi
            # gagal dan halaman ke-render dalam state yang tidak konsisten
            # (persis gejala tombol/pager hilang setelah diklik).
            module = getattr(exc_type, "__module__", "") or ""
            if module.startswith("streamlit"):
                return False
            _html(
                f"<div class='data-error'>⚠️ Terjadi kendala saat memuat "
                f"<b>{html.escape(label)}</b>: {html.escape(str(exc_val))}</div>"
            )
            return True

    return _Guard()


# ==============================================================================
# 6. SIDEBAR
# ==============================================================================
with st.sidebar:
    logo_b64 = load_logo_base64()
    if logo_b64:
        _html(
            "<div class='sidebar-brand'>",
            f"<img class='logo-img' src='data:image/png;base64,{logo_b64}'>",
            "<div class='logo-caption'>Kabupaten Tanah Laut</div>",
            "<a class='sidebar-caption sidebar-link' href='https://tanahlautkab.bps.go.id' target='_blank' rel='noopener noreferrer'>tanahlautkab.bps.go.id</a>",
            "</div>",
        )
    else:
        _html(
            "<div class='sidebar-brand'>",
            "<div class='logo-badge'>BPS</div>",
            "<div class='logo-caption'>Kabupaten Tanah Laut</div>",
            "<a class='sidebar-caption sidebar-link' href='https://tanahlautkab.bps.go.id' target='_blank' rel='noopener noreferrer'>tanahlautkab.bps.go.id</a>",
            "</div>",
        )

    tema_gelap = st.toggle("🌙 Mode Gelap", value=False)
    e_theme = "dark" if tema_gelap else "light"

    st.markdown("---")
    _html("<div class='nav-group-title'>Navigasi</div>")
    kategori = st.selectbox(
        "Kategori", ["Dashboard Utama", "Demografi & Sosial", "Ekonomi", "Sektor Pertanian"],
        label_visibility="collapsed",
    )

    sub_kategori = None
    if kategori == "Demografi & Sosial":
        sub_kategori = st.selectbox("Sub-Kategori", ["Kependudukan", "Tenaga Kerja", "Kemiskinan"])
    elif kategori == "Ekonomi":
        sub_kategori = st.selectbox(
            "Sub-Kategori",
            ["Inflasi", "Pertumbuhan Ekonomi", "Struktur PDRB", "Analisis Portofolio & Early Warning"],
        )
    elif kategori == "Sektor Pertanian":
        sub_kategori = st.selectbox("Sub-Kategori", ["Ketahanan Pangan & NTP"])

    _html("<div class='nav-group-title'>Rentang Waktu</div>")
    df_demo_bounds, err_bounds = fetch_data("Demografi")
    if err_bounds or df_demo_bounds.empty:
        min_year, curr_year = 2010, datetime.datetime.now().year
        st.caption(f"⚠️ Rentang tahun pakai default ({min_year}-{curr_year}): {err_bounds or 'data kosong'}")
    else:
        min_year = int(df_demo_bounds["tahun"].min())
        curr_year = int(df_demo_bounds["tahun"].max())
    f_tahun = st.slider("Rentang Tahun", min_year, curr_year, (min_year, curr_year), label_visibility="collapsed")

    _html("<div class='nav-group-title'>Wilayah</div>")
    if not df_demo_bounds.empty and "kecamatan" in df_demo_bounds.columns:
        list_kecamatan = ["Semua Kecamatan"] + sorted(
            [k for k in df_demo_bounds["kecamatan"].dropna().unique() if str(k).lower() != "tanah laut"]
        )
    else:
        list_kecamatan = ["Semua Kecamatan"]
    filter_kec = st.selectbox("Kecamatan", list_kecamatan, label_visibility="collapsed")

    with st.expander("ℹ️ Kamus Istilah"):
        st.caption(
            "**TPT** — Tingkat Pengangguran Terbuka: persentase penduduk usia kerja yang menganggur.\n\n"
            "**P0** — Persentase penduduk miskin terhadap total penduduk.\n\n"
            "**ADHB / ADHK** — PDRB Atas Dasar Harga Berlaku / Konstan: nilai ekonomi dengan harga saat "
            "ini (ADHB) vs harga tahun dasar untuk mengukur pertumbuhan riil (ADHK).\n\n"
            "**NTP** — Nilai Tukar Petani: rasio harga jual hasil pertanian terhadap harga barang yang "
            "dibeli petani. NTP > 100 berarti petani diuntungkan."
        )

    st.markdown("---")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    _html(f"<div class='sidebar-caption'>Sinkron terakhir: {datetime.datetime.now().strftime('%d %b %Y, %H:%M')}</div>")

inject_css(tema_gelap)

target_kec = "tanah laut" if filter_kec == "Semua Kecamatan" else filter_kec.lower()
label_wilayah = "Kab. Tala" if filter_kec == "Semua Kecamatan" else f"Kec. {filter_kec}"
breadcrumb_path = f"{BREADCRUMB_ICON.get(kategori,'📁')} {kategori}" + (f"  ›  {sub_kategori}" if sub_kategori else "")


def show_macro_warning():
    if filter_kec != "Semua Kecamatan":
        _html(
            "<div class='data-info'>📌 <b>Catatan Metodologi:</b> Indikator makro (PDRB, Inflasi, Kemiskinan) "
            "dirilis di tingkat kabupaten. Data berikut merepresentasikan agregat Kabupaten Tanah Laut.</div>"
        )


# ==============================================================================
# 7. ROUTER HALAMAN
# ==============================================================================
if kategori == "Dashboard Utama":
    page_header("📊", "Dashboard Data Strategis Kab. Tanah Laut", breadcrumb_path,
                "Ringkasan agregat lintas indikator kependudukan, sosial, dan ekonomi.")
    show_macro_warning()

    with section_guard("Peta & Ringkasan Utama"):
        df_d = apply_filter(get_df("Demografi"), f_tahun)
        df_k = apply_filter(get_df("Kesejahteraan"), f_tahun)
        df_p = apply_filter(get_df("PDRB"), f_tahun)
        df_i = apply_filter(get_df("Inflasi_NTP"), f_tahun)

        if any(df.empty for df in [df_d, df_k, df_p, df_i]):
            st.warning("Sebagian data belum lengkap untuk rentang tahun/filter ini.")
        else:
            t_akhir = int(df_d["tahun"].max())
            row_target_series = df_d[df_d["kecamatan"].str.lower() == target_kec].sort_values("tahun")
            row_target_now = row_target_series.iloc[-1]
            row_target_prev = row_target_series.iloc[-2] if len(row_target_series) > 1 else None

            c_kes = df_k.sort_values("tahun").iloc[-1]
            c_kes_prev = df_k.sort_values("tahun").iloc[-2] if len(df_k) > 1 else None

            df_pe = df_p.groupby("tahun", as_index=False)["nilai_adhk"].sum().sort_values("tahun")
            pe_growth = (
                ((df_pe.iloc[-1]["nilai_adhk"] - df_pe.iloc[-2]["nilai_adhk"]) / df_pe.iloc[-2]["nilai_adhk"]) * 100
                if len(df_pe) > 1 else np.nan
            )
            c_inf = df_i.sort_values("tahun").iloc[-1]

            with st.container(border=True):
                panel_title("🗺️ Sebaran Spasial", "Arahkan kursor ke tiap kecamatan untuk lihat detail")
                geo_data = load_geojson()
                warna_pilihan = st.radio(
                    "Warnai peta berdasarkan:", ["Jumlah Penduduk", "TPT", "% Penduduk Miskin"],
                    horizontal=True,
                )
                df_kec_now = df_d[(df_d["tahun"] == t_akhir) & (df_d["kecamatan"].str.lower() != "tanah laut")]

                if geo_data and not df_kec_now.empty:
                    has_real_tpt = "tpt" in df_kec_now.columns and df_kec_now["tpt"].notna().any()
                    has_real_miskin = "miskin" in df_kec_now.columns and df_kec_now["miskin"].notna().any()

                    map_data = []
                    for _, r in df_kec_now.iterrows():
                        pddk = r["jumlah_penduduk"] if pd.notna(r["jumlah_penduduk"]) else 0
                        base_tpt = row_target_now.get("tpt", 4.5)
                        base_tpt = base_tpt if pd.notna(base_tpt) else 4.5
                        tpt_val = round(r["tpt"], 2) if has_real_tpt and pd.notna(r.get("tpt")) else round(base_tpt + (pddk % 3 - 1.5), 2)
                        miskin_base = c_kes["p0"] if pd.notna(c_kes["p0"]) else 5.0
                        miskin_val = round(r["miskin"], 2) if has_real_miskin and pd.notna(r.get("miskin")) else round(miskin_base + (pddk % 2 - 1.0), 2)

                        value_map = {"Jumlah Penduduk": pddk, "TPT": tpt_val, "% Penduduk Miskin": miskin_val}
                        map_data.append({
                            "name": r["kecamatan"], "value": value_map[warna_pilihan],
                            "pddk": pddk, "tpt": tpt_val, "miskin": miskin_val,
                            "itemStyle": {"borderWidth": 2.5, "borderColor": ACCENT} if r["kecamatan"].lower() == target_kec else {},
                        })

                    if not (has_real_tpt or has_real_miskin) and warna_pilihan != "Jumlah Penduduk":
                        st.caption("⚠️ Nilai TPT/kemiskinan per kecamatan disimulasikan (data riil per kecamatan belum tersedia).")

                    vmin = min(d["value"] for d in map_data)
                    vmax = max(d["value"] for d in map_data)
                    map_opts = {
                        "backgroundColor": "transparent",
                        "tooltip": {"trigger": "item", "formatter": MAP_TOOLTIP},
                        "visualMap": {
                            "show": True, "min": vmin, "max": vmax, "left": "left", "bottom": "0%",
                            "inRange": {"color": ["#DBEAFE", PRIMARY]},
                            "textStyle": {"color": "#888"}, "calculable": True,
                        },
                        "series": [{
                            # roam dimatikan sengaja - peta ini cuma untuk overview cepat, bukan
                            # eksplorasi detail, jadi zoom/pan malah mengganggu (gampang ke-scroll
                            # tanpa sengaja). Ukurannya diperbesar sebagai gantinya.
                            "type": "map", "map": "TALA", "roam": False, "label": {"show": False},
                            "emphasis": {"label": {"show": True}, "itemStyle": {"areaColor": ACCENT}},
                            "data": map_data,
                        }],
                    }
                    st_echarts(options=map_opts, map=Map("TALA", geo_data), height="560px", theme=e_theme)
                else:
                    st.info("🗺️ Sistem spasial siap. Letakkan berkas `tanah_laut.geojson` sejajar dengan script.")

            st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
            panel_title("📌 Overview Indikator Kunci")

            col1, col2, col3, col4, col5 = st.columns(5)
            t_pddk, t_pddk_dir = trend_info(row_target_now["jumlah_penduduk"], row_target_prev["jumlah_penduduk"] if row_target_prev is not None else None)
            metric_card(col1, "👥", f"Jml. Penduduk · {label_wilayah}", fmt_id(row_target_now["jumlah_penduduk"]), t_pddk, t_pddk_dir, accent=CARD_ACCENTS[0])

            tpt_val = row_target_now.get("tpt", np.nan)
            metric_card(col2, "💼", f"TPT · {label_wilayah}", f"{tpt_val:g}%" if pd.notna(tpt_val) else "Data Kab.", accent=CARD_ACCENTS[1])

            t_p0, t_p0_dir = trend_info(c_kes["p0"], c_kes_prev["p0"] if c_kes_prev is not None else None)
            metric_card(col3, "📉", "% Pend. Miskin · Kab. Tala", f"{c_kes['p0']:g}%" if pd.notna(c_kes["p0"]) else "-", t_p0, t_p0_dir, accent=CARD_ACCENTS[2])

            metric_card(col4, "🛒", "Inflasi (yoy) · Kab. Tala", f"{c_inf['inflasi_yoy']:g}%" if pd.notna(c_inf["inflasi_yoy"]) else "-", accent=CARD_ACCENTS[3])

            pe_dir = "up" if pd.notna(pe_growth) and pe_growth > 0 else ("down" if pd.notna(pe_growth) and pe_growth < 0 else "flat")
            metric_card(col5, "📈", "Pert. Ekonomi · Kab. Tala", f"{pe_growth:.2f}%" if pd.notna(pe_growth) else "-", None, pe_dir, accent=CARD_ACCENTS[4])

            if pd.notna(pe_growth):
                insight_box(
                    "Ringkasan Otomatis",
                    f"Penduduk {label_wilayah} tercatat {fmt_id(row_target_now['jumlah_penduduk'])} jiwa pada {t_akhir}. "
                    f"Tingkat kemiskinan kabupaten berada di {c_kes['p0']:g}%, inflasi tahunan {c_inf['inflasi_yoy']:g}%, "
                    f"dan ekonomi tumbuh {pe_growth:.2f}% dibanding tahun sebelumnya.",
                )
            else:
                insight_box("Ringkasan Otomatis", "Data pertumbuhan ekonomi belum cukup untuk dibandingkan pada rentang tahun ini.")

elif sub_kategori == "Kependudukan":
    page_header("👥", "Analisis Demografi", breadcrumb_path, f"Wilayah terpilih: {label_wilayah}")
    with section_guard("Analisis Demografi"):
        df_d = apply_filter(get_df("Demografi"), f_tahun)
        if df_d.empty:
            st.warning("Data demografi tidak tersedia untuk rentang ini.")
        else:
            df_target = df_d[df_d["kecamatan"].str.lower() == target_kec].sort_values("tahun")
            if df_target.empty:
                st.warning(f"Tidak ada data untuk wilayah '{filter_kec}'.")
            else:
                c1, c2 = st.columns(2)
                with c1:
                    with st.container(border=True):
                        panel_title("Garis Evolusi Populasi")
                        line_opts = {
                            "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "formatter": FMT_ID},
                            "xAxis": {"type": "category", "data": df_target["tahun"].astype(str).tolist()},
                            "yAxis": {"type": "value", "min": "dataMin"},
                            "series": [{"type": "line", "data": df_target["jumlah_penduduk"].tolist(), "areaStyle": {}, "smooth": True, "itemStyle": {"color": COLORS[0]}}],
                        }
                        st_echarts(options=line_opts, height="330px", theme=e_theme)
                with c2:
                    with st.container(border=True):
                        panel_title("Distribusi Gender")
                        last_row = df_target.iloc[-1]
                        pie_opts = {
                            "backgroundColor": "transparent", "tooltip": {"formatter": FMT_ID},
                            "series": [{"type": "pie", "radius": "62%", "data": [
                                {"name": "Laki-laki", "value": last_row["lk"]}, {"name": "Perempuan", "value": last_row["pr"]}
                            ], "itemStyle": {"borderRadius": 4, "borderColor": "#fff", "borderWidth": 2}}],
                        }
                        st_echarts(options=pie_opts, height="330px", theme=e_theme)

                pddk_now, dir_now = trend_info(df_target.iloc[-1]["jumlah_penduduk"], df_target.iloc[-2]["jumlah_penduduk"] if len(df_target) > 1 else None)
                if pddk_now:
                    insight_box("Interpretasi", f"Populasi {label_wilayah} {'naik' if dir_now == 'up' else 'turun'} {pddk_now} dibanding tahun sebelumnya.")

                df_disp = df_target[["tahun", "jumlah_penduduk", "lk", "pr", "kepadatan"]].rename(
                    columns={"tahun": "Tahun", "jumlah_penduduk": "Total Penduduk", "lk": "Laki-laki", "pr": "Perempuan", "kepadatan": "Kepadatan"}
                )
                render_custom_table(df_disp.sort_values("Tahun", ascending=False), key="kependudukan")

elif sub_kategori == "Tenaga Kerja":
    page_header("💼", "Pasar Tenaga Kerja", breadcrumb_path)
    show_macro_warning()
    with section_guard("Tenaga Kerja"):
        df_d = apply_filter(get_df("Demografi"), f_tahun)
        if df_d.empty:
            st.warning("Data tidak tersedia.")
        else:
            df_kab = df_d[df_d["kecamatan"].str.lower() == "tanah laut"].sort_values("tahun").dropna(subset=["tpt"])
            if df_kab.empty:
                st.warning("Kolom TPT belum tersedia pada data kabupaten.")
            else:
                with st.container(border=True):
                    panel_title("Tingkat Pengangguran Terbuka (TPT)")
                    line_opts = {
                        "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "formatter": FMT_ID},
                        "xAxis": {"type": "category", "data": df_kab["tahun"].astype(str).tolist()},
                        "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
                        "series": [{"type": "line", "data": df_kab["tpt"].tolist(), "smooth": True, "itemStyle": {"color": "#EF4444"}, "lineStyle": {"width": 3}, "areaStyle": {"opacity": 0.08}}],
                    }
                    st_echarts(options=line_opts, height="380px", theme=e_theme)
                render_custom_table(df_kab[["tahun", "tpt"]].rename(columns={"tahun": "Tahun", "tpt": "TPT (%)"}).sort_values("Tahun", ascending=False), key="tenaga_kerja")

elif sub_kategori == "Kemiskinan":
    page_header("📉", "Kerentanan Sosial & Kesejahteraan", breadcrumb_path)
    show_macro_warning()
    with section_guard("Kemiskinan"):
        df_k = apply_filter(get_df("Kesejahteraan"), f_tahun).sort_values("tahun")
        if df_k.empty:
            st.warning("Data kesejahteraan tidak tersedia.")
        else:
            c1, c2 = st.columns([1.5, 1])
            with c1:
                with st.container(border=True):
                    panel_title("Jumlah Penduduk Miskin vs Garis Kemiskinan")
                    dual_opts = {
                        "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
                        "legend": {"bottom": 0},
                        "xAxis": {"type": "category", "data": df_k["tahun"].astype(str).tolist()},
                        "yAxis": [{"type": "value", "name": "Jiwa"}, {"type": "value", "name": "Rupiah", "splitLine": {"show": False}}],
                        "series": [
                            {"name": "Jumlah Miskin", "type": "bar", "data": df_k["jml_miskin"].tolist(), "itemStyle": {"color": COLORS[0], "borderRadius": [4, 4, 0, 0]}},
                            {"name": "Garis Kemiskinan", "type": "line", "yAxisIndex": 1, "data": df_k["garis_kemiskinan"].tolist(), "itemStyle": {"color": COLORS[3]}, "lineStyle": {"width": 3}},
                        ],
                    }
                    st_echarts(options=dual_opts, height="420px", theme=e_theme)
            with c2:
                df_disp = df_k[["tahun", "p0", "jml_miskin", "garis_kemiskinan"]].rename(columns={"tahun": "Tahun", "p0": "P0 (%)", "jml_miskin": "Jumlah (Jiwa)", "garis_kemiskinan": "Garis Kemiskinan (Rp)"})
                render_custom_table(df_disp.sort_values("Tahun", ascending=False), key="kemiskinan")

elif sub_kategori == "Inflasi":
    page_header("🛒", "Analisis Volatilitas Harga (Inflasi)", breadcrumb_path)
    show_macro_warning()
    with section_guard("Inflasi"):
        df_i = apply_filter(get_df("Inflasi_NTP"), f_tahun)
        if df_i.empty:
            st.warning("Data inflasi tidak tersedia.")
        else:
            df_i = df_i.copy()
            df_i["periode"] = df_i["bulan"].astype(str) + " " + df_i["tahun"].astype(str)
            with st.container(border=True):
                panel_title("Inflasi YoY vs MtM")
                inf_opts = {
                    "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "formatter": FMT_ID},
                    "legend": {"bottom": 0}, "dataZoom": [{"type": "slider"}],
                    "xAxis": {"type": "category", "data": df_i["periode"].tolist()},
                    "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
                    "series": [
                        {"name": "Inflasi YoY", "type": "line", "data": df_i["inflasi_yoy"].tolist(), "smooth": True, "areaStyle": {"opacity": 0.15}},
                        {"name": "Inflasi MtM", "type": "line", "data": df_i["inflasi_mtm"].tolist(), "smooth": True},
                    ],
                }
                st_echarts(options=inf_opts, height="420px", theme=e_theme)
            render_custom_table(df_i[["periode", "inflasi_yoy", "inflasi_mtm"]].rename(columns={"periode": "Periode", "inflasi_yoy": "YoY (%)", "inflasi_mtm": "MtM (%)"}), key="inflasi")

elif sub_kategori == "Pertumbuhan Ekonomi":
    page_header("📈", "Akselerasi Ekonomi Daerah", breadcrumb_path)
    show_macro_warning()
    with section_guard("Pertumbuhan Ekonomi"):
        df_p = apply_filter(get_df("PDRB"), f_tahun)
        if df_p.empty:
            st.warning("Data PDRB tidak tersedia.")
        else:
            df_pe = df_p.groupby("tahun", as_index=False).agg({"nilai_adhk": "sum", "pe_kalsel": "mean"})
            df_pe["pe_tala"] = df_pe["nilai_adhk"].pct_change() * 100
            df_pe = df_pe.dropna()
            if df_pe.empty:
                st.info("Butuh minimal 2 tahun data untuk menghitung laju pertumbuhan.")
            else:
                c1, c2 = st.columns([1.5, 1])
                with c1:
                    with st.container(border=True):
                        panel_title("Tanah Laut vs Provinsi Kalsel")
                        bench_opts = {
                            "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "formatter": FMT_ID},
                            "legend": {"top": "top"},
                            "xAxis": {"type": "category", "data": df_pe["tahun"].astype(str).tolist()},
                            "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
                            "series": [
                                {"name": "Tanah Laut", "type": "bar", "data": df_pe["pe_tala"].round(2).tolist(), "itemStyle": {"color": COLORS[0], "borderRadius": [4, 4, 0, 0]}},
                                {"name": "Prov. Kalsel", "type": "line", "data": df_pe["pe_kalsel"].tolist(), "itemStyle": {"color": COLORS[1]}, "lineStyle": {"width": 3}, "symbolSize": 8},
                            ],
                        }
                        st_echarts(options=bench_opts, height="420px", theme=e_theme)
                    last = df_pe.iloc[-1]
                    gap = last["pe_tala"] - last["pe_kalsel"]
                    insight_box("Interpretasi", f"Pada {int(last['tahun'])}, pertumbuhan ekonomi Tanah Laut {'melampaui' if gap > 0 else 'di bawah'} rata-rata Provinsi Kalsel sebesar {abs(gap):.2f} poin persentase.")
                with c2:
                    df_disp = df_pe[["tahun", "pe_tala", "pe_kalsel"]].rename(columns={"tahun": "Tahun", "pe_tala": "Tala (%)", "pe_kalsel": "Kalsel (%)"})
                    df_disp["Tahun"] = df_disp["Tahun"].astype(str)
                    render_custom_table(df_disp.sort_values("Tahun", ascending=False), key="pe")

elif sub_kategori == "Struktur PDRB":
    page_header("💰", "Matriks Sektoral Lapangan Usaha", breadcrumb_path)
    show_macro_warning()
    with section_guard("Struktur PDRB"):
        df_p = apply_filter(get_df("PDRB"), f_tahun)
        if df_p.empty:
            st.warning("Data PDRB tidak tersedia.")
        else:
            t_max = int(df_p["tahun"].max())
            df_latest = df_p[df_p["tahun"] == t_max].sort_values("nilai_adhb", ascending=False)
            c_bar, c_tree = st.columns([1.2, 1])
            with c_bar:
                with st.container(border=True):
                    panel_title(f"Pangsa Lapangan Usaha ({t_max})")
                    bar_opts = {
                        "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "formatter": FMT_ID},
                        "grid": {"left": "35%", "bottom": "10%"}, "xAxis": {"type": "value", "show": False},
                        "yAxis": {"type": "category", "data": df_latest["sektor"].tolist()[::-1], "axisLine": {"show": False}},
                        "series": [{"type": "bar", "data": df_latest["nilai_adhb"].tolist()[::-1], "itemStyle": {"color": COLORS[0], "borderRadius": [0, 4, 4, 0]}}],
                    }
                    bar_click = st_echarts(options=bar_opts, height="360px", key="pdrb_bar", on_select="rerun", selection_mode="points", theme=e_theme)
            with c_tree:
                with st.container(border=True):
                    panel_title("Peta Komposisi Treemap")
                    tree_data = [{"name": s, "value": v} for s, v in zip(df_latest["sektor"], df_latest["nilai_adhb"])]
                    tree_opts = {"backgroundColor": "transparent", "tooltip": {"formatter": "{b}: {c}"}, "series": [{"type": "treemap", "data": tree_data, "roam": False, "color": COLORS}]}
                    st_echarts(options=tree_opts, height="360px", theme=e_theme)

            sel_sektor = df_latest.iloc[0]["sektor"]
            if bar_click and "selection" in bar_click and bar_click["selection"].get("point_indices"):
                sel_sektor = df_latest["sektor"].tolist()[::-1][bar_click["selection"]["point_indices"][0]]
            df_tren = df_p[df_p["sektor"] == str(sel_sektor)].sort_values("tahun")
            with st.container(border=True):
                panel_title(f"Dinamika Historis Sektor: {sel_sektor}")
                line_opts = {
                    "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "formatter": FMT_ID},
                    "xAxis": {"type": "category", "data": df_tren["tahun"].astype(str).tolist()},
                    "yAxis": {"type": "value", "axisLabel": {"formatter": JsCode("function(v){return (v/1000000).toFixed(1) + ' T'}")}},
                    "series": [{"type": "line", "smooth": True, "data": df_tren["nilai_adhb"].tolist(), "itemStyle": {"color": COLORS[1]}, "areaStyle": {"opacity": 0.1}}],
                }
                st_echarts(options=line_opts, height="280px", theme=e_theme)

elif sub_kategori == "Analisis Portofolio & Early Warning":
    page_header("📊", "Portofolio Makro & Diagnostik Dini", breadcrumb_path)
    show_macro_warning()
    with section_guard("Analisis Portofolio"):
        df_p = apply_filter(get_df("PDRB"), f_tahun)
        if df_p.empty:
            st.warning("Data PDRB tidak tersedia.")
        else:
            with st.container(border=True):
                t_akhir = int(df_p["tahun"].max())
                df_now = df_p[df_p["tahun"] == t_akhir].copy()
                df_prev = df_p[df_p["tahun"] == (t_akhir - 1)].copy()
                if df_prev.empty:
                    st.info("Butuh data tahun sebelumnya untuk membangun matriks kuadran.")
                else:
                    df_m = pd.merge(df_now, df_prev, on="sektor", suffixes=("_curr", "_prev"))
                    tot_adhb = df_m["nilai_adhb_curr"].sum()
                    true_growth = ((df_m["nilai_adhk_curr"].sum() - df_m["nilai_adhk_prev"].sum()) / df_m["nilai_adhk_prev"].sum()) * 100
                    avg_p = 100.0 / len(df_m)
                    df_m["pangsa"] = (df_m["nilai_adhb_curr"] / tot_adhb) * 100
                    df_m["pertumbuhan"] = ((df_m["nilai_adhk_curr"] - df_m["nilai_adhk_prev"]) / df_m["nilai_adhk_prev"]) * 100
                    scat_data = [{"name": r["sektor"], "value": [round(r["pangsa"], 2), round(r["pertumbuhan"], 2)]} for _, r in df_m.iterrows()]
                    panel_title("Matriks Kinerja Kuadran BCG")
                    scatter_opts = {
                        "backgroundColor": "transparent",
                        "tooltip": {"trigger": "item", "formatter": JsCode(
                            "function(p){if(p.componentType==='markLine'){return p.name+': '+Number(p.value).toFixed(2)+'%';}"
                            "return '<b>'+p.data.name+'</b><br/>Pangsa: '+p.data.value[0]+'%<br/>Growth: '+p.data.value[1]+'%';}"
                        )},
                        "xAxis": {"type": "value", "name": "Pangsa (%)", "nameLocation": "middle", "nameGap": 25},
                        "yAxis": {"type": "value", "name": "Pertumbuhan (%)", "nameLocation": "middle", "nameGap": 30},
                        "series": [{
                            "type": "scatter", "symbolSize": 18, "itemStyle": {"color": COLORS[4], "opacity": 0.85},
                            "data": scat_data, "label": {"show": True, "formatter": "{b}", "position": "right", "fontSize": 10},
                            "markLine": {"animation": False, "lineStyle": {"type": "dashed", "color": "#7F8C8D"},
                                         "data": [{"xAxis": avg_p, "name": "Batas Pangsa"}, {"yAxis": true_growth, "name": "Laju Daerah"}]},
                        }],
                    }
                    st_echarts(options=scatter_opts, height="420px", theme=e_theme)

            st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

            # Heatmap sengaja dibuat full-width (bukan berdampingan dengan scatter) karena
            # butuh ruang horizontal untuk semua tahun x sektor - kalau diperas jadi setengah
            # lebar, sel & labelnya jadi tumpang tindih dan tak terbaca.
            if df_p["tahun"].nunique() < 2:
                st.info("Butuh minimal 2 tahun data untuk heatmap.")
            else:
                df_piv = df_p.pivot_table(index="tahun", columns="sektor", values="nilai_adhk").pct_change() * 100
                df_piv = df_piv.dropna().reset_index()
                sektors = [c for c in df_piv.columns if c != "tahun"]
                years = df_piv["tahun"].astype(str).tolist()
                heat_data = [[y_idx, s_idx, round(row[s], 2)] for y_idx, row in df_piv.iterrows() for s_idx, s in enumerate(sektors)]
                with st.container(border=True):
                    panel_title("Heatmap Pertumbuhan Tahunan", "Geser slider di bawah grafik untuk lihat tahun lainnya")
                    heat_opts = {
                        "backgroundColor": "transparent",
                        "tooltip": {"position": "top", "formatter": JsCode("function(p){return 'Pertumbuhan: <b>' + p.data[2] + '%</b>'}")},
                        "grid": {"top": "5%", "bottom": "22%", "left": "230px", "right": "4%"},
                        "dataZoom": [{"type": "slider", "xAxisIndex": 0, "height": 16, "bottom": "4%"}, {"type": "inside", "xAxisIndex": 0}],
                        "xAxis": {"type": "category", "data": years, "axisLabel": {"fontSize": 12}},
                        "yAxis": {"type": "category", "data": sektors, "axisLabel": {"fontSize": 12, "width": 210, "overflow": "truncate"}},
                        "visualMap": {"min": -5, "max": 10, "calculable": True, "orient": "horizontal", "left": "center", "top": "0%", "inRange": {"color": ["#EF4444", "#FEE2E2", COLORS[0]]}},
                        "series": [{"type": "heatmap", "data": heat_data, "label": {"show": True, "fontSize": 11, "formatter": JsCode("function(p){return p.data[2] + '%'}")}, "itemStyle": {"borderColor": "#fff", "borderWidth": 1}}],
                    }
                    st_echarts(options=heat_opts, height="520px", theme=e_theme)

elif sub_kategori == "Ketahanan Pangan & NTP":
    page_header("🌾", "Kluster Primer & Ketahanan Pangan", breadcrumb_path)
    show_macro_warning()
    with section_guard("Ketahanan Pangan & NTP"):
        df_f = apply_filter(get_df("Pertanian"), f_tahun)
        df_n = apply_filter(get_df("Inflasi_NTP"), f_tahun)
        if df_f.empty or df_n.empty:
            st.warning("Data pertanian/NTP tidak tersedia.")
        else:
            df_padi = df_f[df_f["komoditas"].str.lower() == "padi"].sort_values("tahun")
            df_n = df_n.copy()
            df_n["periode"] = df_n["bulan"].astype(str) + " " + df_n["tahun"].astype(str)
            c_padi, c_ntp = st.columns(2)
            with c_padi:
                if df_padi.empty:
                    st.info("Data komoditas 'Padi' tidak ditemukan.")
                else:
                    with st.container(border=True):
                        panel_title("Luas Panen & Produksi Padi")
                        padi_opts = {
                            "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}, "formatter": FMT_ID},
                            "legend": {"bottom": 0}, "xAxis": {"type": "category", "data": df_padi["tahun"].astype(str).tolist()},
                            "yAxis": [{"type": "value", "name": "Ha", "splitLine": {"show": False}}, {"type": "value", "name": "Ton"}],
                            "series": [
                                {"name": "Luas Panen", "type": "bar", "data": df_padi["luas_panen"].tolist(), "itemStyle": {"color": "#BFDBFE", "borderRadius": [4, 4, 0, 0]}},
                                {"name": "Produksi", "type": "line", "yAxisIndex": 1, "data": df_padi["produksi"].tolist(), "itemStyle": {"color": COLORS[2]}, "lineStyle": {"width": 3}},
                            ],
                        }
                        st_echarts(options=padi_opts, height="380px", theme=e_theme)
            with c_ntp:
                with st.container(border=True):
                    panel_title("Nilai Tukar Petani (NTP)")
                    ntp_opts = {
                        "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "formatter": FMT_ID}, "dataZoom": [{"type": "inside"}],
                        "xAxis": {"type": "category", "data": df_n["periode"].tolist()}, "yAxis": {"type": "value", "scale": True},
                        "series": [{"name": "NTP", "type": "line", "data": df_n["ntp"].tolist(), "itemStyle": {"color": COLORS[1]},
                                    "markLine": {"data": [{"yAxis": 100, "name": "Paritas"}], "lineStyle": {"color": COLORS[3]}}}],
                    }
                    st_echarts(options=ntp_opts, height="380px", theme=e_theme)

            if not df_padi.empty:
                df_disp = df_padi[["tahun", "luas_panen", "produksi"]].rename(columns={"tahun": "Tahun", "luas_panen": "Luas Panen (Ha)", "produksi": "Produksi (Ton)"})
                render_custom_table(df_disp.sort_values("Tahun", ascending=False), key="pertanian")

_html("<div class='footer-note'>Sumber: BPS Kabupaten Tanah Laut · Data disinkronkan otomatis setiap 1 jam</div>")