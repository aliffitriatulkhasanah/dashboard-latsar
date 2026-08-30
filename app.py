"""
Dashboard Data Strategis - Kabupaten Tanah Laut
=================================================
Revisi v3: rombak total mengikuti prototype desain baru (nav-bar + landing page
+ 7 halaman: Dashboard Utama, Kependudukan, Tenaga Kerja, Kemiskinan, IPM,
Inflasi, Pertumbuhan Ekonomi, Pertanian) dan struktur database Excel baru
(sheet: Kependudukan, Tenaga Kerja, Kemiskinan_IPM, PDRB, Inflasi_NTP, Pertanian).

CSS, helper komponen (_html, page_header, metric_card, insight_box, panel_title,
render_custom_table+pagination, section_guard, dst) di-reuse dari versi
sebelumnya karena sudah teruji lewat banyak putaran perbaikan (bug rendering
HTML, dark/light mode, responsivitas, dsb) - lihat komentar di masing-masing
fungsi untuk detail kenapa ditulis seperti itu.

Patch (Agustus 2026): get_komoditas() dibuat mendeteksi baris header nama
bulan secara otomatis (bukan hardcode iloc[1]) - supaya tahan kalau sheet
"Komoditas" di Google Sheets ke-geser barisnya saat diedit manual, dan
memunculkan pesan error yang jelas kalau header tetap tidak ketemu.

Patch (Agustus 2026, ronde 2):
- Bubble chart Top 10 komoditas (halaman Inflasi) sekarang pakai IHK PER
  KOMODITAS bulan berjalan (sheet "IHK Komoditas") sebagai sumbu-X, apple to
  apple dengan andil m-to-m bulan berjalan di sumbu-Y - sebelumnya sempat pakai
  IHK Tanah Laut (bukan per komoditas) lalu dirata-rata, ternyata datanya ADA
  di sheet tersendiri jadi tidak perlu didekati/dirata-ratakan lagi.
- Ditambah kotak dokumen Bahan Rilis Inflasi di halaman Inflasi - sumbernya
  link Google Drive di sheet Inflasi_NTP kolom "bahan_rilis" (bahan rilis
  bulan TERBARU yang sudah terisi), bukan berkas lokal.
- Ditambah halaman baru "Track Record Inflasi" di sub-kategori Ekonomi.
- Slider "Rentang Waktu" dihilangkan dari sidebar saat kategori = Dashboard
  Utama (halaman itu memang selalu menampilkan data TERBARU, tidak difilter).

Patch (Agustus 2026, ronde 3):
- Interpretasi otomatis bubble chart komoditas diseragamkan sesuai template
  yang diminta: pendorong/penahan bulan berjalan (andil tertinggi/terendah
  bulan itu saja) + komoditas paling konsisten sepanjang tahun berjalan
  (frekuensi top-10 terbanyak).
- Filter multiselect "Kelompok Pengeluaran" (Track Record Inflasi) dirapikan:
  batas maksimal 3 pilihan ditegakkan manual (bukan lewat max_selections
  bawaan) supaya pesannya bisa di-custom dan tag pilihan tidak lagi
  terpotong/di-scroll horizontal - dibuat wrap ke baris baru.
- Dokumen Bahan Rilis Inflasi dipindah dari berkas lokal ke link Google
  Drive per baris bulan di sheet Inflasi_NTP (kolom "bahan_rilis").
"""
import streamlit as st
import pandas as pd
import numpy as np
import json
import os
import re
import html
import base64
import datetime
from urllib.parse import quote
from streamlit_echarts import st_echarts, JsCode, Map

# ==============================================================================
# 1. KONFIGURASI HALAMAN & KONSTANTA
# ==============================================================================
st.set_page_config(
    page_title="Dashboard Data Strategis BPS Tanah Laut",
    page_icon="bps.png",
    layout="wide",
    initial_sidebar_state="auto",
)

# PENTING: Streamlit melarang mengubah st.session_state[key] milik sebuah widget
# SETELAH widget itu di-render di run yang sama - walau langsung disusul st.rerun().
# Makanya drill-down "klik peta -> ubah pilihan kecamatan" tidak bisa langsung
# menulis ke session_state["kepen_wilayah"] (key milik st.selectbox di sidebar).
# Solusinya: klik menulis ke key "pending" terpisah, lalu di SINI - sebelum
# selectbox itu sempat di-render - nilai pending dipindahkan ke key aslinya.
if "kepen_wilayah_pending" in st.session_state:
    st.session_state["kepen_wilayah"] = st.session_state.pop("kepen_wilayah_pending")

SHEET_ID = st.secrets.get("SHEET_ID", "1nQh8AezWpM8TfsaknlNO922yqqBWWBfDKah4fm9tpHU")
PRIMARY = "#4F46E5"
SECONDARY = "#7C3AED"
ACCENT = "#F59E0B"
COLORS = ["#4F46E5", "#F59E0B", "#10B981", "#EC4899", "#06B6D4", "#D97706"]
CARD_ACCENTS = ["#4F46E5", "#F59E0B", "#EC4899", "#06B6D4", "#10B981"]
GEOJSON_PATH = "tanah_laut.geojson"
LOGO_PATH = "bps.png"

REQUIRED_COLUMNS = {
    "Kependudukan": ["tahun", "kecamatan", "jumlah_penduduk", "kepadatan", "pertumbuhan", "lk", "pr", "rasio_jk"],
    "Tenaga Kerja": ["tahun", "tpt", "tpak", "bekerja", "pengangguran", "sekolah", "mengurus rt", "lainnya", "r_ketergantungan"],
    "Kemiskinan_IPM": ["tahun", "p0", "p1", "p2", "jml_miskin", "garis_kemiskinan", "gini", "ipm", "ipm_kalsel", "ipg", "idg", "ikg"],
    "PDRB": ["tahun", "nilai_adhb", "nilai_adhk", "pert_eko", "pdptn_perkapita_adhk"],
    "Inflasi_NTP": ["tahun", "bulan", "ihk", "inflasi_mtm", "inflasi_ytd", "inflasi_yoy", "ntp"],
    "Pertanian": ["tahun", "komoditas", "luas_panen", "produksi"],
    "Harga": ["tahun", "bulan", "minggu", "bawang merah", "bawang putih", "beras", "daging ayam ras", "telur ayam ras", "ikan gabus", "ikan nila", "gula pasir", "minyak goreng", "cabai rawit"],
}

BREADCRUMB_ICON = {
    "Dashboard Utama": "🏠",
    "Demografi & Sosial": "👥",
    "Ekonomi": "💰",
    "Pertanian": "🌾",
}

