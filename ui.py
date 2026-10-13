"""Visual layer for HelpDeskGenie: an IT operations console look.

Palette (signal colours carry meaning, never decoration):
  ink     #172036  sidebar, headings
  paper   #EEF2F6  page background (cool, not cream)
  panel   #FFFFFF  cards and chat bubbles
  signal  #0E7C70  on / OK / primary action
  amber   #B7791F  pending / waiting
  alarm   #B83A2A  blocked / alert
  slate   #556074  secondary text
Type: Archivo (headings, set tight and heavy) + Source Sans 3 (body).
"""
import html

import streamlit as st

INK, PAPER, PANEL, SIGNAL, AMBER, ALARM, SLATE, LINE = (
    "#172036", "#EEF2F6", "#FFFFFF", "#0E7C70", "#B7791F", "#B83A2A", "#556074", "#D5DCE5")
LAMP = {"ok": "#2BC4AE", "wait": "#E3A33B", "alert": "#E5604C", "off": "#8A94A6"}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=Source+Sans+3:wght@400;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"], [data-testid="stMarkdownContainer"], .stTextInput, .stSelectbox, button {{
  font-family: 'Source Sans 3', system-ui, sans-serif;
}}
[data-testid="stAppViewContainer"] {{ background: {PAPER}; }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}
h1, h2, h3 {{ font-family: 'Archivo', sans-serif !important; color: {INK}; letter-spacing: -0.01em; }}

/* keep the main area readable even if the browser is in dark mode and config.toml is missing */
[data-testid="stMain"], section.main {{ color: {INK}; }}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] p, [data-testid="stMain"] [data-testid="stMarkdownContainer"] li,
section.main [data-testid="stMarkdownContainer"] p, section.main [data-testid="stMarkdownContainer"] li,
[data-testid="stMain"] label, section.main label {{ color: {INK}; }}
[data-testid="stMain"] [data-testid="stCaptionContainer"], section.main [data-testid="stCaptionContainer"] {{ color: {SLATE}; }}
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{ background: {PAPER}; }}

/* sidebar: the console's dark rail */
[data-testid="stSidebar"] {{ background: {INK}; }}
[data-testid="stSidebar"] * {{ color: #E7ECF3; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {{ color: #A9B4C6; }}
[data-testid="stSidebar"] code {{ color: #F4F6F9; background: #26314A; }}
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] input {{ background: #222D45 !important; border-color: #33405C !important; color: #F4F6F9 !important; }}
[data-testid="stSidebar"] [data-baseweb="select"] svg {{ fill: #C9D2DF; }}
[data-testid="stSidebar"] hr {{ border-color: #2C3852; }}
[data-testid="stSidebar"] button {{ background: #222D45; border: 1px solid #33405C; }}
[data-testid="stSidebar"] button:hover {{ border-color: {SIGNAL}; }}
[data-testid="stSidebar"] [data-testid="stExpander"] {{ background: #1D2740; border: 1px solid #2C3852; border-radius: 10px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{ padding: 4px 6px; border-radius: 6px; }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{ background: #24324E; }}

/* brand block */
.hdg-brand {{ display:flex; gap:12px; align-items:center; margin: 4px 0 18px; }}
.hdg-mark {{ width:40px; height:40px; border-radius:10px; background:{SIGNAL}; display:grid; place-items:center;
  font-family:'Archivo',sans-serif; font-weight:800; color:#fff; font-size:18px; }}
.hdg-brand b {{ font-family:'Archivo',sans-serif; font-size:20px; color:#fff; display:block; line-height:1.1; }}
.hdg-brand span {{ font-size:13px; color:#A9B4C6; }}
.hdg-who {{ background:#1D2740; border:1px solid #2C3852; border-radius:10px; padding:10px 12px; margin:6px 0 4px; font-size:14px; }}
.hdg-who b {{ color:#fff; }}
.hdg-pill {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; font-weight:600; margin-left:6px; }}

/* page header */
.hdg-head h1 {{ font-size: 40px; font-weight: 800; margin: 0 0 6px; line-height: 1.05; }}
.hdg-head p {{ color:{SLATE}; font-size:17px; max-width: 70ch; margin:0 0 18px; }}

/* hero + service board (the one bold element) */
.hdg-hero {{ background:{INK}; border-radius:16px; padding:30px 32px 24px; margin-bottom:18px; position:relative; overflow:hidden; }}
.hdg-hero:before {{ content:""; position:absolute; inset:0; background:
  repeating-linear-gradient(90deg, rgba(255,255,255,.035) 0 1px, transparent 1px 56px),
  repeating-linear-gradient(0deg, rgba(255,255,255,.035) 0 1px, transparent 1px 56px); }}
.hdg-hero h1 {{ font-family:'Archivo',sans-serif !important; font-weight:800; font-size:46px; color:#fff !important;
  line-height:1.02; margin:0 0 10px; position:relative; letter-spacing:-0.02em; }}
.hdg-hero p {{ color:#BCC6D6 !important; font-size:18px; max-width:62ch; margin:0 0 22px; position:relative; }}
.hdg-board {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap:1px;
  background:#2C3852; border:1px solid #2C3852; border-radius:12px; overflow:hidden; position:relative; }}
.hdg-cell {{ background:#1B2540; padding:12px 14px; }}
.hdg-cell small {{ color:#93A0B5; font-size:13px; display:block; margin-bottom:4px; }}
.hdg-cell b {{ color:#fff; font-size:16px; font-weight:600; }}
.hdg-lamp {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:8px; vertical-align:1px;
  box-shadow: 0 0 0 3px rgba(255,255,255,.06); }}
@media (prefers-reduced-motion: no-preference) {{
  .hdg-lamp.live {{ animation: hdg-pulse 2.4s ease-in-out 3; }}
  @keyframes hdg-pulse {{ 50% {{ box-shadow: 0 0 0 6px rgba(14,124,112,.25); }} }}
}}

/* quick actions */
.hdg-qa-label {{ color:{SLATE}; font-weight:600; font-size:14px; margin: 6px 0 2px; }}
.stButton > button {{ border-radius:10px; border:1px solid {LINE}; background:{PANEL}; color:{INK};
  font-weight:600; text-align:left; justify-content:flex-start; min-height:44px; }}
.stButton > button:hover {{ border-color:{SIGNAL}; color:{SIGNAL}; }}
.stButton > button:focus-visible {{ outline: 3px solid rgba(14,124,112,.45); outline-offset: 2px; }}
.stButton > button[kind="primary"] {{ background:{SIGNAL}; border-color:{SIGNAL}; color:#fff; }}

/* chat */
[data-testid="stChatMessage"] {{ background:{PANEL}; border:1px solid {LINE}; border-radius:14px; padding:14px 18px; margin-bottom:10px; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]),
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {{ background:#E3E9F1; border-color:#D3DCE7; }}
[data-testid="stChatMessage"] h3 {{ font-size:21px; margin-top:0; }}
[data-testid="stChatMessage"] code {{ background:#EEF2F6; color:{INK}; }}
[data-testid="stChatInput"] {{ border-radius:14px; }}
[data-testid="stChatInput"] textarea {{ font-size:16px; }}

/* metrics, tabs, tables, expanders on the light pages */
[data-testid="stMetric"] {{ background:{PANEL}; border:1px solid {LINE}; border-left:4px solid {SIGNAL}; border-radius:12px; padding:14px 16px; }}
[data-testid="stMetricValue"] {{ font-family:'Archivo',sans-serif; font-weight:800; color:{INK}; }}
[data-testid="stMetricLabel"] p {{ color:{SLATE}; font-weight:600; }}
[data-baseweb="tab-list"] {{ gap: 4px; }}
[data-baseweb="tab"] {{ font-weight:600; }}
[data-testid="stDataFrame"] {{ border:1px solid {LINE}; border-radius:10px; overflow:hidden; background:{PANEL}; }}
.main [data-testid="stExpander"] {{ background:{PANEL}; border:1px solid {LINE}; border-radius:12px; }}
[data-testid="stAlert"] {{ border-radius:12px; }}
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x):
    return html.escape(str(x))


def brand():
    st.sidebar.markdown(
        '<div class="hdg-brand"><div class="hdg-mark">HG</div>'
        '<div><b>HelpDeskGenie</b><span>IT service desk assistant</span></div></div>', unsafe_allow_html=True)


def who(user, is_admin):
    role = ("IT admin", SIGNAL) if user.get("role") == "it_admin" else ("Employee", "#3C4A66")
    lock = (f'<span class="hdg-pill" style="background:{ALARM};color:#fff">Account locked</span>'
            if user.get("locked") else "")
    access = "" if user.get("role") != "it_admin" else (
        f'<span class="hdg-pill" style="background:{SIGNAL};color:#fff">Admin views open</span>' if is_admin
        else f'<span class="hdg-pill" style="background:{AMBER};color:#fff">Passcode needed</span>')
    st.sidebar.markdown(
        f'<div class="hdg-who"><b>{esc(user["name"])}</b>'
        f'<span class="hdg-pill" style="background:{role[1]};color:#fff">{role[0]}</span>{lock}{access}</div>',
        unsafe_allow_html=True)


def header(title, desc=""):
    st.markdown(f'<div class="hdg-head"><h1>{esc(title)}</h1>' + (f"<p>{desc}</p>" if desc else "") + "</div>",
                unsafe_allow_html=True)


def hero(title, desc, cells):
    """cells: [(label, value, state)] where state is ok | wait | alert | off."""
    board = "".join(
        f'<div class="hdg-cell"><small>{esc(label)}</small>'
        f'<b><span class="hdg-lamp{" live" if state == "ok" else ""}" style="background:{LAMP[state]}"></span>{esc(value)}</b></div>'
        for label, value, state in cells)
    st.markdown(f'<div class="hdg-hero"><h1>{esc(title)}</h1><p>{esc(desc)}</p><div class="hdg-board">{board}</div></div>',
                unsafe_allow_html=True)


def label(text):
    st.markdown(f'<div class="hdg-qa-label">{esc(text)}</div>', unsafe_allow_html=True)