# Urutan bulan Indonesia (dipakai untuk sorting/pivot, karena default alfabetis salah urutan)
BULAN_URUT = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
# Sheet "Harga" pakai singkatan bulan (Jan, Feb, ...), sementara sheet lain (Inflasi_NTP,
# Komoditas) pakai nama penuh - mapping ini menjembatani keduanya.
BULAN_ABBR_MAP = {"Jan": "Januari", "Feb": "Februari", "Mar": "Maret", "Apr": "April", "Mei": "Mei", "Juni": "Juni", "Juli": "Juli", "Agu": "Agustus", "Agt": "Agustus"}
# Singkatan 3-huruf dipakai untuk label sumbu-X yang lebih padat di halaman
# "Track Record Inflasi" (data 31 bulan berturut-turut - label penuh terlalu panjang).
BULAN_ABBR3 = {"Januari": "Jan", "Februari": "Feb", "Maret": "Mar", "April": "Apr", "Mei": "Mei", "Juni": "Jun", "Juli": "Jul", "Agustus": "Agu", "September": "Sep", "Oktober": "Okt", "November": "Nov", "Desember": "Des"}
# Nama 11 kelompok pengeluaran (COICOP) di sheet sumber cukup panjang (mis.
# "Perumahan, Air, Listrik, Gas, dan Bahan Bakar Lainnya") - kalau dipakai
# apa adanya sebagai label tag di widget multiselect, teksnya kepotong di
# segala sisi karena tag jadi lebih lebar dari kotak widget. Dipetakan ke
# versi ringkas HANYA untuk tampilan widget (dropdown & tag terpilih); nilai
# yang dipakai untuk filter data tetap nama aslinya dari sheet.
COICOP_SHORT_LABEL = {
    "Makanan, Minuman, dan Tembakau": "Makanan, Minuman & Tembakau",
    "Pakaian dan Alas Kaki": "Pakaian & Alas Kaki",
    "Perumahan, Air, Listrik, Gas, dan Bahan Bakar Lainnya": "Perumahan & Utilitas",
    "Perlengkapan, Peralatan, dan Pemeliharaan Rutin Rumah Tangga": "Perlengkapan Rumah Tangga",
    "Kesehatan": "Kesehatan",
    "Transportasi": "Transportasi",
    "Informasi, Komunikasi, dan Jasa Keuangan": "Info, Komunikasi & Keuangan",
    "Rekreasi, Olahraga, dan Budaya": "Rekreasi, Olahraga & Budaya",
    "Pendidikan": "Pendidikan",
    "Penyediaan Makanan dan Minuman/Restoran": "Makanan & Minuman Jadi/Restoran",
    "Perawatan Pribadi dan Jasa Lainnya": "Perawatan Pribadi & Jasa Lainnya",
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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@1,600;1,700;1,800&display=swap');

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

/* ---- Header halaman: judul italic serif polos (sesuai prototype - tanpa
   hero gradient/breadcrumb, cukup judul besar + subjudul kecil di bawahnya) ---- */
.page-title {{ font-family: 'Playfair Display', Georgia, serif; font-style: italic; font-weight: 700;
    font-size: 3rem !important; color: {text}; margin: 0 0 4px 0; line-height: 1.2; }}
.page-subtitle {{ font-size: 0.95rem; color: {text_muted}; margin-bottom: 22px; }}
.page-header-wrap {{ margin-bottom: 24px; }}

/* ---- Kartu metrik (varian solid - dipakai di dalam halaman detail) ---- */
.metric-card {{ background-color: {surface}; border: 1px solid {border}; border-left: 4px solid {PRIMARY}; border-radius: 12px; padding: 16px 16px 14px 16px; min-height: 96px; box-shadow: {shadow}; display: flex; flex-direction: column; justify-content: flex-start; transition: transform 0.15s ease; }}
.metric-card:hover {{ transform: translateY(-2px); }}
.metric-card .m-top {{ display:flex; align-items:center; gap:8px; }}
.metric-card .m-icon {{ font-size: 1.1rem; }}
.metric-card .m-label {{ font-size: 0.74rem; font-weight: 700; color: {text_muted}; line-height: 1.25; text-transform: uppercase; letter-spacing: 0.4px; }}
.metric-card .m-value {{ font-size: 1.65rem; font-weight: 800; color: {text}; line-height: 1.1; margin-top: 6px; }}
.metric-card .m-trend {{ font-size: 0.76rem; font-weight: 700; }}

/* ---- Kartu metrik varian OUTLINE (khusus landing page "Dashboard Utama" -
   sesuai prototype: kotak dengan border oranye/emas tipis, tanpa fill warna,
   label di atas dan angka besar di bawah, rata tengah) ---- */
.metric-card-outline {{ background-color: {surface}; border: 1.5px solid {ACCENT}; border-radius: 10px; padding: 18px 14px; min-height: 96px; margin-bottom: 12px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 6px; transition: transform 0.15s ease, box-shadow 0.15s ease; }}
.metric-card-outline:hover {{ transform: translateY(-2px); box-shadow: {shadow}; }}
.metric-card-outline .mo-label {{ font-size: 0.78rem; font-weight: 700; color: {text_muted}; }}
.metric-card-outline .mo-value {{ font-size: 1.5rem; font-weight: 800; color: {text}; }}
.metric-card-outline .mo-trend {{ font-size: 0.76rem; font-weight: 700; }}
.m-up {{ color: #10B981; }} .m-down {{ color: #EF4444; }} .m-flat {{ color: {text_muted}; }}

/* ---- Kotak interpretasi otomatis ---- */
.insight-box {{ background-color: {surface}; border: 1px solid {border}; border-left: 4px solid {ACCENT}; padding: 14px 18px; border-radius: 10px; margin: 6px 0 22px 0; box-shadow: {shadow}; }}
.insight-title {{ font-weight: 800; margin-bottom: 3px; font-size: 0.88rem; color: {text}; }}
.insight-text {{ font-size: 0.88rem; color: {text_muted}; line-height: 1.5; }}

/* ---- Kotak dokumen PDF (halaman Inflasi) - kartu klik-utuh berbentuk link,
   supaya klik di mana pun di kartu langsung membuka dokumen. ---- */
.pdf-card {{ display:flex; align-items:flex-start; gap:14px; background-color: {surface}; border: 1px solid {border}; border-left: 4px solid {PRIMARY}; border-radius: 12px; padding: 16px 18px; box-shadow: {shadow}; margin-bottom: 10px; }}
.pdf-card-icon {{ font-size: 2rem; line-height: 1; flex-shrink: 0; margin-top: 2px; }}
.pdf-card-text {{ display: flex; flex-direction: column; align-items: flex-start; }}
.pdf-card-title {{ font-weight: 700; font-size: 0.95rem; color: {text}; text-decoration: none !important; transition: color 0.15s; }}
.pdf-card-title:hover {{ color: {PRIMARY}; text-decoration: underline !important; }}
.pdf-card-sub {{ font-size: 0.8rem; color: {text_muted}; margin-top: 4px; margin-bottom: 12px; }}
.pdf-badge {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.75rem; font-weight: 700; padding: 4px 10px; background-color: {"#374151" if dark else "#E5E7EB"}; color: {text} !important; border-radius: 6px; text-decoration: none !important; transition: background-color 0.15s; }}
.pdf-badge:hover {{ background-color: {"#4B5563" if dark else "#D1D5DB"}; }}

/* ---- Panel section (pembungkus chart) ---- */
.panel-title {{ font-size: 1.02rem; font-weight: 700; color: {text}; margin-bottom: 2px; }}
.panel-sub {{ font-size: 0.8rem; color: {text_muted}; margin-bottom: 10px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 12px !important; border-color: {border} !important; background-color: {surface} !important; box-shadow: {shadow}; }}

/* ---- Chip badge (mis. "Kecamatan: Panyipatan" yang aktif akibat drill-down) ---- */
.chip {{ display:inline-block; background-color: {surface}; border: 1.5px solid {PRIMARY}; color: {PRIMARY}; font-weight: 700; font-size: 0.85rem; padding: 6px 16px; border-radius: 999px; margin-bottom: 14px; }}

.donut-center {{ text-align:center; }}
.donut-center .dc-label {{ font-size: 0.8rem; color: {text_muted}; font-weight: 600; }}
.donut-center .dc-value {{ font-size: 1.5rem; font-weight: 800; color: {PRIMARY}; }}

/* ---- Kartu hero IPM (lebih besar dari metric-card biasa, sesuai desain) ---- */
.ipm-hero {{ background: linear-gradient(135deg, {"#3A3624" if dark else "#EFE7D0"} 0%, {"#2E2B1C" if dark else "#E8DFC0"} 100%); border-radius: 14px; padding: 20px 24px; box-shadow: {shadow}; }}
.ipm-hero-label {{ font-size: 0.85rem; font-weight: 700; color: {text_muted}; text-transform: uppercase; letter-spacing: 0.4px; }}
.ipm-hero-row {{ display: flex; align-items: baseline; gap: 12px; margin-top: 8px; }}
.ipm-hero-value {{ font-size: 2.4rem; font-weight: 900; color: {text}; }}
.ipm-hero-badge {{ font-size: 0.85rem; font-weight: 700; padding: 4px 10px; border-radius: 999px; background-color: {surface}; }}
.ipm-hero-sub {{ font-size: 0.78rem; color: {text_muted}; margin-top: 6px; }}

/* ---- Tabel kustom ---- */
.table-scroll {{ width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 8px; box-shadow: {shadow}; margin: 10px 0; }}
.custom-table {{ width: 100%; min-width: 480px; border-collapse: collapse; font-size: 0.88em; }}
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
.logo-img {{ width: 64px; height: 64px; object-fit: contain; background: #FFFFFF; border-radius: 50%; padding: 8px; box-shadow: 0 6px 16px rgba(30,64,175,0.2); display: block; margin: 0 auto; }}
.logo-caption {{ font-size: 0.86rem; font-weight: 700; color: {text}; margin-top: 8px; }}
.sidebar-caption {{ text-align:center; font-size:0.78rem; color:{text_muted}; margin-top:4px; }}

/* ---- Footer info sidebar (Informasi Selengkapnya) - rata tengah, 4 baris ---- */
.sidebar-footer {{ text-align: center; padding: 4px 6px 8px 6px; }}
.sidebar-footer-title {{ font-weight: 700; font-size: 0.85rem; color: {text}; margin-bottom: 6px; }}
.sidebar-footer-link {{ display: block; font-size: 0.8rem; color: {PRIMARY}; text-decoration: none !important; margin-bottom: 4px; }}
.sidebar-footer-link:hover {{ text-decoration: underline !important; }}
.sidebar-footer-text {{ font-size: 0.8rem; color: {text_muted}; margin-bottom: 4px; }}

a.sidebar-link {{ display:block; text-decoration:none !important; }}
a.sidebar-link:hover {{ color:{PRIMARY} !important; text-decoration:underline !important; }}
.nav-group-title {{ font-size: 0.75rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; color: {text_muted}; margin: 14px 0 4px 0; }}

/* ---- Sub-Kategori sebagai daftar tombol bertumpuk (bukan dropdown) - sesuai
   prototype: tombol aktif berwarna mauve/rose solid teks putih, tombol lain
   abu-abu muda. Disasar lewat parameter type="primary"/"secondary" pada
   st.button, yang di-render Streamlit dengan atribut kind="...". Dibungkus
   div dengan class "subnav" supaya tidak menimpa tombol lain di halaman
   (mis. tombol pagination / refresh). */
div[class*="st-key-subnav_"] .stButton > button {{
    width: 100%; text-align: left; border-radius: 8px !important; font-weight: 600;
    padding: 0.5rem 0.9rem !important; margin-bottom: 4px; border: none !important;
    box-shadow: none !important; justify-content: flex-start !important;
}}
div[class*="st-key-subnav_"] .stButton > button[kind="primary"] {{
    background-color: #B08998 !important; color: #FFFFFF !important;
}}
div[class*="st-key-subnav_"] .stButton > button[kind="secondary"] {{
    background-color: {"#374151" if dark else "#E5E7EB"} !important; color: {text} !important;
}}
div[class*="st-key-subnav_"] .stButton > button[kind="secondary"]:hover {{
    background-color: {"#4B5563" if dark else "#D1D5DB"} !important;
}}

/* ---- Tabel varian header berwarna (dipakai untuk tabel NTP / PDRB di
   halaman Pertanian & Pertumbuhan Ekonomi, sesuai skema warna prototype) ---- */
.table-scroll.tbl-yellow .custom-table thead tr {{ background-color: #F5C518; }}
.table-scroll.tbl-yellow .custom-table thead th {{ color: #1F2937 !important; }}
.table-scroll.tbl-yellow .custom-table tbody tr:nth-of-type(odd) {{ background-color: #B7E4C7; }}
.table-scroll.tbl-yellow .custom-table tbody tr:nth-of-type(even) {{ background-color: #D9F2E3; }}
.table-scroll.tbl-yellow .custom-table tbody tr:last-of-type {{ background-color: #F5C518; font-weight: 700; }}
/* Latar sel di atas SELALU pastel terang (fixed, tidak ikut tema) - jadi
   warna teksnya juga WAJIB dipaksa gelap terus-menerus, supaya di mode
   gelap teksnya tidak ikut jadi putih/abu-abu terang (tak terbaca di atas
   latar terang). !important perlu karena aturan umum "h1,h2,h3,h4,p,label,
   span" di atas sudah men-set warna teks ikut tema dengan spesifisitas tag. */
.table-scroll.tbl-yellow .custom-table tbody td {{ color: #1F2937 !important; }}

.pdrb-table {{ width: 100%; border-collapse: collapse; font-size: 0.88em; text-align: center; }}
.pdrb-table th, .pdrb-table td {{ padding: 9px 12px; border: 1px solid {border}; }}
.pdrb-table thead th.grp-tahun {{ background-color: #F5C518; color: #1F2937 !important; }}
.pdrb-table thead th.grp-nilai {{ background-color: #A9D6F5; color: #1F2937 !important; }}
.pdrb-table thead th.grp-perkap {{ background-color: #F5B8DA; color: #1F2937 !important; }}
.pdrb-table tbody td.col-tahun {{ background-color: #FBD1E7; color: #1F2937 !important; font-weight: 700; }}
.pdrb-table tbody td.col-nilai {{ background-color: #D6EBFB; color: #1F2937 !important; }}
.pdrb-table tbody td.col-perkap {{ background-color: {surface}; color: {text}; }}

/* ---- Heatmap gender (IPM) ---- */
.gender-heat-table {{ width: 100%; border-collapse: collapse; font-size: 0.86em; text-align: center; }}
.gender-heat-table th, .gender-heat-table td {{ padding: 10px 12px; border: 1px solid {border}; }}
.gender-heat-table thead th {{ background-color: {"#1F2937" if dark else "#F3F4F6"}; }}
.gender-heat-table tbody th {{ text-align: left; font-weight: 700; background-color: {"#1F2937" if dark else "#F3F4F6"}; }}

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
[data-testid="stMultiSelect"] [role="group"] {{ background-color: {surface} !important; border: 1px solid {border} !important; }}
[data-testid="stMultiSelect"] span[data-baseweb="tag"] {{ background-color: {PRIMARY} !important; }}
/* ---- Multiselect (mis. pilihan kelompok pengeluaran di "Track Record
   Inflasi"): BaseWeb secara default menaruh semua tag terpilih dalam SATU
   baris dengan tinggi & lebar tag TETAP, jadi label yang panjang terpotong
   di segala sisi (atas/bawah kepotong karena tinggi fixed, kiri/kanan
   kepotong karena text-overflow ellipsis + lebar tag dibatasi). Diperbaiki
   dua lapis: (1) label panjang sudah dipersingkat lewat format_func di
   Python sebelum sampai ke widget, (2) sebagai jaring pengaman, kotak
   pilihan & tag dipaksa wrap otomatis mengikuti tinggi kontennya sendiri
   (bukan tinggi/lebar tetap), supaya walau ada label yang masih panjang,
   tetap terbaca utuh alih-alih kepotong. ---- */
[data-testid="stMultiSelect"] div[data-baseweb="select"] {{ height: auto !important; }}
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{
    flex-wrap: wrap !important; height: auto !important; min-height: 44px !important;
    overflow: visible !important; padding: 6px 8px !important; align-items: center !important;
}}
[data-testid="stMultiSelect"] span[data-baseweb="tag"] {{
    height: auto !important; max-width: 100% !important; margin: 3px 4px 3px 0 !important;
    overflow: visible !important; padding: 4px 6px !important;
}}
[data-testid="stMultiSelect"] span[data-baseweb="tag"] span {{
    white-space: normal !important; overflow: visible !important; text-overflow: unset !important;
    word-break: break-word !important; line-height: 1.3 !important;
}}
[data-testid="stMultiSelect"] div:has(> input[role="combobox"]) {{
    color:transparent !important; opacity: 0 !important;
}}
/* ---- Notifikasi batas pilihan custom (pengganti pesan bawaan browser/
   BaseWeb "You can only select up to N options" yang berbahasa Inggris
   dan tidak stylable) - dipakai di halaman Track Record Inflasi. ---- */
.limit-notice {{ background-color: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.35); color: {text}; padding: 9px 14px; border-radius: 8px; font-size: 0.82rem; margin: 6px 0 4px 0; }}


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

/* ---- Responsif: tablet & mobile ----
   Ukuran font/padding di atas dirancang untuk layar desktop. Di layar sempit,
   header, kartu, dan panel perlu dipadatkan supaya proporsional dan tidak
   makan tempat berlebihan. Kolom (st.columns) sudah otomatis stack jadi
   1 kolom di Streamlit saat sempit - itu dibiarkan default (aman & fungsional),
   yang disesuaikan manual di sini cuma tipografi & spacing. */
/* Tablet (mis. iPad potret ~768-1024px): masih 2 kolom cukup lega, cuma
   padding & tipografi sedikit dipadatkan supaya tidak terlalu longgar. */
@media (max-width: 1024px) {{
    .block-container {{ padding-left: 1rem !important; padding-right: 1rem !important; }}
    .page-title {{ font-size: 1.85rem; }}
}}

@media (max-width: 768px) {{
    .block-container {{ padding-left: 0.7rem !important; padding-right: 0.7rem !important; }}
    .app-hero {{ padding: 16px 18px; border-radius: 12px; }}
    .app-hero .title {{ font-size: 1.2rem; }}
    .app-hero .subtitle {{ font-size: 0.8rem; }}
    .page-title {{ font-size: 1.55rem; }}
    .page-subtitle {{ font-size: 0.85rem; margin-bottom: 16px; }}
    .metric-card {{ height: auto; min-height: 96px; padding: 12px 14px; }}
    .metric-card .m-value {{ font-size: 1.35rem; }}
    .metric-card .m-label {{ font-size: 0.7rem; }}
    .metric-card-outline {{ min-height: 78px; padding: 12px 10px; margin-bottom: 10px; }}
    .metric-card-outline .mo-label {{ font-size: 0.72rem; }}
    .metric-card-outline .mo-value {{ font-size: 1.25rem; }}
    .panel-title {{ font-size: 0.95rem; }}
    .insight-box {{ padding: 12px 14px; }}
    .insight-text {{ font-size: 0.85rem; }}
    .custom-table {{ font-size: 0.82em; min-width: 420px; }}
    .custom-table th, .custom-table td {{ padding: 7px 10px; }}
    .pdrb-table, .gender-heat-table {{ font-size: 0.8em; min-width: 480px; }}
    .pdrb-table th, .pdrb-table td, .gender-heat-table th, .gender-heat-table td {{ padding: 6px 8px; }}
    .pdf-card {{ padding: 12px 14px; gap: 10px; }}
    .pdf-card-icon {{ font-size: 1.5rem; }}
    .pdf-card-title {{ font-size: 0.88rem; }}
    .pdf-card-sub {{ font-size: 0.75rem; }}
    /* Kartu/panel di dalam st.container(border=True) diberi jarak bawah
       sedikit lebih besar supaya tidak terasa berdempetan saat kolom-kolom
       ikut stack vertikal (perilaku default Streamlit di layar sempit). */
    [data-testid="stVerticalBlockBorderWrapper"] {{ margin-bottom: 10px; }}
    /* Sidebar tablet/phone-landscape: dipadatkan juga (default Streamlit
       ~336px terasa lebar di layar 480-768px), dengan bayangan drawer. */
    [data-testid="stSidebar"] {{ width: 62vw !important; min-width: 260px !important; max-width: 320px !important; box-shadow: 4px 0 24px rgba(0,0,0,0.2); }}
}}

@media (max-width: 480px) {{
    .app-hero .title {{ font-size: 1.05rem; }}
    .app-hero .breadcrumb {{ font-size: 0.72rem; }}
    .page-title {{ font-size: 1.35rem; }}
    .metric-card .m-value {{ font-size: 1.15rem; }}
    .metric-card-outline .mo-value {{ font-size: 1.1rem; }}
    .logo-badge, .logo-img {{ width: 52px; height: 52px; }}
    .logo-caption {{ font-size: 0.8rem; }}
    div[class*="st-key-subnav_"] .stButton > button {{ font-size: 0.85rem; padding: 0.45rem 0.7rem !important; }}
    /* Sidebar mobile: dibuat seperti drawer standar (bukan menutupi 3/4
       layar) - lebar dipadatkan ke ~70vw dengan batas atas 260px, ditambah
       bayangan supaya terasa "mengambang" di atas konten alih-alih ikut
       memakan ruang tata letak. */
    [data-testid="stSidebar"] {{ min-width: 220px !important; width: 70vw !important; max-width: 260px !important; box-shadow: 4px 0 24px rgba(0,0,0,0.25); }}
    [data-testid="stSidebar"] .block-container {{ padding-left: 0.9rem !important; padding-right: 0.9rem !important; }}
}}

/* ---- Pagination tabel: WAJIB selalu sejajar kiri-kanan, tidak boleh ikut
   stack ke bawah seperti kolom lain saat layar sempit. Disasar lewat
   st.container(key="pager_...") yang menghasilkan class stabil "st-key-pager_*"
   - jadi cuma baris pagination yang dipaksa row, kolom lain (chart, kartu)
   tetap boleh stack seperti biasa karena itu memang lebih baik untuk mereka. */
[class*="st-key-pager_"] div[data-testid="stHorizontalBlock"] {{
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 8px !important;
}}
[class*="st-key-pager_"] div[data-testid="column"] {{
    width: auto !important;
    min-width: 0 !important;
    flex: 0 0 auto !important;
}}
[class*="st-key-pager_"] div[data-testid="column"]:nth-of-type(2) {{
    flex: 1 1 auto !important;
    overflow: hidden;
}}
[class*="st-key-pager_"] .stButton > button {{ min-width: 42px !important; max-width: 56px !important; padding: 0.2rem 0 !important; }}
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
    # PENTING: nama sheet di-encode karena "Tenaga Kerja" mengandung spasi -
    # tanpa ini, request ke Google Sheets bisa gagal/salah parse URL.
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={quote(sheet_name)}"
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
    # "bahan_rilis" (URL Google Drive di sheet Inflasi_NTP) HARUS ikut masuk
    # text_cols - kalau tidak, clean_numeric() akan mengubahnya jadi NaN
    # karena isinya bukan angka, dan link dokumen rilis jadi hilang.
    text_cols = {"kecamatan", "sektor", "komoditas", "bulan", "tahun", "kabupaten", "bahan_rilis"}
    for col in df.columns:
        if col not in text_cols:
            df[col] = df[col].apply(clean_numeric)
    return df, None


def get_df(sheet_name: str) -> pd.DataFrame:
    df, err = fetch_data(sheet_name)
    if err:
        _html(f"<div class='data-error'>⚠️ {html.escape(err)}</div>")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_raw_csv(sheet_name: str):
    """Fetch CSV mentah TANPA asumsi skema standar (kolom 'tahun', dst) - dipakai
    untuk sheet berbentuk lain: Dist_PDRB (wide, tahun sebagai kolom),
    Komoditas/IHK Komoditas (2 baris header karena sel judul di-merge), dan
    Inflasi_COICOP22 (wide per kelompok pengeluaran)."""
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={quote(sheet_name)}"
    try:
        df = pd.read_csv(url, header=None)
        return df, None
    except Exception as e:
        return pd.DataFrame(), f"Gagal mengambil sheet '{sheet_name}': {e}"


@st.cache_data(ttl=3600, show_spinner=False)
def get_dist_pdrb() -> pd.DataFrame:
    """Sheet Dist_PDRB formatnya wide (kategori, sektor, lalu tahun jadi kolom
    2016..2025) - di-reshape ke long format (tahun jadi baris) supaya bisa
    difilter/di-drill-down seperti sheet lain."""
    raw, err = fetch_raw_csv("Dist_PDRB")
    if err or raw.empty:
        if err:
            _html(f"<div class='data-error'>⚠️ {html.escape(err)}</div>")
        return pd.DataFrame()
    raw.columns = raw.iloc[0]
    df = raw[1:].reset_index(drop=True)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "kategori" not in df.columns or "sektor" not in df.columns:
        _html("<div class='data-error'>⚠️ Sheet 'Dist_PDRB' kehilangan kolom 'kategori'/'sektor'.</div>")
        return pd.DataFrame()
    year_cols = [c for c in df.columns if c not in ("kategori", "sektor")]
    df_long = df.melt(id_vars=["kategori", "sektor"], value_vars=year_cols, var_name="tahun", value_name="pangsa")
    df_long["tahun"] = pd.to_numeric(df_long["tahun"], errors="coerce")
    df_long["pangsa"] = df_long["pangsa"].apply(clean_numeric)
    df_long = df_long.dropna(subset=["tahun"])
    df_long["tahun"] = df_long["tahun"].astype(int)
    df_long["kategori"] = df_long["kategori"].astype(str).str.strip().str.lower()
    df_long["sektor"] = df_long["sektor"].astype(str).str.strip()
    return df_long


@st.cache_data(ttl=3600, show_spinner=False)
def _get_komoditas_wide(sheet_name: str) -> pd.DataFrame:
    """Loader generik untuk sheet berformat 'wide per bulan' dengan 2 baris
    header (baris judul yang di-merge sepanjang kolom bulan + baris nama
    bulan sebenarnya) - dipakai untuk DUA sheet yang strukturnya identik:
    'Komoditas' (Andil Inflasi M-to-M per komoditas) dan 'IHK Komoditas'
    (IHK per komoditas). Baris header dicari OTOMATIS di antara 5 baris
    teratas (bukan hardcode ke iloc[1]) supaya tahan kalau sheet ke-geser
    barisnya saat diedit manual di Google Sheets, dan memunculkan pesan
    error yang jelas kalau header tetap tidak ketemu - bukan diam-diam gagal."""
    raw, err = fetch_raw_csv(sheet_name)
    if err or raw.empty or len(raw) < 3:
        if err:
            _html(f"<div class='data-error'>⚠️ {html.escape(err)}</div>")
        return pd.DataFrame()

    header_row_idx, best_match = None, 0
    for i in range(min(5, len(raw))):
        row_vals = [str(v).strip() for v in raw.iloc[i].tolist()]
        match_count = sum(1 for v in row_vals if v in BULAN_URUT)
        if match_count > best_match:
            best_match, header_row_idx = match_count, i

    if header_row_idx is None or best_match < 3:
        _html(
            f"<div class='data-error'>⚠️ Sheet '{html.escape(sheet_name)}': baris header nama "
            "bulan (Januari, Februari, dst) tidak terdeteksi di 5 baris "
            "teratas. Cek ulang struktur sheet - mungkin ada baris "
            "kosong/tambahan yang menggeser posisi header.</div>"
        )
        return pd.DataFrame()

    header_row = raw.iloc[header_row_idx].tolist()
    header_row[0] = "komoditas"
    df = raw[header_row_idx + 1:].reset_index(drop=True)
    df.columns = [str(h).strip() for h in header_row]
    for col in df.columns:
        if col != "komoditas":
            df[col] = df[col].apply(clean_numeric)
    df["komoditas"] = df["komoditas"].astype(str).str.strip()
    return df


def get_komoditas() -> pd.DataFrame:
    """Sheet 'Komoditas': Andil Inflasi M-to-M per komoditas, per bulan."""
    return _get_komoditas_wide("Komoditas")


def get_ihk_komoditas() -> pd.DataFrame:
    """Sheet 'IHK Komoditas': IHK per komoditas, per bulan - dipakai sebagai
    sumbu-X bubble chart Top 10 komoditas di halaman Inflasi (apple to apple
    dengan Andil M-to-M bulan berjalan di sumbu-Y, sama-sama data KOMODITAS
    per bulan, bukan angka gabungan kabupaten)."""
    return _get_komoditas_wide("IHK Komoditas")


@st.cache_data(ttl=3600, show_spinner=False)
def get_coicop() -> pd.DataFrame:
    """Sheet 'Inflasi_COICOP22': inflasi YoY per 11 kelompok pengeluaran
    (COICOP), Januari 2024 - Juli 2026 - dipakai di halaman "Track Record
    Inflasi".

    CATATAN PENTING: di sheet aslinya, header kolom pertama & kedua TERTUKAR -
    kolom bertajuk 'Tahun' sebenarnya isinya nama BULAN, dan kolom bertajuk
    'Bulan' sebenarnya isinya angka TAHUN (sudah dicek langsung ke data
    mentahnya, bukan salah baca). Fungsi ini mendeteksi kuirk itu otomatis
    (cek apakah isi kolom pertama adalah nama bulan) dan menormalkannya,
    supaya kode di halaman tidak perlu tahu soal kondisi sheet sumbernya."""
    raw, err = fetch_raw_csv("Inflasi_COICOP22")
    if err or raw.empty:
        if err:
            _html(f"<div class='data-error'>⚠️ {html.escape(err)}</div>")
        return pd.DataFrame()
    # Sheet punya banyak kolom kosong sisa export - dibatasi ke 13 kolom
    # bermakna saja (Tahun, Bulan, + 11 kelompok pengeluaran).
    raw = raw.iloc[:, :13]
    header = [str(h).strip() for h in raw.iloc[0].tolist()]
    df = raw[1:].reset_index(drop=True)
    df.columns = header
    df = df.dropna(subset=[df.columns[0]])
    if df.empty:
        return pd.DataFrame()
    first_col, second_col = df.columns[0], df.columns[1]
    sample_first = str(df[first_col].iloc[0]).strip()
    if sample_first in BULAN_URUT:
        df = df.rename(columns={first_col: "bulan", second_col: "tahun"})
    else:
        df = df.rename(columns={first_col: "tahun", second_col: "bulan"})
    df["tahun"] = pd.to_numeric(df["tahun"], errors="coerce")
    df = df.dropna(subset=["tahun"])
    df["tahun"] = df["tahun"].astype(int)
    df["bulan"] = df["bulan"].astype(str).str.strip()
    kategori_cols = [c for c in df.columns if c not in ("tahun", "bulan")]
    for c in kategori_cols:
        df[c] = df[c].apply(clean_numeric)
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


def extract_drive_file_id(url: str):
    """Ambil FILE_ID dari berbagai bentuk URL berbagi Google Drive, mis.
    'https://drive.google.com/file/d/FILE_ID/view?usp=drive_link' atau
    'https://drive.google.com/open?id=FILE_ID'. Dipakai untuk menyusun link
    unduh langsung (uc?export=download). None kalau polanya tidak dikenali -
    tombol unduh cadangan cukup disembunyikan, bukan bikin app error."""
    if not url:
        return None
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def apply_filter(df: pd.DataFrame, year_range):
    if df.empty or "tahun" not in df.columns:
        return df
    return df[(df["tahun"] >= year_range[0]) & (df["tahun"] <= year_range[1])]


# ==============================================================================
# 5. KOMPONEN UI
# ==============================================================================
def page_header(icon: str, title: str, breadcrumb: str, subtitle: str = ""):
    """Judul halaman gaya prototype: italic serif polos + subjudul kecil,
    TANPA kotak hero gradient/breadcrumb (prototype tidak punya elemen itu -
    lihat semua mockup: judul halaman langsung jadi teks hitam italic besar
    di pojok kiri atas area konten). Parameter icon & breadcrumb tetap
    diterima (dipakai di tempat lain / kompatibilitas) tapi tidak dirender."""
    sub_html = f"<div class='page-subtitle'>{html.escape(subtitle)}</div>" if subtitle else ""
    _html(
        "<div class='page-header-wrap'>",
        f"<p class='page-title'>{html.escape(title)}</p>",
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


def metric_card_outline(col, label: str, value: str, trend: str = None, trend_dir: str = "flat"):
    """Varian kartu KPI bergaya OUTLINE (border tipis, tanpa fill warna) -
    dipakai khusus di landing page 'Dashboard Utama', sesuai prototype
    (Image 8: 7 kotak KPI dengan border oranye/emas tipis)."""
    trend_html = ""
    if trend:
        cls = {"up": "m-up", "down": "m-down", "flat": "m-flat"}.get(trend_dir, "m-flat")
        arrow = {"up": "▲", "down": "▼", "flat": "▬"}.get(trend_dir, "▬")
        trend_html = f"<div class='mo-trend {cls}'>{arrow} {html.escape(trend)}</div>"
    with col:
        _html(
            "<div class='metric-card-outline'>",
            f"<div class='mo-label'>{html.escape(label)}</div>",
            f"<div class='mo-value'>{html.escape(value)}</div>",
            trend_html,
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


def render_custom_table(df: pd.DataFrame, key: str = "tbl", page_size: int = 10, variant: str = ""):
    """variant: "" (default) atau "yellow" (header kuning + baris hijau
    selang-seling, dipakai untuk tabel NTP di halaman Pertanian sesuai
    skema warna prototype)."""
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

    variant_cls = f" tbl-{variant}" if variant else ""
    _html(f"<div class='table-scroll{variant_cls}'><table class='custom-table'><thead><tr>{thead}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")

    if total_pages > 1:
        with st.container(key=f"pager_{key}"):
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


def render_pdrb_table(df: pd.DataFrame):
    """Tabel PDRB dengan header 2 tingkat (Tahun / Nilai PDRB [ADHB, ADHK] /
    Pendapatan per Kapita [ADHB, ADHK]) dan skema warna kuning-biru-pink
    sesuai prototype (Image 2). df harus sudah berkolom:
    Tahun, PDRB ADHB, PDRB ADHK, Pendapatan ADHB, Pendapatan ADHK."""
    rows_html = []
    for _, r in df.iterrows():
        rows_html.append(
            "<tr>"
            f"<td class='col-tahun'>{html.escape(str(int(r['Tahun'])))}</td>"
            f"<td class='col-nilai'>{html.escape(fmt_id(r['PDRB ADHB']))}</td>"
            f"<td class='col-nilai'>{html.escape(fmt_id(r['PDRB ADHK']))}</td>"
            f"<td class='col-perkap'>{html.escape(fmt_id(r['Pendapatan ADHB']))}</td>"
            f"<td class='col-perkap'>{html.escape(fmt_id(r['Pendapatan ADHK']))}</td>"
            "</tr>"
        )
    table_html = (
        "<div class='table-scroll'><table class='pdrb-table'><thead>"
        "<tr>"
        "<th class='grp-tahun' rowspan='2'>Tahun</th>"
        "<th class='grp-nilai' colspan='2'>Nilai PDRB (Milyar Rp)</th>"
        "<th class='grp-perkap' colspan='2'>Pendapatan per Kapita (Ribu Rp)</th>"
        "</tr>"
        "<tr><th class='grp-nilai'>ADHB</th><th class='grp-nilai'>ADHK 2010</th>"
        "<th class='grp-perkap'>ADHB</th><th class='grp-perkap'>ADHK 2010</th></tr>"
        f"</thead><tbody>{''.join(rows_html)}</tbody></table></div>"
    )
    _html(table_html)


def render_gender_heatmap(years: list, ipg: list, idg: list, ikg: list):
    """Tabel heatmap Indeks-Indeks Gender (baris: IPG/IDG/IKG, kolom: tahun) -
    warna sel dari terang ke gelap sesuai proporsi nilai per baris, sesuai
    prototype (Image 4)."""
    def _row(label, values, low_is_good=False):
        valid = [v for v in values if pd.notna(v)]
        vmin, vmax = (min(valid), max(valid)) if valid else (0, 1)
        rng = (vmax - vmin) or 1
        cells = f"<th>{html.escape(label)}</th>"
        for v in values:
            if pd.isna(v):
                cells += "<td>-</td>"
                continue
            frac = (v - vmin) / rng
            if low_is_good:
                frac = 1 - frac
            alpha = 0.15 + 0.65 * frac
            txt_color = "#FFFFFF" if frac > 0.6 else "inherit"
            cells += f"<td style='background-color: rgba(79,134,198,{alpha:.2f}); color:{txt_color};'>{fmt_id(v, 2 if label != 'IKG' else 3)}</td>"
        return f"<tr>{cells}</tr>"

    thead = "<th></th>" + "".join(f"<th>{int(y)}</th>" for y in years)
    body = _row("IPG", ipg) + _row("IDG", idg) + _row("IKG", ikg, low_is_good=True)
    _html(f"<div class='table-scroll'><table class='gender-heat-table'><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table></div>")


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


def mini_trend_panel(col, title: str, years: list, values: list, color: str, decimals: int = 2, suffix: str = ""):
    """Panel tren mini dengan titik terakhir dibesarkan - dipakai untuk P0/P1/P2
    (Kemiskinan) dan IPG/IDG/IKG (IPM). Sengaja dipisah per-indikator (bukan
    1 heatmap gabungan) karena skala nilainya beda jauh antar indikator
    (mis. IKG 0-1 vs IPG/IDG 60-90) - digabung dalam 1 skala warna malah
    menyesatkan."""
    with col:
        with st.container(border=True):
            panel_title(title)
            pairs = [(y, v) for y, v in zip(years, values) if pd.notna(v)]
            if not pairs:
                st.caption("Data tidak tersedia.")
                return
            years_clean = [str(int(y)) for y, _ in pairs]
            vals_clean = [round(float(v), decimals) for _, v in pairs]
            last_val = vals_clean[-1]
            opts = {
                "backgroundColor": "transparent",
                "grid": {"top": "8%", "bottom": "16%", "left": "6%", "right": "6%"},
                "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                "xAxis": {"type": "category", "data": years_clean, "axisLabel": {"fontSize": 10}, "axisLine": {"show": False}, "axisTick": {"show": False}},
                "yAxis": {"type": "value", "show": False},
                "series": [{
                    "name": "", "type": "line", "data": vals_clean, "smooth": True, "symbolSize": 6,
                    "itemStyle": {"color": color}, "lineStyle": {"color": color, "width": 2},
                    "markPoint": {"symbol": "circle", "symbolSize": 22, "data": [{"coord": [len(vals_clean) - 1, last_val], "itemStyle": {"color": color}}], "label": {"show": False}},
                }],
            }
            st_echarts(options=opts, height="150px", theme=e_theme)
            _html(f"<div style='text-align:center; font-size:1.3rem; font-weight:800; color:{color};'>{fmt_id(last_val, decimals)}{suffix}</div>")


def sparkline_kpi_card(col, title: str, value_text: str, delta_text: str, delta_dir: str, spark_labels: list, spark_values: list, color: str, chart_type: str = "line"):
    """Kartu KPI kecil dengan angka besar + badge delta + grafik mini di
    bawahnya - dipakai untuk kartu IHK/Inflasi (halaman Inflasi) dan
    UHH/HLS/RLS/Pengeluaran (halaman IPM)."""
    with col:
        with st.container(border=True):
            panel_title(title)
            trend_html = ""
            if delta_text:
                cls = {"up": "m-up", "down": "m-down", "flat": "m-flat"}.get(delta_dir, "m-flat")
                arrow = {"up": "▲", "down": "▼", "flat": "▬"}.get(delta_dir, "▬")
                trend_html = f"<div class='m-trend {cls}'>{arrow} {html.escape(delta_text)}</div>"
            _html(f"<div class='m-value'>{html.escape(value_text)}</div>{trend_html}")
            valid = [(l, v) for l, v in zip(spark_labels, spark_values) if pd.notna(v)]
            if valid:
                labels_clean = [str(l) for l, _ in valid]
                vals_clean = [round(float(v), 4) for _, v in valid]
                series_def = {"name": "", "type": chart_type, "data": vals_clean, "itemStyle": {"color": color}, "symbolSize": 0}
                if chart_type == "line":
                    series_def["smooth"] = True
                    series_def["lineStyle"] = {"color": color, "width": 2}
                    series_def["areaStyle"] = {"opacity": 0.15}
                else:
                    series_def["barWidth"] = "60%"
                opts = {
                    "backgroundColor": "transparent",
                    "grid": {"top": "8%", "bottom": "2%", "left": "2%", "right": "2%"},
                    "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                    "xAxis": {"type": "category", "data": labels_clean, "show": False},
                    "yAxis": {"type": "value", "show": False, "scale": True},
                    "series": [series_def],
                }
                st_echarts(options=opts, height="70px", theme=e_theme)


def sub_nav(options: list, state_key: str) -> str:
    """Daftar tombol Sub-Kategori bertumpuk (bukan dropdown) - sesuai
    prototype: opsi aktif berwarna mauve solid, opsi lain abu-abu muda.
    state_key HARUS unik per grup (mis. 'subnav_demografi', 'subnav_ekonomi')
    supaya pilihan tiap kategori tidak saling menimpa saat user pindah
    kategori di sidebar."""
    if state_key not in st.session_state or st.session_state[state_key] not in options:
        st.session_state[state_key] = options[0]
    with st.container(key=state_key):
        for opt in options:
            is_active = st.session_state[state_key] == opt
            if st.button(opt, key=f"{state_key}_btn_{opt}", use_container_width=True,
                         type="primary" if is_active else "secondary"):
                if not is_active:
                    st.session_state[state_key] = opt
                    st.rerun()
    return st.session_state[state_key]


def ipm_hero_card(tahun: int, value: float, prev_value: float, prev_tahun: int):
    """Kartu KPI besar khusus IPM (beda gaya dari metric_card biasa - lebih
    besar, dengan badge delta di atas angka), sesuai desain prototype."""
    delta = value - prev_value if pd.notna(value) and pd.notna(prev_value) else None
    direction = "flat"
    if delta is not None:
        direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
    cls = {"up": "m-up", "down": "m-down", "flat": "m-flat"}.get(direction, "m-flat")
    arrow = {"up": "▲", "down": "▼", "flat": "▬"}.get(direction, "▬")
    badge = f"<span class='ipm-hero-badge {cls}'>{arrow} {abs(delta):.2f}</span>" if delta is not None else ""
    _html(
        "<div class='ipm-hero'>",
        f"<div class='ipm-hero-label'>IPM {int(tahun)}</div>",
        f"<div class='ipm-hero-row'>{badge}<span class='ipm-hero-value'>{fmt_id(value, 2)}</span></div>",
        f"<div class='ipm-hero-sub'>dibandingkan {int(prev_tahun)}</div>" if pd.notna(prev_tahun) else "",
        "</div>",
    )


# ==============================================================================
# 6. SIDEBAR
# ==============================================================================
filter_kec = None
with st.sidebar:
    logo_b64 = load_logo_base64()
    if logo_b64:
        _html(
            "<div class='sidebar-brand'>",
            f"<img class='logo-img' src='data:image/png;base64,{logo_b64}'>",
            "<div class='logo-caption'>TALA.ID</div>",
            "<a class='sidebar-caption sidebar-link' href='https://tanahlautkab.bps.go.id' target='_blank' rel='noopener noreferrer'>tanahlautkab.bps.go.id</a>",
            "</div>",
        )
    else:
        _html(
            "<div class='sidebar-brand'>",
            "<div class='logo-badge'>BPS</div>",
            "<div class='logo-caption'>TALA.ID</div>",
            "<a class='sidebar-caption sidebar-link' href='https://tanahlautkab.bps.go.id' target='_blank' rel='noopener noreferrer'>tanahlautkab.bps.go.id</a>",
            "</div>",
        )

    tema_gelap = st.toggle("🌙 Mode Gelap", value=False)
    e_theme = "dark" if tema_gelap else "light"

    st.markdown("---")
    _html("<div class='nav-group-title'>Navigasi</div>")
    kategori = st.selectbox(
        "Kategori", ["Dashboard Utama", "Demografi & Sosial", "Ekonomi", "Pertanian"],
        label_visibility="collapsed",
    )

    sub_kategori = None
    if kategori == "Demografi & Sosial":
        _html("<div class='nav-group-title'>Sub-Kategori</div>")
        sub_kategori = sub_nav(["Kependudukan", "Tenaga Kerja", "Kemiskinan", "IPM"], "subnav_demografi")
    elif kategori == "Ekonomi":
        _html("<div class='nav-group-title'>Sub-Kategori</div>")
        sub_kategori = sub_nav(["Inflasi", "Track Record Inflasi", "Pertumbuhan Ekonomi"], "subnav_ekonomi")
    # Pertanian: sengaja tanpa sub-kategori (1 halaman saja) sesuai prototype desain

    # Halaman Inflasi butuh filter BERBEDA dari halaman lain: data pendukungnya
    # (Harga mingguan, Komoditas) cuma ada untuk tahun 2026 dan granularitasnya
    # bulanan/mingguan - filter rentang TAHUN tidak relevan di sana, makanya
    # diganti slider rentang BULAN khusus untuk halaman ini.
    #
    # Dashboard Utama & Track Record Inflasi TIDAK punya filter rentang waktu
    # sama sekali di sidebar: Dashboard Utama memang selalu menampilkan data
    # TERBARU (bukan yang difilter), dan Track Record Inflasi selalu
    # menampilkan rentang tetap Januari 2024 - Juli 2026 sesuai definisinya.
    bulan_range = None
    if sub_kategori == "Inflasi":
        _html("<div class='nav-group-title'>Rentang Bulan (2026)</div>")
        df_inf_bounds, err_inf_bounds = fetch_data("Inflasi_NTP")
        if err_inf_bounds or df_inf_bounds.empty:
            bulan_list = BULAN_URUT[:7]
            st.caption(f"⚠️ Rentang bulan pakai default: {err_inf_bounds or 'data kosong'}")
        else:
            df_2026 = df_inf_bounds[(df_inf_bounds["tahun"] == 2026) & (df_inf_bounds["ihk"].notna())]
            bulan_list = [b for b in BULAN_URUT if b in df_2026["bulan"].tolist()]
            if not bulan_list:
                bulan_list = BULAN_URUT[:7]
        if len(bulan_list) == 1:
            bulan_range = (bulan_list[0], bulan_list[0])
            st.caption(f"Data baru tersedia untuk {bulan_list[0]} 2026.")
        else:
            bulan_range = st.select_slider("Rentang Bulan", options=bulan_list, value=(bulan_list[0], bulan_list[-1]), label_visibility="collapsed")
        # f_tahun tetap diisi (fallback penuh) supaya variabel selalu ada walau tidak dipakai halaman ini
        f_tahun = (2016, datetime.datetime.now().year)
    elif kategori == "Dashboard Utama" or sub_kategori == "Track Record Inflasi":
        # Tidak ada widget filter yang ditampilkan - kedua halaman ini punya
        # rentang data yang sudah pasti/otomatis (selalu data terbaru / selalu
        # Jan 2024-Jul 2026), jadi slider tahun di sini cuma membingungkan
        # karena tidak benar-benar mengubah apa pun di halamannya.
        f_tahun = (2016, datetime.datetime.now().year)
    else:
        _html("<div class='nav-group-title'>Rentang Waktu</div>")
        df_bounds, err_bounds = fetch_data("Kependudukan")
        if err_bounds or df_bounds.empty:
            min_year, curr_year = 2016, datetime.datetime.now().year
            st.caption(f"⚠️ Rentang tahun pakai default ({min_year}-{curr_year}): {err_bounds or 'data kosong'}")
        else:
            min_year = int(df_bounds["tahun"].min())
            # Batas atas diambil yang PALING BESAR antara data Kependudukan vs tahun
            # berjalan saat ini - soalnya sheet lain (mis. Inflasi_NTP) sering lebih
            # up-to-date (bulanan) dan bisa lebih baru dari data kependudukan
            # (biasanya proyeksi tahunan yang telat rilis). Kalau batas cuma ikut
            # Kependudukan, data terbaru di sheet lain bisa ke-filter hilang tanpa disadari.
            curr_year = max(int(df_bounds["tahun"].max()), datetime.datetime.now().year)
        f_tahun = st.slider("Rentang Tahun", min_year, curr_year, (min_year, curr_year), label_visibility="collapsed")

    # Kependudukan butuh df_bounds untuk daftar kecamatan di bawah - pastikan selalu terisi
    if sub_kategori in ("Inflasi", "Track Record Inflasi") or kategori == "Dashboard Utama":
        df_bounds, _ = fetch_data("Kependudukan")

    # Filter wilayah (kecamatan) HANYA relevan untuk halaman Kependudukan -
    # sheet lain tidak punya breakdown per kecamatan, jadi tidak ditampilkan
    # di halaman lain (mengikuti prototype desain).
    if sub_kategori == "Kependudukan":
        _html("<div class='nav-group-title'>Wilayah</div>")
        if not df_bounds.empty and "kecamatan" in df_bounds.columns:
            list_kecamatan = ["Seluruh Kecamatan"] + sorted(
                [k for k in df_bounds["kecamatan"].dropna().unique() if str(k).lower() != "tanah laut"]
            )
        else:
            list_kecamatan = ["Seluruh Kecamatan"]
        if "kepen_wilayah" not in st.session_state:
            st.session_state["kepen_wilayah"] = "Seluruh Kecamatan"
        if st.session_state["kepen_wilayah"] not in list_kecamatan:
            st.session_state["kepen_wilayah"] = "Seluruh Kecamatan"
        filter_kec = st.selectbox("Kecamatan", list_kecamatan, key="kepen_wilayah")

    with st.expander("ℹ️ Kamus Istilah"):
        st.caption(
            "**TPT** — Tingkat Pengangguran Terbuka: persentase penduduk usia kerja yang menganggur.\n\n"
            "**TPAK** — Tingkat Partisipasi Angkatan Kerja: persentase penduduk usia kerja yang aktif "
            "secara ekonomi (bekerja atau sedang mencari kerja).\n\n"
            "**P0 / P1 / P2** — P0: persentase penduduk miskin. P1: kedalaman kemiskinan (seberapa jauh "
            "pengeluaran penduduk miskin dari garis kemiskinan). P2: keparahan kemiskinan (ketimpangan di "
            "antara penduduk miskin).\n\n"
            "**Rasio Gini** — ukuran ketimpangan pengeluaran; 0 = merata sempurna, 1 = timpang sempurna.\n\n"
            "**IPM** — Indeks Pembangunan Manusia: gabungan dimensi kesehatan, pendidikan, dan standar hidup layak.\n\n"
            "**UHH / HLS / RLS** — UHH: Usia Harapan Hidup. HLS: Harapan Lama Sekolah. RLS: Rata-rata Lama Sekolah.\n\n"
            "**Pengeluaran/Kapita** — Pengeluaran Per Kapita Disesuaikan (ribu rupiah per orang per tahun).\n\n"
            "**IPG / IDG / IKG** — Indeks Pembangunan Gender, Indeks Pemberdayaan Gender, Indeks Ketimpangan Gender.\n\n"
            "**NTP** — Nilai Tukar Petani: rasio harga jual hasil pertanian terhadap harga barang yang "
            "dibeli petani. NTP > 100 berarti petani diuntungkan.\n\n"
            "**Rasio Ketergantungan** — perbandingan penduduk usia nonproduktif terhadap usia produktif.\n\n"
            "**COICOP** — Classification of Individual Consumption according to Purpose: klasifikasi "
            "kelompok pengeluaran standar yang dipakai BPS untuk menghitung inflasi per kelompok."
        )

    st.markdown("---")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    _html(f"<div class='sidebar-caption'>Sinkron terakhir: {(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))).strftime('%d %b %Y, %H:%M')} WITA</div>")

    st.markdown("---")
    _html(
        "<div class='sidebar-footer'>",
        "<div class='sidebar-footer-title'>Informasi Selengkapnya</div>",
        "<a class='sidebar-footer-link' href='https://forms.gle/EuhfVVdZ2toVCiX46' target='_blank' rel='noopener noreferrer'>Formulir Kritik dan Saran</a>",
        "<a class='sidebar-footer-link' href='https://wa.me/6281388886301' target='_blank' rel='noopener noreferrer'>+62 813-8888-6301 (WA)</a>"
        "<a class='sidebar-footer-link' href='https://instagram.com/bps_tanahlaut' target='_blank' rel='noopener noreferrer'>@bps_tanahlaut (Instagram)</a>",
        "</div>",
    )

inject_css(tema_gelap)
breadcrumb_path = f"{BREADCRUMB_ICON.get(kategori, '📁')} {kategori}" + (f"  ›  {sub_kategori}" if sub_kategori else "")

# ==============================================================================
# 7. ROUTER HALAMAN
# ==============================================================================
if kategori == "Dashboard Utama":
    page_header("🏠", "OVERVIEW", breadcrumb_path, "Profil Makroekonomi dan Demografi Kabupaten Tanah Laut")
    with section_guard("Overview"):
        df_kep = get_df("Kependudukan")
        df_tk = get_df("Tenaga Kerja")
        df_ki = get_df("Kemiskinan_IPM")
        df_inf = get_df("Inflasi_NTP")
        df_pdrb = get_df("PDRB")
        df_pt = get_df("Pertanian")

        if any(d.empty for d in [df_kep, df_tk, df_ki, df_inf, df_pdrb, df_pt]):
            st.warning("Sebagian data belum lengkap untuk menampilkan overview.")
        else:
            t_max = int(df_kep["tahun"].max())
            row_kep_series = df_kep[(df_kep["tahun"] == t_max) & (df_kep["kecamatan"].str.lower() == "tanah laut")]
            row_kep = row_kep_series.iloc[0] if not row_kep_series.empty else None
            row_tk = df_tk.sort_values("tahun").iloc[-1] if not df_tk.empty else None
            row_ki = df_ki.sort_values("tahun").iloc[-1] if not df_ki.empty else None
            row_pdrb = df_pdrb.sort_values("tahun").iloc[-1] if not df_pdrb.empty else None
            df_inf_sorted = df_inf.copy()
            df_inf_sorted["bulan_idx"] = df_inf_sorted["bulan"].apply(lambda b: BULAN_URUT.index(b) if b in BULAN_URUT else -1)
            df_inf_sorted = df_inf_sorted.sort_values(["tahun", "bulan_idx"])
            row_inf = df_inf_sorted.iloc[-1] if not df_inf_sorted.empty else None
            df_padi = df_pt[df_pt["komoditas"].str.lower() == "padi"].sort_values("tahun")
            row_padi = df_padi.iloc[-1] if not df_padi.empty else None

            with st.container(border=True):
                panel_title("🗺️ Peta Wilayah Kabupaten Tanah Laut", "Arahkan kursor ke setiap kecamatan untuk melihat jumlah penduduk")
                geo_data = load_geojson()
                df_map = df_kep[(df_kep["tahun"] == t_max) & (df_kep["kecamatan"].str.lower() != "tanah laut")]
                if geo_data and not df_map.empty:
                    map_data = [{"name": r["kecamatan"], "value": r["jumlah_penduduk"], "pddk": r["jumlah_penduduk"]} for _, r in df_map.iterrows()]

                    # Hitung nilai minimum dan maksimum jumlah penduduk untuk skala gradasi
                    pddk_vals = [d["value"] for d in map_data if pd.notna(d["value"])]
                    vmin = min(pddk_vals) if pddk_vals else 0
                    vmax = max(pddk_vals) if pddk_vals else 100000

                    # Penyesuaian batas wilayah & gradasi warna (Terang -> Gelap)
                    map_border = "#94A3B8" if tema_gelap else "#64748B"
                    # Warna gradasi: Terang (penduduk sedikit) ke Gelap (penduduk banyak)
                    gradasi_warna = ["#E8DFCA", "#CFAB8D", "#B87C4C"] if tema_gelap else ["#FACE68", "#FAAC68", "#6F8F72", "#4E8D9C"]

                    map_opts = {
                        "backgroundColor": "transparent",
                        "tooltip": {
                            "trigger": "item",
                            "confine": True,
                            "formatter": JsCode(
                                "function(p){if(!p.data)return '<b>'+p.name+'</b><br/>Data tidak tersedia';"
                                "return '<b>'+p.name+'</b><br/>Jumlah Penduduk: <b>'+Number(p.data.pddk).toLocaleString('id-ID')+' jiwa</b>';}"
                            )
                        },
                        # Komponen penanggung jawab gradasi warna (Choropleth Visual Map)
                        "visualMap": {
                            "show": True,
                            "min": vmin,
                            "max": vmax,
                            "left": "left",
                            "bottom": "0%",
                            "inRange": {"color": gradasi_warna},
                            "textStyle": {"color": "#9CA3AF" if tema_gelap else "#4B5563"},
                            "formatter": JsCode("function(value){ return Number(value).toLocaleString('id-ID'); }"),
                            "itemWidth": 12,
                            "itemHeight": 90
                        },
                        "series": [{
                            "type": "map",
                            "map": "TALA",
                            "roam": False,
                            "label": {"show": False},
                            # Hapus areaColor di itemStyle agar diatur penuh oleh visualMap
                            "itemStyle": {"borderColor": map_border, "borderWidth": 1.5},
                            "emphasis": {
                                "label": {"show": True},
                                "itemStyle": {"areaColor": ACCENT, "borderColor": map_border, "borderWidth": 1.5}
                            },
                            "data": map_data,
                        }],
                    }
                    st_echarts(options=map_opts, map=Map("TALA", geo_data), height="480px", theme=e_theme)
                else:
                    st.info("🗺️ Sistem spasial siap. Letakkan berkas `tanah_laut.geojson` sejajar dengan script.")

            st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
            panel_title("📌 Indikator Kunci")

            # 1. Ambil tahun/bulan dari data masing-masing indikator
            th_kep = f" {int(row_kep['tahun'])}" if row_kep is not None and pd.notna(row_kep.get("tahun")) else ""
            th_tk = f" {int(row_tk['tahun'])}" if row_tk is not None and pd.notna(row_tk.get("tahun")) else ""
            th_ki = f" {int(row_ki['tahun'])}" if row_ki is not None and pd.notna(row_ki.get("tahun")) else ""
            th_pdrb = f" {int(row_pdrb['tahun'])}" if row_pdrb is not None and pd.notna(row_pdrb.get("tahun")) else ""
            th_padi = f" {int(row_padi['tahun'])}" if row_padi is not None and pd.notna(row_padi.get("tahun")) else ""

            # Khusus Inflasi: Ambil Bulan & Tahun (contoh: "Juli 2026")
            bln_inf = f" {row_inf['bulan']} {int(row_inf['tahun'])}" if row_inf is not None and pd.notna(row_inf.get("bulan")) else ""

            # 2. Baris Pertama KPI (4 Kolom)
            r1 = st.columns(4)
            metric_card_outline(r1[0], f"Jumlah Penduduk{th_kep}", fmt_id(row_kep["jumlah_penduduk"]) if row_kep is not None else "-")
            metric_card_outline(r1[1], f"Tingkat Pengangguran Terbuka{th_tk}", f"{fmt_id(row_tk['tpt'], decimals=2)}%" if row_tk is not None and pd.notna(row_tk["tpt"]) else "-")
            metric_card_outline(r1[2], f"Persentase Penduduk Miskin{th_ki}", f"{fmt_id(row_ki['p0'], decimals=2)}%" if row_ki is not None and pd.notna(row_ki["p0"]) else "-")
            metric_card_outline(r1[3], f"Indeks Pembangunan Manusia{th_ki}", fmt_id(row_ki["ipm"], 2) if row_ki is not None and pd.notna(row_ki["ipm"]) else "-")

            st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

            # 3. Baris Kedua KPI (3 Kolom)
            r2 = st.columns(3)
            metric_card_outline(r2[0], f"Inflasi (y-on-y){bln_inf}", f"{fmt_id(row_inf['inflasi_yoy'], decimals=2)}%" if row_inf is not None and pd.notna(row_inf["inflasi_yoy"]) else "-")
            metric_card_outline(r2[1], f"Pertumbuhan Ekonomi{th_pdrb}", f"{fmt_id(row_pdrb['pert_eko'], decimals=2)}%" if row_pdrb is not None and pd.notna(row_pdrb["pert_eko"]) else "-")
            metric_card_outline(r2[2], f"Luas Panen Padi{th_padi}", f"{fmt_id(row_padi['luas_panen'])} Ha" if row_padi is not None else "-")

elif sub_kategori == "Kependudukan":
    page_header("👥", "Kependudukan", breadcrumb_path)
    with section_guard("Kependudukan"):
        df_d = apply_filter(get_df("Kependudukan"), f_tahun)
        if df_d.empty:
            st.warning("Data kependudukan tidak tersedia untuk rentang ini.")
        else:
            target_kec = "tanah laut" if filter_kec in (None, "Seluruh Kecamatan") else filter_kec.lower()
            label_wilayah = "Seluruh Kecamatan" if target_kec == "tanah laut" else filter_kec
            _html(f"<div class='chip'>📍 {html.escape(label_wilayah)}</div>")

            df_target = df_d[df_d["kecamatan"].str.lower() == target_kec].sort_values("tahun")
            if df_target.empty:
                st.warning(f"Tidak ada data untuk wilayah '{filter_kec}'.")
            else:
                years_k = df_target["tahun"].astype(int).tolist()
                c_chart, c_insight = st.columns([1.7, 1])
                with c_chart:
                    with st.container(border=True):
                        panel_title("Jumlah dan Pertumbuhan Penduduk", "Klik titik tahun untuk melihat kepadatan & rasio JK tahun tersebut")
                        kep_opts = {
                            "backgroundColor": "transparent",
                            "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                            "legend": {"bottom": 0},
                            "xAxis": {"type": "category", "data": [str(y) for y in years_k]},
                            "yAxis": [{"type": "value", "name": "Jiwa"}, {"type": "value", "name": "%", "splitLine": {"show": False}}],
                            "series": [
                                {"name": "Jumlah Penduduk", "type": "line", "data": df_target["jumlah_penduduk"].tolist(), "smooth": True, "areaStyle": {"opacity": 0.15}, "itemStyle": {"color": COLORS[0]}, "lineStyle": {"width": 3}, "symbolSize": 8},
                                {"name": "Pertumbuhan Penduduk", "type": "line", "yAxisIndex": 1, "data": df_target["pertumbuhan"].round(2).tolist(), "smooth": True, "itemStyle": {"color": COLORS[1]}, "lineStyle": {"width": 2}},
                            ],
                        }
                        kep_click = st_echarts(options=kep_opts, height="380px", key="kep_line", theme=e_theme, on_select="rerun", selection_mode="points")

                if "kepen_tahun_aktif" not in st.session_state or st.session_state["kepen_tahun_aktif"] not in years_k:
                    st.session_state["kepen_tahun_aktif"] = years_k[-1]
                if kep_click and "selection" in kep_click and kep_click["selection"].get("point_indices"):
                    idx = kep_click["selection"]["point_indices"][0]
                    if idx < len(years_k):
                        st.session_state["kepen_tahun_aktif"] = years_k[idx]
                t_aktif_k = st.session_state["kepen_tahun_aktif"]

                row_series = df_target[df_target["tahun"] == t_aktif_k]
                row_target = row_series.iloc[0] if not row_series.empty else df_target.iloc[-1]
                prev_series = df_target[df_target["tahun"] < t_aktif_k]
                pddk_now, dir_now = trend_info(row_target["jumlah_penduduk"], prev_series["jumlah_penduduk"].iloc[-1] if not prev_series.empty else None)

                with c_insight:
                    if pddk_now:
                        insight_box("Interpretasi", f"Populasi {label_wilayah} pada {int(t_aktif_k)} {'naik' if dir_now == 'up' else 'turun'} {pddk_now}.")

                c_map, c_gender, c_rasio = st.columns([1.1, 1.2, 0.8])
                map_click = None
                map_data = []
                with c_map:
                    with st.container(border=True):
                        panel_title(f"Kepadatan Penduduk {int(t_aktif_k)}", "Klik kecamatan untuk filter seluruh halaman")
                        geo_data = load_geojson()
                        df_map_year = df_d[(df_d["tahun"] == t_aktif_k) & (df_d["kecamatan"].str.lower() != "tanah laut")]
                        if geo_data and not df_map_year.empty:
                            map_data = [{"name": r["kecamatan"], "value": r["kepadatan"], "pddk": r["jumlah_penduduk"]} for _, r in df_map_year.iterrows() if pd.notna(r["kepadatan"])]
                            if map_data:
                                vmin = min(d["value"] for d in map_data)
                                vmax = max(d["value"] for d in map_data)
                                map_border_dens = "#1F2937" if tema_gelap else "#6B5B45"
                                map_opts = {
                                    "backgroundColor": "transparent",
                                    "tooltip": {"trigger": "item", "confine": True, "formatter": JsCode(
                                        "function(p){if(!p.data)return '<b>'+p.name+'</b><br/>Data tidak tersedia';"
                                        "return '<b>'+p.name+'</b><br/>Kepadatan: <b>'+Number(p.value).toLocaleString('id-ID')+' jiwa/km\u00b2</b><br/>Penduduk: <b>'+Number(p.data.pddk).toLocaleString('id-ID')+' jiwa</b>';}"
                                    )},
                                    "visualMap": {"show": True, "min": vmin, "max": vmax, "left": "left", "bottom": "0%", "inRange": {"color": ["#FEF3C7", PRIMARY]}, "textStyle": {"color": "#888"}, "itemWidth": 10, "itemHeight": 70},
                                    "series": [{
                                        "type": "map", "map": "TALA", "roam": False, "label": {"show": False},
                                        "itemStyle": {"borderColor": map_border_dens, "borderWidth": 1.5},
                                        "emphasis": {"label": {"show": True}, "itemStyle": {"areaColor": ACCENT, "borderColor": map_border_dens, "borderWidth": 1.5}},
                                        "data": map_data,
                                    }],
                                }
                                map_click = st_echarts(options=map_opts, map=Map("TALA", geo_data), height="360px", key="kep_map", theme=e_theme, on_select="rerun", selection_mode="points")
                            else:
                                st.info("Data kepadatan belum tersedia untuk tahun ini.")
                        else:
                            st.info("🗺️ Sistem spasial siap. Letakkan berkas `tanah_laut.geojson` sejajar dengan script.")

                if map_click and "selection" in map_click and map_click["selection"].get("point_indices") and map_data:
                    idx = map_click["selection"]["point_indices"][0]
                    if idx < len(map_data):
                        clicked_name = map_data[idx]["name"]
                        if st.session_state.get("kepen_wilayah") != clicked_name:
                            st.session_state["kepen_wilayah_pending"] = clicked_name
                            st.rerun()

                with c_gender:
                    with st.container(border=True):
                        panel_title("Penduduk Berdasarkan Jenis Kelamin")
                        gender_opts = {
                            "backgroundColor": "transparent",
                            "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                            "legend": {"bottom": 0},
                            "xAxis": {"type": "category", "data": [str(y) for y in years_k]},
                            "yAxis": {"type": "value"},
                            "series": [
                                {"name": "Laki-laki", "type": "bar", "data": df_target["lk"].tolist(), "itemStyle": {"color": COLORS[0], "borderRadius": [3, 3, 0, 0]}},
                                {"name": "Perempuan", "type": "bar", "data": df_target["pr"].tolist(), "itemStyle": {"color": COLORS[3], "borderRadius": [3, 3, 0, 0]}},
                            ],
                        }
                        st_echarts(options=gender_opts, height="360px", key="kep_gender", theme=e_theme)

                with c_rasio:
                    with st.container(border=True):
                        panel_title(f"Rasio Jenis Kelamin {int(t_aktif_k)}")
                        rasio = row_target.get("rasio_jk", np.nan)
                        _html(
                            f"<div style='text-align:center; padding:16px 0;'>"
                            f"<div style='font-size:2.1rem; font-weight:800; color:{PRIMARY};'>{fmt_id(rasio, 2)}</div>"
                            f"<div style='font-size:0.8rem; color:#888; margin-top:8px;'>Terdapat sekitar {fmt_id(rasio, 0)} "
                            f"penduduk laki-laki untuk setiap 100 penduduk perempuan.</div></div>"
                        )

                df_disp = df_target[["tahun", "jumlah_penduduk", "lk", "pr", "kepadatan", "pertumbuhan"]].rename(
                    columns={"tahun": "Tahun", "jumlah_penduduk": "Total Penduduk", "lk": "Laki-laki", "pr": "Perempuan", "kepadatan": "Kepadatan", "pertumbuhan": "Pertumbuhan (%)"}
                )
                render_custom_table(df_disp.sort_values("Tahun", ascending=False), key="kependudukan")

elif sub_kategori == "Tenaga Kerja":
    page_header("💼", "Tenaga Kerja", breadcrumb_path)
    with section_guard("Tenaga Kerja"):
        df_tk = apply_filter(get_df("Tenaga Kerja"), f_tahun).sort_values("tahun")
        if df_tk.empty:
            st.warning("Data tenaga kerja tidak tersedia untuk rentang ini.")
        else:
            years_tk = df_tk["tahun"].astype(int).tolist()
            c_chart, c_insight = st.columns([1.7, 1])
            with c_chart:
                with st.container(border=True):
                    panel_title("Perkembangan TPT dan TPAK", "Klik titik tahun untuk melihat rincian di bawahnya")
                    tk_opts = {
                        "backgroundColor": "transparent",
                        "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                        "legend": {"bottom": 0},
                        "xAxis": {"type": "category", "data": [str(y) for y in years_tk]},
                        "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
                        "series": [
                            {"name": "TPT", "type": "line", "data": df_tk["tpt"].round(2).tolist(), "smooth": True, "itemStyle": {"color": COLORS[3]}, "lineStyle": {"width": 3}, "symbolSize": 8},
                            {"name": "TPAK", "type": "bar", "data": df_tk["tpak"].round(2).tolist(), "itemStyle": {"color": COLORS[0], "borderRadius": [4, 4, 0, 0]}},
                        ],
                    }
                    tk_click = st_echarts(options=tk_opts, height="380px", key="tk_line", theme=e_theme, on_select="rerun", selection_mode="points")

            if "tk_tahun_aktif" not in st.session_state or st.session_state["tk_tahun_aktif"] not in years_tk:
                st.session_state["tk_tahun_aktif"] = years_tk[-1]
            if tk_click and "selection" in tk_click and tk_click["selection"].get("point_indices"):
                idx = tk_click["selection"]["point_indices"][0]
                if idx < len(years_tk):
                    st.session_state["tk_tahun_aktif"] = years_tk[idx]
            t_aktif_tk = st.session_state["tk_tahun_aktif"]

            row_series = df_tk[df_tk["tahun"] == t_aktif_tk]
            row_tk = row_series.iloc[0] if not row_series.empty else df_tk.iloc[-1]

            with c_insight:
                insight_box("Interpretasi", f"Pada {int(t_aktif_tk)}, TPT tercatat {row_tk['tpt']:g}% dan TPAK {row_tk['tpak']:g}%.")

            c_donut, c_stack, c_rasio = st.columns([1, 1.4, 0.8])
            donut_click = None
            donut_labels = ["Angkatan Kerja", "Bukan Angkatan Kerja"]
            with c_donut:
                with st.container(border=True):
                    panel_title(f"Proporsi {int(t_aktif_tk)}", "Klik salah satu bagian chart untuk melihat rincian")
                    tpak_val = row_tk["tpak"] if pd.notna(row_tk["tpak"]) else 0
                    donut_opts = {
                        "backgroundColor": "transparent",
                        "tooltip": {"confine": True, "formatter": "{b}: {c}%"},
                        "series": [{
                            "type": "pie", "radius": ["55%", "75%"], "avoidLabelOverlap": True, "label": {"show": False},
                            "data": [
                                {"name": donut_labels[0], "value": round(tpak_val, 2), "itemStyle": {"color": COLORS[0]}},
                                {"name": donut_labels[1], "value": round(100 - tpak_val, 2), "itemStyle": {"color": "#CBD5E1"}},
                            ],
                        }],
                    }
                    donut_click = st_echarts(options=donut_opts, height="220px", key="tk_donut", theme=e_theme, on_select="rerun", selection_mode="points")
                    _html(f"<div class='donut-center'><div class='dc-label'>Angkatan Kerja</div><div class='dc-value'>{tpak_val:g}%</div></div>")

            if "tk_kategori_aktif" not in st.session_state:
                st.session_state["tk_kategori_aktif"] = "Angkatan Kerja"
            if donut_click and "selection" in donut_click and donut_click["selection"].get("point_indices"):
                idx = donut_click["selection"]["point_indices"][0]
                if idx < len(donut_labels):
                    st.session_state["tk_kategori_aktif"] = donut_labels[idx]
            kategori_aktif_tk = st.session_state["tk_kategori_aktif"]

            with c_stack:
                with st.container(border=True):
                    if kategori_aktif_tk == "Angkatan Kerja":
                        panel_title("Rincian Angkatan Kerja", "Bekerja dan Pengangguran, per tahun")
                        stack_series = [
                            {"name": "Bekerja", "type": "bar", "stack": "s", "data": df_tk["bekerja"].round(2).tolist(), "itemStyle": {"color": COLORS[0]}},
                            {"name": "Pengangguran", "type": "bar", "stack": "s", "data": df_tk["pengangguran"].round(2).tolist(), "itemStyle": {"color": COLORS[3]}},
                        ]
                    else:
                        panel_title("Rincian Bukan Angkatan Kerja", "Sekolah / Mengurus RT / Lainnya, per tahun")
                        stack_series = [
                            {"name": "Sekolah", "type": "bar", "stack": "s", "data": df_tk["sekolah"].round(2).tolist(), "itemStyle": {"color": COLORS[2]}},
                            {"name": "Mengurus RT", "type": "bar", "stack": "s", "data": df_tk["mengurus rt"].round(2).tolist(), "itemStyle": {"color": COLORS[1]}},
                            {"name": "Lainnya", "type": "bar", "stack": "s", "data": df_tk["lainnya"].round(2).tolist(), "itemStyle": {"color": COLORS[4]}},
                        ]
                    stack_opts = {
                        "backgroundColor": "transparent",
                        "tooltip": {"trigger": "axis", "confine": True, "axisPointer": {"type": "shadow"}, "formatter": FMT_ID},
                        "legend": {"bottom": 0},
                        "xAxis": {"type": "category", "data": [str(y) for y in years_tk]},
                        "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
                        "series": stack_series,
                    }
                    st_echarts(options=stack_opts, height="280px", key="tk_stack", theme=e_theme)

            with c_rasio:
                with st.container(border=True):
                    panel_title(f"Rasio Ketergantungan {int(t_aktif_tk)}")
                    rk = row_tk.get("r_ketergantungan", np.nan)
                    _html(
                        f"<div style='text-align:center; padding:12px 0;'>"
                        f"<div style='font-size:2rem; font-weight:800; color:{PRIMARY};'>{fmt_id(rk, 2)}</div>"
                        f"<div style='font-size:0.78rem; color:#888; margin-top:8px;'>Setiap 100 penduduk usia produktif "
                        f"menanggung sekitar {fmt_id(rk, 0)} penduduk usia nonproduktif.</div></div>"
                    )

            df_disp = df_tk[["tahun", "tpt", "tpak", "bekerja", "pengangguran", "r_ketergantungan"]].rename(
                columns={"tahun": "Tahun", "tpt": "TPT (%)", "tpak": "TPAK (%)", "bekerja": "Bekerja (%)", "pengangguran": "Pengangguran (%)", "r_ketergantungan": "Rasio Ketergantungan"}
            )
            render_custom_table(df_disp.sort_values("Tahun", ascending=False), key="tenaga_kerja")

elif sub_kategori == "Kemiskinan":
    page_header("📉", "Kemiskinan", breadcrumb_path)
    with section_guard("Kemiskinan"):
        df_k = apply_filter(get_df("Kemiskinan_IPM"), f_tahun).sort_values("tahun")
        if df_k.empty:
            st.warning("Data kemiskinan tidak tersedia untuk rentang ini.")
        else:
            years_m = df_k["tahun"].astype(int).tolist()
            last = df_k.iloc[-1]
            c1, c2 = st.columns([1.6, 1])
            with c1:
                with st.container(border=True):
                    panel_title("Jumlah Penduduk Miskin dan Garis Kemiskinan")
                    dual_opts = {
                        "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "confine": True, "axisPointer": {"type": "cross"}},
                        "legend": {"bottom": 0},
                        "xAxis": {"type": "category", "data": [str(y) for y in years_m]},
                        "yAxis": [{"type": "value", "name": "Jiwa"}, {"type": "value", "name": "Rupiah", "splitLine": {"show": False}}],
                        "series": [
                            {"name": "Jumlah Miskin", "type": "bar", "data": df_k["jml_miskin"].tolist(), "itemStyle": {"color": COLORS[0], "borderRadius": [4, 4, 0, 0]}},
                            {"name": "Garis Kemiskinan", "type": "line", "yAxisIndex": 1, "data": df_k["garis_kemiskinan"].tolist(), "itemStyle": {"color": COLORS[3]}, "lineStyle": {"width": 3}},
                        ],
                    }
                    st_echarts(options=dual_opts, height="380px", key="mis_dual", theme=e_theme)
            with c2:
                insight_box(
                    "Interpretasi",
                    f"Pada {int(last['tahun'])}, persentase penduduk miskin (P0) Kabupaten Tanah Laut sebesar {last['p0']:g}%, "
                    f"dengan {fmt_id(last['jml_miskin'])} jiwa berada di bawah garis kemiskinan Rp {fmt_id(last['garis_kemiskinan'])}/kapita/bulan.",
                )
                with st.container(border=True):
                    df_gini_valid = df_k.dropna(subset=["gini"])
                    row_gini = df_gini_valid.iloc[-1] if not df_gini_valid.empty else last
                    panel_title(f"Rasio Gini {int(row_gini['tahun'])}")
                    _html(f"<div style='text-align:center; padding:16px 0;'><div style='font-size:2.3rem; font-weight:800; color:{PRIMARY};'>{fmt_id(row_gini['gini'], 3)}</div></div>")
                    st.caption("Koefisien Gini yang semakin mendekati 0 berarti mendekati pemerataan sempurna, sedangkan semakin mendekati 1 berarti ketimpangan sempurna.")

            c_p0, c_p1, c_p2 = st.columns(3)
            mini_trend_panel(c_p0, "Persentase Penduduk Miskin (P0)", years_m, df_k["p0"].tolist(), COLORS[0], decimals=2, suffix="%")
            mini_trend_panel(c_p1, "Indeks Kedalaman Kemiskinan (P1)", years_m, df_k["p1"].tolist(), COLORS[1], decimals=2)
            mini_trend_panel(c_p2, "Indeks Keparahan Kemiskinan (P2)", years_m, df_k["p2"].tolist(), COLORS[3], decimals=2)

            df_disp = df_k[["tahun", "p0", "p1", "p2", "jml_miskin", "garis_kemiskinan", "gini"]].rename(
                columns={"tahun": "Tahun", "p0": "P0 (%)", "p1": "P1", "p2": "P2", "jml_miskin": "Jumlah (Jiwa)", "garis_kemiskinan": "Garis Kemiskinan (Rp)", "gini": "Rasio Gini"}
            )
            render_custom_table(df_disp.sort_values("Tahun", ascending=False), key="kemiskinan")

elif sub_kategori == "IPM":
    page_header("📚", "Indeks Pembangunan Manusia (IPM)", breadcrumb_path)
    with section_guard("IPM"):
        df_i = apply_filter(get_df("Kemiskinan_IPM"), f_tahun).sort_values("tahun")
        if df_i.empty:
            st.warning("Data IPM tidak tersedia untuk rentang ini.")
        else:
            years_i = df_i["tahun"].astype(int).tolist()
            df_i_valid = df_i.dropna(subset=["ipm"])
            c_hero, c_uhh, c_hls, c_rls, c_peng = st.columns([1.4, 1, 1, 1, 1])
            if not df_i_valid.empty:
                last_i = df_i_valid.iloc[-1]
                prev_i = df_i_valid.iloc[-2] if len(df_i_valid) > 1 else None
                with c_hero:
                    with st.container(border=True):
                        ipm_hero_card(
                            last_i["tahun"], last_i["ipm"],
                            prev_i["ipm"] if prev_i is not None else np.nan,
                            prev_i["tahun"] if prev_i is not None else np.nan,
                        )

            sparkline_kpi_card(c_uhh, "Usia Harapan Hidup (UHH)", f"{fmt_id(last_i['uhh'], 2)} tahun" if not df_i_valid.empty else "-", None, "flat", [str(y) for y in years_i], df_i["uhh"].tolist(), COLORS[0])
            sparkline_kpi_card(c_hls, "Harapan Lama Sekolah (HLS)", f"{fmt_id(last_i['hls'], 2)} tahun" if not df_i_valid.empty else "-", None, "flat", [str(y) for y in years_i], df_i["hls"].tolist(), COLORS[0])
            sparkline_kpi_card(c_rls, "Rata-rata Lama Sekolah (RLS)", f"{fmt_id(last_i['rls'], 2)} tahun" if not df_i_valid.empty else "-", None, "flat", [str(y) for y in years_i], df_i["rls"].tolist(), COLORS[0])
            sparkline_kpi_card(c_peng, "Pengeluaran/Kapita Disesuaikan", f"Rp {fmt_id(last_i['pengeluaran'])} rb" if not df_i_valid.empty else "-", None, "flat", [str(y) for y in years_i], df_i["pengeluaran"].tolist(), COLORS[0])

            if not df_i_valid.empty:
                gap = last_i["ipm"] - last_i["ipm_kalsel"] if pd.notna(last_i.get("ipm_kalsel")) else None
                gap_txt = f" — {'melampaui' if gap > 0 else 'di bawah'} rata-rata provinsi sebesar {abs(gap):.2f} poin." if gap is not None else "."
                insight_box("Interpretasi", f"IPM Kabupaten Tanah Laut pada {int(last_i['tahun'])} sebesar {last_i['ipm']:g}{gap_txt}")

            with st.container(border=True):
                panel_title("Perbandingan IPM Tanah Laut dan Kalimantan Selatan")
                ipm_opts = {
                    "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                    "legend": {"bottom": 0},
                    "xAxis": {"type": "category", "data": [str(y) for y in years_i]},
                    "yAxis": {"type": "value", "scale": True},
                    "series": [
                        {"name": "Tanah Laut", "type": "bar", "data": df_i["ipm"].round(2).tolist(), "itemStyle": {"color": COLORS[0], "borderRadius": [4, 4, 0, 0]}},
                        {"name": "Kalimantan Selatan", "type": "line", "data": df_i["ipm_kalsel"].round(2).tolist(), "itemStyle": {"color": COLORS[1]}, "lineStyle": {"width": 3}, "symbolSize": 8},
                    ],
                }
                st_echarts(options=ipm_opts, height="380px", key="ipm_bar", theme=e_theme)

            c_heat, c_g_insight = st.columns([1.6, 1])
            with c_heat:
                with st.container(border=True):
                    panel_title("Indeks-Indeks Gender")
                    render_gender_heatmap(years_i, df_i["ipg"].tolist(), df_i["idg"].tolist(), df_i["ikg"].tolist())
            with c_g_insight:
                with st.container(border=True):
                    panel_title("Insight")
                    st.caption(
                        "**IPG** yang semakin mendekati 100 menunjukkan pembangunan yang semakin setara antara "
                        "perempuan dan laki-laki.\n\n"
                        "**IDG** yang semakin mendekati 100 menunjukkan peran aktif perempuan dalam kegiatan "
                        "ekonomi dan politik.\n\n"
                        "**IKG** yang semakin menjauhi 1 menunjukkan ketimpangan gender semakin berkurang."
                    )

            df_disp = df_i[["tahun", "ipm", "ipm_kalsel", "uhh", "hls", "rls", "pengeluaran"]].rename(
                columns={"tahun": "Tahun", "ipm": "IPM Tala", "ipm_kalsel": "IPM Kalsel", "uhh": "UHH", "hls": "HLS", "rls": "RLS", "pengeluaran": "Pengeluaran/Kapita Disesuaikan (Ribu Rupiah)"}
            )
            render_custom_table(df_disp.sort_values("Tahun", ascending=False), key="ipm")

elif sub_kategori == "Inflasi":
    page_header("🛒", "Inflasi", breadcrumb_path, "Perkembangan Indeks Harga Konsumen Kabupaten Tanah Laut")
    with section_guard("Inflasi"):
        df_inf_all = get_df("Inflasi_NTP")
        df_2026 = df_inf_all[(df_inf_all["tahun"] == 2026) & (df_inf_all["ihk"].notna())].copy()
        if df_2026.empty or not bulan_range:
            st.warning("Data inflasi 2026 tidak tersedia.")
        else:
            df_2026["bulan_idx"] = df_2026["bulan"].apply(lambda b: BULAN_URUT.index(b) if b in BULAN_URUT else -1)
            df_2026 = df_2026.sort_values("bulan_idx")
            i0, i1 = BULAN_URUT.index(bulan_range[0]), BULAN_URUT.index(bulan_range[1])
            df_f = df_2026[(df_2026["bulan_idx"] >= i0) & (df_2026["bulan_idx"] <= i1)]

            if df_f.empty:
                st.warning("Tidak ada data untuk rentang bulan yang dipilih.")
            else:
                last_row = df_f.iloc[-1]
                prev_row = df_f.iloc[-2] if len(df_f) > 1 else None

                def _delta(col):
                    if prev_row is None or pd.isna(last_row[col]) or pd.isna(prev_row[col]) or prev_row[col] == 0:
                        return None, "flat"
                    d = last_row[col] - prev_row[col]
                    return f"{d:+.2f}%", ("up" if d > 0 else ("down" if d < 0 else "flat"))

                c1, c2, c3, c4 = st.columns(4)
                dtxt, ddir = _delta("ihk")
                sparkline_kpi_card(c1, "Indeks Harga Konsumen", fmt_id(last_row["ihk"], 2), dtxt, ddir, df_f["bulan"].tolist(), df_f["ihk"].tolist(), COLORS[2], chart_type="bar")
                dtxt, ddir = _delta("inflasi_mtm")
                sparkline_kpi_card(c2, "Inflasi Month-to-Month", f"{last_row['inflasi_mtm']:g}%", dtxt, ddir, df_f["bulan"].tolist(), df_f["inflasi_mtm"].tolist(), COLORS[3])
                dtxt, ddir = _delta("inflasi_ytd")
                sparkline_kpi_card(c3, "Inflasi Year-to-Date", f"{last_row['inflasi_ytd']:g}%", dtxt, ddir, df_f["bulan"].tolist(), df_f["inflasi_ytd"].tolist(), COLORS[1])
                dtxt, ddir = _delta("inflasi_yoy")
                sparkline_kpi_card(c4, "Inflasi Year-on-Year", f"{last_row['inflasi_yoy']:g}%", dtxt, ddir, df_f["bulan"].tolist(), df_f["inflasi_yoy"].tolist(), COLORS[2])

                insight_box(
                    "Interpretasi",
                    f"Pada {last_row['bulan']} 2026, IHK Kabupaten Tanah Laut tercatat {last_row['ihk']:g} dengan inflasi "
                    f"bulanan (mtm) {last_row['inflasi_mtm']:g}%, inflasi tahun berjalan (ytd) {last_row['inflasi_ytd']:g}%, "
                    f"dan inflasi tahunan (yoy) {last_row['inflasi_yoy']:g}%.",
                )

                # ---- Kotak dokumen PDF Bahan Rilis Inflasi ----
                # Sumber dokumen BUKAN berkas lokal - link Google Drive-nya ada di
                # sheet Inflasi_NTP, kolom "bahan_rilis" (diisi manual tiap bulan
                # rilis tersedia; boleh kosong untuk bulan yang belum ada rilisnya).
                # Yang ditampilkan selalu bahan rilis dari bulan TERBARU yang sudah
                # terisi - bukan bulan terbaru di data inflasi secara umum, karena
                # rilisnya bisa saja belum diunggah untuk bulan paling baru.
                if "bahan_rilis" in df_inf_all.columns:
                    df_rilis_src = df_inf_all[df_inf_all["bahan_rilis"].notna() & (df_inf_all["bahan_rilis"].astype(str).str.strip() != "")].copy()
                else:
                    df_rilis_src = pd.DataFrame()
                if not df_rilis_src.empty:
                    df_rilis_src["bulan_idx"] = df_rilis_src["bulan"].apply(lambda b: BULAN_URUT.index(b) if b in BULAN_URUT else -1)
                    df_rilis_src = df_rilis_src.sort_values(["tahun", "bulan_idx"])
                    row_rilis = df_rilis_src.iloc[-1]
                    rilis_url = str(row_rilis["bahan_rilis"]).strip()
                    rilis_label_bulan = f"{row_rilis['bulan']} {int(row_rilis['tahun'])}"
                else:
                    rilis_url, rilis_label_bulan = None, None

                with st.container(border=True):
                    sub_rilis = f"Dokumen resmi rilis inflasi bulanan Kabupaten Tanah Laut terbaru ({rilis_label_bulan})" if rilis_label_bulan else "Dokumen resmi rilis inflasi bulanan Kabupaten Tanah Laut"
                    panel_title("📄 Bahan Rilis Inflasi", sub_rilis)
                    if rilis_url:
                        # PENTING: konten di dalam <a> HARUS berupa elemen inline (<span>),
                        # bukan <div>/<p> - versi sebelumnya menaruh <div><p>...</p></div> di
                        # dalam <a>, dan itu membuat renderer markdown Streamlit memecah
                        # tiap elemen jadi "kotak" terpisah-pisah (persis gejala di screenshot:
                        # ikon, judul, dan subjudul masing-masing muncul sebagai box sendiri).
                        # Dengan <span> semua, satu kartu tetap jadi SATU blok utuh.
                        # Tautan unduh cadangan dibuat kecil & sekunder (bukan kartu penuh
                        # lagi) supaya tidak menambah "kotak" baru - cukup satu baris teks
                        # kecil di bawah kartu utama, sesuai masukan bahwa terlalu banyak
                        # kotak di bagian ini kurang enak dilihat.
                        file_id = extract_drive_file_id(rilis_url)
                        badge_html = ""
                        if file_id:
                            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                            badge_html = (
                                f"<a class='pdf-badge' "
                                f"href='{download_url}' "
                                f"target='_self' "
                                f"onclick=\"event.preventDefault(); var ifr = document.createElement('iframe'); ifr.style.display = 'none'; ifr.src = '{download_url}'; document.body.appendChild(ifr); return false;\">"
                                f"📥 Unduh PDF"
                                f"</a>"
                            )
                        _html(
                            f"<div class='pdf-card'>"
                                f"<span class='pdf-card-icon'>📄</span>"
                                f"<div class='pdf-card-text'>"
                                    f"<a class='pdf-card-title' href='{html.escape(rilis_url)}' target='_blank' rel='noopener noreferrer'>Buka Dokumen Rilis Inflasi</a>"
                                    f"<span class='pdf-card-sub'>Klik judul untuk melihat, atau gunakan tombol di bawah untuk mengunduh.</span>"
                                    f"{badge_html}"
                                f"</div>"
                            f"</div>"
                        )
                    else:
                        st.info(
                            "📄 Dokumen rilis inflasi belum tersedia. Isi link Google Drive PDF-nya di sheet "
                            "'Inflasi_NTP' kolom 'bahan_rilis' pada baris bulan yang sesuai untuk mengaktifkan fitur ini."
                        )

                # Mekanisme: untuk tiap bulan (Jan s.d. bulan berjalan), ranking komoditas
                # berdasar Andil M-to-M (descending utk pendorong, ascending utk penahan),
                # ambil top 10, lalu hitung berapa kali tiap komoditas nongol di top-10
                # sepanjang tahun berjalan (frekuensi). Cuma yang frekuensi >= 3 yang
                # ditampilkan sbg bubble - makanya chart ini baru bisa muncul mulai Maret.
                #
                # Sumbu-X = IHK PER KOMODITAS (sheet "IHK Komoditas") pada BULAN BERJALAN -
                # bukan rata-rata, bukan IHK gabungan Tanah Laut - supaya apple to apple
                # dengan sumbu-Y (Andil M-to-M komoditas itu, juga bulan berjalan).
                df_kom = get_komoditas()
                df_ihk_kom = get_ihk_komoditas()
                bulan_aktif = last_row["bulan"]
                bulan_cols_sofar = [b for b in BULAN_URUT if b in df_kom.columns and BULAN_URUT.index(b) <= BULAN_URUT.index(bulan_aktif)] if not df_kom.empty else []

                bubble_pendorong, bubble_penahan = [], []
                if len(bulan_cols_sofar) < 3:
                    st.info(f"📊 Analisis Top 10 komoditas butuh minimal 3 bulan data tahun berjalan - baru bisa ditampilkan mulai Maret 2026 (saat ini: {bulan_aktif}).")
                else:
                    pendorong_freq, penahan_freq = {}, {}
                    for b in bulan_cols_sofar:
                        col_valid = df_kom[["komoditas", b]].dropna()
                        for _, r in col_valid.sort_values(b, ascending=False).head(10).iterrows():
                            pendorong_freq[r["komoditas"]] = pendorong_freq.get(r["komoditas"], 0) + 1
                        for _, r in col_valid.sort_values(b, ascending=True).head(10).iterrows():
                            penahan_freq[r["komoditas"]] = penahan_freq.get(r["komoditas"], 0) + 1

                    def _build_bubbles(freq_dict, min_freq=3):
                        out = []
                        for kom, freq in freq_dict.items():
                            if freq < min_freq:
                                continue
                            cur_andil = df_kom.loc[df_kom["komoditas"] == kom, bulan_aktif]
                            andil_val = cur_andil.iloc[0] if not cur_andil.empty and pd.notna(cur_andil.iloc[0]) else None
                            ihk_val = None
                            if not df_ihk_kom.empty and bulan_aktif in df_ihk_kom.columns:
                                cur_ihk = df_ihk_kom.loc[df_ihk_kom["komoditas"] == kom, bulan_aktif]
                                if not cur_ihk.empty and pd.notna(cur_ihk.iloc[0]):
                                    ihk_val = cur_ihk.iloc[0]
                            if andil_val is not None and ihk_val is not None:
                                out.append({"name": kom, "value": [round(ihk_val, 2), round(andil_val, 4), freq]})
                        return out

                    bubble_pendorong = _build_bubbles(pendorong_freq)
                    bubble_penahan = _build_bubbles(penahan_freq)

                    size_js = JsCode("function(val){ return Math.max(14, val[2] * 7); }")
                    tooltip_js = JsCode(
                        "function(p){return '<b>'+p.data.name+'</b><br/>IHK Bulan Berjalan: '+p.data.value[0]+"
                        "'<br/>Andil bulan berjalan: '+p.data.value[1]+'%<br/>Frekuensi Top 10: '+p.data.value[2]+'x';}"
                    )

                    c_dorong, c_tahan = st.columns(2)
                    with c_dorong:
                        with st.container(border=True):
                            panel_title("Komoditas Utama Pendorong Inflasi M-to-M", "Bubble = frekuensi masuk Top 10 (min. 3x) sepanjang 2026")
                            if bubble_pendorong:
                                opts = {
                                    "backgroundColor": "transparent", "tooltip": {"confine": True, "formatter": tooltip_js},
                                    "xAxis": {"type": "value", "name": "IHK Bulan Berjalan", "nameLocation": "middle", "nameGap": 28},
                                    "yAxis": {"type": "value", "name": "Andil Bulan Berjalan (%)"},
                                    "series": [{"type": "scatter", "data": bubble_pendorong, "symbolSize": size_js, "itemStyle": {"color": COLORS[3], "opacity": 0.75}, "label": {"show": True, "formatter": "{b}", "position": "top", "fontSize": 9}}],
                                }
                                st_echarts(options=opts, height="380px", key="inf_bubble_pendorong", theme=e_theme)
                            else:
                                st.info("Belum ada komoditas dengan frekuensi Top 10 >= 3x.")
                    with c_tahan:
                        with st.container(border=True):
                            panel_title("Komoditas Utama Penahan Inflasi M-to-M", "Bubble = frekuensi masuk Top 10 (min. 3x) sepanjang 2026")
                            if bubble_penahan:
                                opts = {
                                    "backgroundColor": "transparent", "tooltip": {"confine": True, "formatter": tooltip_js},
                                    "xAxis": {"type": "value", "name": "IHK Bulan Berjalan", "nameLocation": "middle", "nameGap": 28},
                                    "yAxis": {"type": "value", "name": "Andil Bulan Berjalan (%)"},
                                    "series": [{"type": "scatter", "data": bubble_penahan, "symbolSize": size_js, "itemStyle": {"color": COLORS[0], "opacity": 0.75}, "label": {"show": True, "formatter": "{b}", "position": "top", "fontSize": 9}}],
                                }
                                st_echarts(options=opts, height="380px", key="inf_bubble_penahan", theme=e_theme)
                            else:
                                st.info("Belum ada komoditas dengan frekuensi Top 10 >= 3x.")

                    # Interpretasi otomatis mengikuti template yang diminta:
                    # - "kenaikan harga terbesar" & "penahan inflasi utama" = komoditas
                    #   dengan andil TERTINGGI/TERENDAH pada BULAN BERJALAN SAJA (dari
                    #   seluruh komoditas bulan itu, tidak dibatasi ke yang tampil di
                    #   bubble chart / freq >= 3).
                    # - "konsisten mendorong/menahan" = komoditas dengan FREKUENSI top-10
                    #   terbanyak sepanjang tahun berjalan (dari pendorong_freq/penahan_freq,
                    #   juga tidak dibatasi ke freq >= 3 supaya benar-benar "yang paling sering").
                    # Setiap bagian dicek non-kosong dulu sebelum dipakai, supaya kondisi
                    # filter apa pun (termasuk bulan pertama tahun berjalan) tidak memicu error.
                    col_now = df_kom[["komoditas", bulan_aktif]].dropna()
                    if not col_now.empty and pendorong_freq and penahan_freq:
                        top_now = col_now.loc[col_now[bulan_aktif].idxmax()]
                        bottom_now = col_now.loc[col_now[bulan_aktif].idxmin()]
                        freq_p_name, freq_p_val = max(pendorong_freq.items(), key=lambda kv: kv[1])
                        freq_t_name, freq_t_val = max(penahan_freq.items(), key=lambda kv: kv[1])
                        insight_box(
                            "Interpretasi Komoditas Pendorong & Penahan Inflasi",
                            f"Pada {bulan_aktif}, kenaikan harga terbesar didorong oleh {str(top_now['komoditas']).title()} "
                            f"dengan andil {top_now[bulan_aktif]:g}%. Di sisi lain, komoditas penahan inflasi utama adalah "
                            f"{str(bottom_now['komoditas']).title()} dengan andil {bottom_now[bulan_aktif]:g}%. Selama tahun "
                            f"{int(last_row['tahun'])}, komoditas yang konsisten mendorong inflasi adalah {str(freq_p_name).title()} "
                            f"(muncul {freq_p_val}x sebagai Top 10) dan komoditas yang konsisten menahan inflasi adalah "
                            f"{str(freq_t_name).title()} (muncul {freq_t_val}x sebagai Top 10).",
                        )

                df_harga = apply_filter(get_df("Harga"), (2026, 2026))
                if not df_harga.empty:
                    df_harga = df_harga.copy()
                    df_harga["bulan_full"] = df_harga["bulan"].map(BULAN_ABBR_MAP)
                    df_harga["bulan_idx"] = df_harga["bulan_full"].apply(lambda b: BULAN_URUT.index(b) if b in BULAN_URUT else -1)
                    df_harga_f = df_harga[(df_harga["bulan_idx"] >= i0) & (df_harga["bulan_idx"] <= i1)].sort_values(["bulan_idx", "minggu"])
                    if not df_harga_f.empty:
                        periode_labels = (df_harga_f["bulan"].astype(str) + "-m" + df_harga_f["minggu"].fillna(0).astype(int).astype(str)).tolist()
                        panel_title("Perkembangan Harga Mingguan Komoditas Utama")
                        c_h1, c_h2 = st.columns(2)
                        group1 = [("Bawang Merah", "bawang merah"), ("Bawang Putih", "bawang putih"), ("Beras", "beras"), ("Daging Ayam Ras", "daging ayam ras"), ("Telur Ayam Ras", "telur ayam ras")]
                        group2 = [("Ikan Gabus", "ikan gabus"), ("Ikan Nila", "ikan nila"), ("Gula Pasir", "gula pasir"), ("Minyak Goreng", "minyak goreng"), ("Cabai Rawit", "cabai rawit")]
                        for c_h, group, chart_key in [(c_h1, group1, "harga1"), (c_h2, group2, "harga2")]:
                            with c_h:
                                with st.container(border=True):
                                    series = [{"name": label, "type": "line", "data": df_harga_f[col].tolist(), "smooth": True, "symbolSize": 0, "itemStyle": {"color": COLORS[idx % len(COLORS)]}} for idx, (label, col) in enumerate(group)]
                                    opts = {
                                        "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                                        # grid diberi jarak eksplisit dari tepi (containLabel: true supaya
                                        # label sumbu-Y ikut dihitung) - sebelumnya tanpa "grid" sama sekali,
                                        # jadi saat legend (5 item) wrap ke 2 baris di layar sempit, ia
                                        # menabrak sumbu-X di bawahnya.
                                        "grid": {"top": "8%", "bottom": "20%", "left": "10%", "right": "4%", "containLabel": True},
                                        "legend": {"bottom": 0, "textStyle": {"fontSize": 10}, "itemWidth": 12, "itemHeight": 8, "itemGap": 10},
                                        "xAxis": {"type": "category", "data": periode_labels, "axisLabel": {"fontSize": 9}},
                                        "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}"}},
                                        "series": series,
                                    }
                                    st_echarts(options=opts, height="360px", key=chart_key, theme=e_theme)
                    else:
                        st.info("Tidak ada data harga untuk rentang bulan ini.")
                else:
                    st.info("Data harga mingguan belum tersedia.")

                df_disp = df_f[["bulan", "ihk", "inflasi_mtm", "inflasi_ytd", "inflasi_yoy"]].rename(
                    columns={"bulan": "Bulan", "ihk": "IHK", "inflasi_mtm": "MtM (%)", "inflasi_ytd": "YtD (%)", "inflasi_yoy": "YoY (%)"}
                )
                render_custom_table(df_disp.iloc[::-1], key="inflasi")

elif sub_kategori == "Track Record Inflasi":
    with section_guard("Track Record Inflasi"):
        df_tr = get_df("Inflasi_NTP")
        if df_tr.empty:
            page_header("📊", "Track Record Inflasi", breadcrumb_path, "Rekam Jejak Inflasi Kabupaten Tanah Laut")
            st.warning("Data inflasi tidak tersedia.")
        else:
            df_tr = df_tr.copy()
            df_tr["bulan_idx"] = df_tr["bulan"].apply(lambda b: BULAN_URUT.index(b) if b in BULAN_URUT else -1)
            df_tr = df_tr[df_tr["bulan_idx"] >= 0].sort_values(["tahun", "bulan_idx"]).reset_index(drop=True)

            # Rentang waktu ditampilkan dinamis mengikuti data yang benar-benar ada di
            # sheet (bukan di-hardcode "Jan 2024 - Jul 2026") - supaya sub-judul selalu
            # akurat begitu data terbaru ditambahkan tanpa perlu mengedit kode.
            bulan_awal, tahun_awal = df_tr["bulan"].iloc[0], int(df_tr["tahun"].iloc[0])
            bulan_akhir, tahun_akhir = df_tr["bulan"].iloc[-1], int(df_tr["tahun"].iloc[-1])
            rentang_waktu = f"{bulan_awal} {tahun_awal} - {bulan_akhir} {tahun_akhir}"
            page_header("📊", "Track Record Inflasi", breadcrumb_path, f"Rekam Jejak Inflasi Kabupaten Tanah Laut, {rentang_waktu}")

            labels_tr = [f"{BULAN_ABBR3.get(b, b)}-{str(int(t))[2:]}" for b, t in zip(df_tr["bulan"], df_tr["tahun"])]

            with st.container(border=True):
                panel_title("Inflasi Month-to-Month, Year-to-Date, dan Year-on-Year", rentang_waktu)
                opts_multi = {
                    "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                    "legend": {"bottom": 0},
                    "grid": {"top": "8%", "bottom": "16%", "left": "6%", "right": "4%", "containLabel": True},
                    "xAxis": {"type": "category", "data": labels_tr, "axisLabel": {"fontSize": 9, "interval": 1, "rotate": 45}},
                    "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
                    "series": [
                        {"name": "m-to-m", "type": "line", "data": df_tr["inflasi_mtm"].round(2).tolist(), "smooth": True, "itemStyle": {"color": COLORS[0]}, "lineStyle": {"width": 2}, "symbolSize": 4},
                        {"name": "y-to-d", "type": "line", "data": df_tr["inflasi_ytd"].round(2).tolist(), "smooth": True, "itemStyle": {"color": COLORS[1]}, "lineStyle": {"width": 2}, "symbolSize": 4},
                        {"name": "y-on-y", "type": "line", "data": df_tr["inflasi_yoy"].round(2).tolist(), "smooth": True, "itemStyle": {"color": COLORS[3]}, "lineStyle": {"width": 2.5}, "symbolSize": 4},
                    ],
                }
                st_echarts(options=opts_multi, height="400px", key="tr_inflasi_line", theme=e_theme)

            with st.container(border=True):
                panel_title("Indeks Harga Konsumen (IHK)", rentang_waktu)
                opts_ihk = {
                    "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "formatter": FMT_ID},
                    "grid": {"top": "8%", "bottom": "16%", "left": "6%", "right": "4%", "containLabel": True},
                    "xAxis": {"type": "category", "data": labels_tr, "axisLabel": {"fontSize": 9, "interval": 1, "rotate": 45}},
                    "yAxis": {"type": "value", "scale": True},
                    "series": [{"name": "IHK", "type": "line", "data": df_tr["ihk"].round(2).tolist(), "smooth": True, "areaStyle": {"opacity": 0.12}, "itemStyle": {"color": COLORS[2]}, "lineStyle": {"width": 3}, "symbolSize": 4}],
                }
                st_echarts(options=opts_ihk, height="340px", key="tr_ihk_line", theme=e_theme)

            with st.container(border=True):
                panel_title("Inflasi Year-on-Year Berdasarkan Kelompok Pengeluaran", "Pilih maksimal 3 kelompok untuk dibandingkan")
                df_coicop = get_coicop()
                if df_coicop.empty:
                    st.info("Data inflasi per kelompok pengeluaran belum tersedia.")
                else:
                    df_coicop = df_coicop.copy()
                    df_coicop["bulan_idx"] = df_coicop["bulan"].apply(lambda b: BULAN_URUT.index(b) if b in BULAN_URUT else -1)
                    df_coicop = df_coicop[df_coicop["bulan_idx"] >= 0].sort_values(["tahun", "bulan_idx"]).reset_index(drop=True)
                    kategori_cols = [c for c in df_coicop.columns if c not in ("tahun", "bulan", "bulan_idx")]

                    # Batas maksimal 3 pilihan DITEGAKKAN MANUAL (bukan lewat parameter
                    # max_selections bawaan st.multiselect) karena dua alasan sekaligus:
                    # 1) pesan bawaan "You can only select up to 3 options..." berbahasa
                    #    Inggris dan tidak bisa diubah teksnya/gayanya;
                    # 2) begitu batas tersentuh, kotak pilihan (tag komoditas) melebar
                    #    jadi satu baris panjang yang terpotong/harus di-scroll - kurang
                    #    enak dilihat, terutama di layar sempit.
                    # Solusinya: kelebihan pilihan di-"potong kembali" ke 3 item TERAKHIR
                    # yang valid, sebelum widget dibuat di run berikutnya (bukan sesudah -
                    # itu dilarang Streamlit di run yang sama) - lihat pola yang sama di
                    # "kepen_wilayah_pending" pada bagian sidebar.
                    ms_key = "coicop_pilihan"

                    pilihan = st.multiselect(
                        "Kelompok Pengeluaran", kategori_cols, default=kategori_cols[:1], key=ms_key,
                        format_func=lambda k: COICOP_SHORT_LABEL.get(k, k)
                    )

                    if not pilihan:
                        st.info("Pilih minimal 1 kelompok pengeluaran untuk menampilkan grafik.")
                    elif len(pilihan) > 3:
                        _html(
                            "<div class='limit-notice'>⚠️ <b>Maksimal 3 kelompok pengeluaran.</b> "
                            "Anda memilih terlalu banyak kelompok sehingga grafik akan tumpang tindih dan sulit dibaca. "
                            "Silakan hapus beberapa pilihan untuk memunculkan grafik.</div>"
                        )
                    else:
                        labels_co = [f"{BULAN_ABBR3.get(b, b)}-{str(int(t))[2:]}" for b, t in zip(df_coicop["bulan"], df_coicop["tahun"])]
                        series_co = [
                            {"name": k, "type": "line", "data": df_coicop[k].round(2).tolist(), "smooth": True, "itemStyle": {"color": COLORS[i % len(COLORS)]}, "lineStyle": {"width": 2.5}, "symbolSize": 4}
                            for i, k in enumerate(pilihan)
                        ]
                        opts_co = {
                            "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                            "legend": {"bottom": 0, "type": "scroll", "textStyle": {"fontSize": 10}},
                            "grid": {"top": "8%", "bottom": "20%", "left": "6%", "right": "4%", "containLabel": True},
                            "xAxis": {"type": "category", "data": labels_co, "axisLabel": {"fontSize": 9, "interval": 1, "rotate": 45}},
                            "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
                            "series": series_co,
                        }
                        st_echarts(options=opts_co, height="420px", key="tr_coicop_line", theme=e_theme)

elif sub_kategori == "Pertumbuhan Ekonomi":
    page_header("📈", "Pertumbuhan Ekonomi", breadcrumb_path)
    with section_guard("Pertumbuhan Ekonomi"):
        df_p = apply_filter(get_df("PDRB"), f_tahun).sort_values("tahun")
        if df_p.empty:
            st.warning("Data PDRB tidak tersedia untuk rentang ini.")
        else:
            years_p = df_p["tahun"].astype(int).tolist()
            with st.container(border=True):
                panel_title("Laju Pertumbuhan Ekonomi vs PDRB per Kapita", "Klik titik tahun untuk melihat distribusi PDRB di bawah")
                growth_opts = {
                    "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "confine": True, "formatter": FMT_ID},
                    "legend": {"bottom": 0},
                    "xAxis": {"type": "category", "data": [str(y) for y in years_p], "name": "tahun", "nameLocation": "middle", "nameGap": 30},
                    "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
                    "series": [
                        {"name": "Pertumbuhan Ekonomi", "type": "line", "data": df_p["pert_eko"].round(2).tolist(), "smooth": True, "itemStyle": {"color": ACCENT}, "lineStyle": {"width": 3}, "symbolSize": 8},
                        {"name": "Pertumbuhan PDRB per Kapita", "type": "line", "data": df_p["pert_pdrb_perkapita"].round(2).tolist() if "pert_pdrb_perkapita" in df_p.columns else [], "smooth": True, "itemStyle": {"color": COLORS[2]}, "lineStyle": {"width": 3}, "symbolSize": 8},
                    ],
                }
                pdrb_click = st_echarts(options=growth_opts, height="400px", key="pdrb_growth", theme=e_theme, on_select="rerun", selection_mode="points")

            if "pdrb_tahun_aktif" not in st.session_state or st.session_state["pdrb_tahun_aktif"] not in years_p:
                st.session_state["pdrb_tahun_aktif"] = years_p[-1]
            if pdrb_click and "selection" in pdrb_click and pdrb_click["selection"].get("point_indices"):
                idx = pdrb_click["selection"]["point_indices"][0] % len(years_p)
                st.session_state["pdrb_tahun_aktif"] = years_p[idx]
            t_aktif_p = st.session_state["pdrb_tahun_aktif"]

            row_p_series = df_p[df_p["tahun"] == t_aktif_p]
            row_p = row_p_series.iloc[0] if not row_p_series.empty else df_p.iloc[-1]
            insight_box(
                "Interpretasi",
                f"Ekonomi Tanah Laut tumbuh {row_p['pert_eko']:.2f}% pada {int(t_aktif_p)}, dengan PDRB per kapita "
                f"(ADHK) sebesar Rp {fmt_id(row_p['pdptn_perkapita_adhk'])} ribu.",
            )

            def _donut_grouped(df_kat, top_n=5):
                d = df_kat.sort_values("pangsa", ascending=False)
                top = d.head(top_n)
                sisanya = d["pangsa"].iloc[top_n:].sum() if len(d) > top_n else 0
                data = [{"name": r["sektor"], "value": round(r["pangsa"], 2)} for _, r in top.iterrows()]
                if sisanya > 0.01:
                    data.append({"name": "Lainnya", "value": round(sisanya, 2)})
                return data

            df_dist = get_dist_pdrb()
            c_d1, c_d2 = st.columns(2)
            if not df_dist.empty:
                for c_d, kat, judul, chart_key in [(c_d1, "lapus", "Distribusi PDRB Berdasarkan Lapangan Usaha", "dist_lapus"), (c_d2, "pengeluaran", "Distribusi PDRB Berdasarkan Pengeluaran", "dist_pengeluaran")]:
                    with c_d:
                        with st.container(border=True):
                            panel_title(f"{judul} {int(t_aktif_p)}")
                            df_kat_year = df_dist[(df_dist["kategori"] == kat) & (df_dist["tahun"] == t_aktif_p)]
                            if df_kat_year.empty:
                                st.info(f"Data belum tersedia untuk {int(t_aktif_p)}.")
                            else:
                                donut_data = _donut_grouped(df_kat_year)
                                opts = {
                                    "backgroundColor": "transparent", "color": COLORS,
                                    "tooltip": {"confine": True, "formatter": "{b}: {c}%"},
                                    # Pie digeser ke atas (center Y 38%) & radius diperkecil supaya
                                    # ada ruang tersisa di bawah untuk legend - sebelumnya radius
                                    # 45-70% nyaris memenuhi tinggi container, jadi begitu legend
                                    # wrap ke 2-3 baris (pasti terjadi di layar sempit / mobile),
                                    # legend itu tumpang-tindih dengan bagian bawah donut.
                                    "legend": {"bottom": 4, "left": "center", "textStyle": {"fontSize": 9}, "itemWidth": 10, "itemHeight": 10, "itemGap": 6},
                                    "series": [{"type": "pie", "radius": ["34%", "56%"], "center": ["50%", "38%"], "avoidLabelOverlap": True, "label": {"show": False}, "data": donut_data}],
                                }
                                st_echarts(options=opts, height="360px", key=chart_key, theme=e_theme)
            else:
                st.info("Data distribusi PDRB (sheet Dist_PDRB) belum tersedia.")

            with st.container(border=True):
                panel_title("Nilai PDRB dan Pendapatan Per Kapita Kabupaten Tanah Laut")
                df_disp = df_p[["tahun", "nilai_adhb", "nilai_adhk", "pdptn_perkapita_adhb", "pdptn_perkapita_adhk"]].rename(
                    columns={"tahun": "Tahun", "nilai_adhb": "PDRB ADHB", "nilai_adhk": "PDRB ADHK", "pdptn_perkapita_adhb": "Pendapatan ADHB", "pdptn_perkapita_adhk": "Pendapatan ADHK"}
                )
                render_pdrb_table(df_disp.sort_values("Tahun", ascending=False))

elif kategori == "Pertanian":
    page_header("🌾", "Pertanian", breadcrumb_path)
    with section_guard("Pertanian"):
        df_pt = apply_filter(get_df("Pertanian"), f_tahun)
        df_ntp_src = apply_filter(get_df("Inflasi_NTP"), f_tahun)
        if df_pt.empty:
            st.warning("Data pertanian tidak tersedia untuk rentang ini.")
        else:
            for komoditas_nama, icon in [("Padi", "🌾"), ("Jagung", "🌽")]:
                df_kom = df_pt[df_pt["komoditas"].str.lower() == komoditas_nama.lower()].sort_values("tahun")
                if df_kom.empty:
                    continue
                c1, c2 = st.columns([1.7, 1])
                with c1:
                    with st.container(border=True):
                        panel_title(f"Luas Panen dan Produksi {komoditas_nama}")
                        pt_opts = {
                            "backgroundColor": "transparent", "tooltip": {"trigger": "axis", "confine": True, "axisPointer": {"type": "cross"}, "formatter": FMT_ID},
                            "legend": {"bottom": 0},
                            "xAxis": {"type": "category", "data": df_kom["tahun"].astype(str).tolist()},
                            "yAxis": [{"type": "value", "name": "Ha", "splitLine": {"show": False}}, {"type": "value", "name": "Ton"}],
                            "series": [
                                {"name": "Luas Panen", "type": "bar", "data": df_kom["luas_panen"].tolist(), "itemStyle": {"color": "#BFDBFE", "borderRadius": [4, 4, 0, 0]}},
                                {"name": "Produksi", "type": "line", "yAxisIndex": 1, "data": df_kom["produksi"].tolist(), "itemStyle": {"color": COLORS[2]}, "lineStyle": {"width": 3}},
                            ],
                        }
                        st_echarts(options=pt_opts, height="360px", key=f"pt_{komoditas_nama.lower()}", theme=e_theme)
                with c2:
                    last_kom = df_kom.iloc[-1]
                    prev_kom = df_kom.iloc[-2] if len(df_kom) > 1 else None
                    delta_txt, _ = trend_info(last_kom["produksi"], prev_kom["produksi"] if prev_kom is not None else None)
                    insight_box(
                        f"Interpretasi {komoditas_nama}",
                        f"Produksi {komoditas_nama} pada {int(last_kom['tahun'])} sebesar {fmt_id(last_kom['produksi'])} ton "
                        f"dari luas panen {fmt_id(last_kom['luas_panen'])} Ha." + (f" {delta_txt}." if delta_txt else ""),
                    )
            if not df_ntp_src.empty:
                with st.container(border=True):
                    panel_title("Nilai Tukar Petani (NTP) per Bulan", "Provinsi Kalimantan Selatan")
                    pivot = df_ntp_src.pivot_table(index="bulan", columns="tahun", values="ntp")
                    pivot = pivot.reindex(BULAN_URUT)
                    pivot.loc["RATA-RATA"] = pivot.mean()
                    pivot = pivot.reset_index().rename(columns={"bulan": "Bulan"})
                    pivot.columns = [str(int(c)) if isinstance(c, (int, float, np.integer, np.floating)) else str(c) for c in pivot.columns]
                    render_custom_table(pivot, key="ntp_pivot", page_size=20, variant="yellow")
            else:
                st.info("Data NTP belum tersedia untuk rentang tahun ini.")

_html("<div class='footer-note'>Sumber: BPS Kabupaten Tanah Laut · Data disinkronkan otomatis setiap 1 jam</div>")
