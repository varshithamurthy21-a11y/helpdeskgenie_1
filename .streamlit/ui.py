"""Visual layer for HelpDeskGenie: the "Friendly Help Center" look in sky blue and gold.

Palette
  mist     #F3F9FE  page background
  sky      #CFE9FA  hero banner (sky blue)
  blue     #1E6FA8  links, tabs, pills (white text passes 4.5:1)
  gold     #F2B544  main buttons, accents (navy text on gold)
  navy     #0F3A5F  headings and hero text
  ink      #1B2B3A  body text
  slate    #4A6075  secondary text
  Genie    #7CC8F0 sky blue with gold #F2B544
Type: Sora (headings) + Plus Jakarta Sans (body); deep navy sidebar.
The Genie sticker is an original illustration made for this project.
"""
import html

import streamlit as st

MIST, SKY, BLUE, NAVY, INK, SLATE, LINE, SOFT = (
    "#F3F9FE", "#CFE9FA", "#1E6FA8", "#0F3A5F", "#1B2B3A", "#4A6075", "#CBE3F3", "#E2F1FC")
GOLD, GOLD_DARK = "#F2B544", "#C98A12"
DOT = {"ok": "#1E8A68", "wait": "#C27C0E", "alert": "#C2334D", "off": "#8A9BAA"}

GENIE_SVG = """<svg width="210" height="220" viewBox="0 0 240 250" role="img" aria-label="Genie, the HelpDeskGenie mascot, rising from a golden lamp" style="transform:rotate(-5deg);display:block">
<circle cx="122" cy="128" r="112" fill="#E9B949" opacity=".55"/>
<circle cx="118" cy="122" r="112" fill="#FFFFFF"/>
<circle cx="118" cy="122" r="102" fill="#FFF8E7"/>
<path d="M150 196c-10-24-44-18-40-44 3-20 30-22 30-40" fill="none" stroke="#7CC8F0" stroke-width="22" stroke-linecap="round"/>
<ellipse cx="118" cy="204" rx="56" ry="18" fill="#E9A83A"/>
<path d="M62 200c0-16 25-26 56-26s56 10 56 26z" fill="#F2B544"/>
<path d="M172 194c14-2 24-10 30-20" fill="none" stroke="#F2B544" stroke-width="10" stroke-linecap="round"/>
<path d="M66 196c-14 0-20-14-10-22" fill="none" stroke="#E9A83A" stroke-width="7" stroke-linecap="round"/>
<ellipse cx="118" cy="172" rx="14" ry="6" fill="#E9A83A"/>
<ellipse cx="140" cy="112" rx="34" ry="28" fill="#7CC8F0"/>
<path d="M110 108c-14-6-26-2-30 8" fill="none" stroke="#7CC8F0" stroke-width="12" stroke-linecap="round"/>
<circle cx="78" cy="118" r="9" fill="#7CC8F0"/>
<path d="M168 104c12-10 18-24 14-36" fill="none" stroke="#7CC8F0" stroke-width="12" stroke-linecap="round"/>
<circle cx="183" cy="64" r="9" fill="#7CC8F0"/>
<path d="M108 128c20 8 44 8 64-2" fill="none" stroke="#F2B544" stroke-width="7" stroke-linecap="round"/>
<circle cx="86" cy="113" r="5" fill="none" stroke="#F2B544" stroke-width="4"/>
<circle cx="179" cy="72" r="5" fill="none" stroke="#F2B544" stroke-width="4"/>
<circle cx="140" cy="66" r="30" fill="#A8DCF7"/>
<circle cx="111" cy="74" r="3.5" fill="#F2B544"/>
<path d="M110 58c2-24 58-26 60 0z" fill="#F2B544"/>
<path d="M112 56c10-10 46-10 56 0" fill="none" stroke="#E9A83A" stroke-width="5"/>
<circle cx="140" cy="44" r="7" fill="#2F7FC1"/>
<path d="M140 30c4-8 12-10 16-6" fill="none" stroke="#F2B544" stroke-width="5" stroke-linecap="round"/>
<ellipse cx="129" cy="70" rx="4" ry="5" fill="#2C2140"/>
<ellipse cx="151" cy="70" rx="4" ry="5" fill="#2C2140"/>
<circle cx="122" cy="80" r="5" fill="#F4A3C0"/>
<circle cx="158" cy="80" r="5" fill="#F4A3C0"/>
<path d="M130 82c5 7 15 7 20 0" fill="none" stroke="#2C2140" stroke-width="3.5" stroke-linecap="round"/>
<path d="M56 60l4 10 10 4-10 4-4 10-4-10-10-4 10-4z" fill="#F2B544"/>
<path d="M196 132l3 7 7 3-7 3-3 7-3-7-7-3 7-3z" fill="#F2B544"/>
<path d="M74 150l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" fill="#1E6FA8"/>
</svg>"""

LOGO_SVG = ('<svg width="40" height="40" viewBox="0 0 44 44" aria-hidden="true"><rect width="44" height="44" rx="14" fill="#1E6FA8"/>'
            '<path d="M12 27c4 0 6-3 10-3s6 3 10 3M17 19a2 2 0 1 0 0 .1M27 19a2 2 0 1 0 0 .1" stroke="#F2B544" stroke-width="3" '
            'stroke-linecap="round" fill="none"/></svg>')

CSS = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap">
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

/* modern type everywhere (icons keep their own font) */
html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp button,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-baseweb="select"], .stApp [data-baseweb="tab"], .stApp th, .stApp td {{
  font-family: 'Plus Jakarta Sans', 'Inter', system-ui, sans-serif !important;
  -webkit-font-smoothing: antialiased; }}
.stApp [data-testid="stIconMaterial"], .stApp .material-symbols-rounded {{ font-family: 'Material Symbols Rounded' !important; }}
h1, h2, h3, h4, .hdg-label, .hdg-brand b, .hdg-bubble, [data-testid="stMetricValue"] {{
  font-family: 'Sora', 'Plus Jakarta Sans', sans-serif !important; letter-spacing: -0.02em; }}
h1, h2, h3 {{ color: {NAVY} !important; font-weight: 600 !important; }}

/* page: soft sky glow with a hint of gold */
[data-testid="stAppViewContainer"] {{
  background: radial-gradient(900px 420px at 92% -8%, #D6ECFB 0%, rgba(214,236,251,0) 60%),
              radial-gradient(700px 360px at 8% 0%, #FFF3D6 0%, rgba(255,243,214,0) 55%), {MIST}; }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 2rem; max-width: 1160px; }}

/* readable even when the browser is in dark mode */
[data-testid="stMain"], section.main {{ color: {INK}; }}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] p, [data-testid="stMain"] [data-testid="stMarkdownContainer"] li,
section.main [data-testid="stMarkdownContainer"] p, section.main [data-testid="stMarkdownContainer"] li,
[data-testid="stMain"] label, section.main label {{ color: {INK}; }}
[data-testid="stMain"] [data-testid="stCaptionContainer"], section.main [data-testid="stCaptionContainer"] {{ color: {SLATE}; }}
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{ background: transparent; }}

/* sidebar: deep navy panel with gold highlights */
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, #0B2540 0%, #12395F 100%); border-right: 0; }}
[data-testid="stSidebar"] * {{ color: #E6F1FB; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {{ color: #9DB7CF; }}
[data-testid="stSidebar"] label p {{ color: #9DB7CF !important; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; }}
[data-testid="stSidebar"] [role="radiogroup"] label p {{ color: #E6F1FB !important; font-size: 15px; text-transform: none; letter-spacing: 0; font-weight: 500; }}
[data-testid="stSidebar"] [data-baseweb="select"] > div, [data-testid="stSidebar"] input {{
  background: rgba(255,255,255,.08) !important; border: 1px solid rgba(255,255,255,.14) !important; border-radius: 12px !important; color: #fff !important; }}
[data-testid="stSidebar"] [data-baseweb="select"] svg {{ fill: #9DB7CF; }}
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 4px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{ padding: 9px 12px; border-radius: 12px; width: 100%; transition: background .15s; }}
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{ display: none; }}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: rgba(255,255,255,.06); }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: linear-gradient(90deg, rgba(242,181,68,.22), rgba(242,181,68,.04)); box-shadow: inset 3px 0 0 {GOLD}; }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: #fff !important; font-weight: 700; }}
[data-testid="stSidebar"] [data-testid="stExpander"] {{ background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12); border-radius: 16px; }}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{ background: transparent; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.12); }}
[data-testid="stSidebar"] .stButton > button {{ background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.14); box-shadow: none; min-height: 40px; }}
[data-testid="stSidebar"] .stButton > button:hover {{ background: rgba(242,181,68,.18); border-color: {GOLD}; }}
[data-testid="stSidebar"] code {{ background: rgba(242,181,68,.18); color: #FFD98A; }}

.hdg-brand {{ display:flex; gap:12px; align-items:center; margin: 4px 0 18px; }}
.hdg-brand b {{ font-weight:700; font-size:21px; color:#fff !important; display:block; line-height:1.15; }}
.hdg-brand span {{ font-size:12.5px; color:#9DB7CF !important; }}
.hdg-who {{ background: rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.12); border-radius:16px; padding:12px 14px; margin:8px 0 10px; font-size:14px; }}
.hdg-who b {{ color:#fff !important; font-weight:700; }}
.hdg-pill {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:11.5px; font-weight:700; margin:6px 4px 0 0; letter-spacing:.02em; }}

/* page header */
.hdg-head h1 {{ font-size: 36px; margin: 0 0 6px; line-height: 1.15; }}
.hdg-head p {{ color:{SLATE}; font-size:16.5px; max-width: 70ch; margin:0 0 18px; }}

/* hero banner with Genie */
.hdg-hero {{ background: linear-gradient(135deg, {SKY} 0%, #EAF5FE 70%, #FFF6E0 100%); border: 1px solid rgba(255,255,255,.8);
  border-radius:28px; padding:28px 32px; display:flex; flex-wrap:wrap; align-items:center; gap:18px; margin-bottom:16px;
  box-shadow: 0 24px 48px -28px rgba(30,111,168,.45); }}
.hdg-hero-text {{ flex: 1 1 360px; min-width: 0; }}
.hdg-eyebrow {{ display:inline-flex; align-items:center; gap:6px; background:#fff; color:#8A5A00; border:1px solid #F5D58E;
  border-radius:999px; padding:4px 12px; font-size:12.5px; font-weight:700; letter-spacing:.04em; margin-bottom:12px; }}
.hdg-hero h1 {{ font-size:40px; line-height:1.12; margin:0 0 10px; font-weight:700 !important;
  background: linear-gradient(90deg, {NAVY} 0%, {BLUE} 100%); -webkit-background-clip: text; background-clip: text; color: transparent !important; }}
.hdg-hero p {{ color:#2D5576 !important; font-size:17px; max-width:48ch; margin:0 0 16px; line-height:1.55; }}
.hdg-genie {{ flex: 0 0 220px; display:flex; flex-direction:column; align-items:center; gap:4px; }}
.hdg-bubble {{ background:#fff; border:2px solid {GOLD}; color:{NAVY}; font-weight:600; font-size:16px;
  padding:7px 14px; border-radius:16px 16px 16px 4px; transform:rotate(-3deg); }}
.hdg-chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
.hdg-chip {{ background:rgba(255,255,255,.8); border:1px solid rgba(30,111,168,.12); color:{NAVY}; border-radius:999px; padding:6px 12px; font-size:13px; font-weight:600; }}
.hdg-chip i {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:7px; vertical-align:1px; }}
@media (prefers-reduced-motion: no-preference) {{
  .hdg-genie svg {{ animation: hdg-float 3.2s ease-in-out 2; }}
  @keyframes hdg-float {{ 50% {{ transform: rotate(-5deg) translateY(-6px); }} }}
}}

.hdg-label {{ display:inline-block; font-weight:600; font-size:19px; color:{NAVY}; margin: 10px 0 8px;
  border-bottom:3px solid {GOLD}; padding-bottom:2px; }}

/* buttons: topic tiles and actions */
.stButton > button {{ border-radius:16px; border:1px solid #DCEBF6; background:#fff; color:{INK}; font-weight:600;
  box-shadow: 0 6px 18px -12px rgba(15,58,95,.35); min-height:52px; justify-content:flex-start; text-align:left; padding: 10px 16px;
  transition: transform .15s, box-shadow .15s, border-color .15s; }}
.stButton > button:hover {{ border-color:{GOLD}; color:{NAVY}; transform: translateY(-2px); box-shadow: 0 12px 24px -14px rgba(15,58,95,.45); }}
.stButton > button:focus-visible {{ outline:3px solid rgba(30,111,168,.45); outline-offset:2px; }}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] button {{
  background: linear-gradient(135deg, #F7C65C, {GOLD}); color:{NAVY}; border:0; box-shadow: 0 8px 18px -10px rgba(201,138,18,.8); }}
.stButton > button[kind="primary"]:hover {{ background: linear-gradient(135deg, #F2B544, #E5A630); color:{NAVY}; }}
.stButton > button span[data-testid="stIconMaterial"] {{ color:{GOLD_DARK}; }}

/* chat */
[data-testid="stChatMessage"] {{ background:#fff; border:1px solid #E3EFF8; border-radius:22px 22px 22px 6px; padding:14px 18px; margin-bottom:10px;
  box-shadow: 0 8px 20px -16px rgba(15,58,95,.35); }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]),
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {{ background:{SOFT}; border-color:transparent; border-radius:22px 22px 6px 22px; box-shadow:none; }}
[data-testid="stChatMessage"] h3 {{ font-size:20px; margin-top:0; }}
[data-testid="stChatMessage"] code {{ background:{MIST}; color:{NAVY}; }}
[data-testid="stChatInput"] {{ border-radius:18px; border: 1px solid #CFE3F2; background:#fff; box-shadow: 0 10px 28px -18px rgba(15,58,95,.45); }}
[data-testid="stChatInput"]:focus-within {{ border-color: {GOLD}; }}

/* metrics, tables, tabs, alerts */
[data-testid="stMetric"] {{ background:#fff; border:1px solid #E3EFF8; border-radius:20px; padding:14px 18px; box-shadow: 0 8px 20px -16px rgba(15,58,95,.35); border-top:3px solid {GOLD}; }}
[data-testid="stMetricValue"] {{ font-weight:600; color:{NAVY}; }}
[data-testid="stMetricLabel"] p {{ color:{SLATE}; font-weight:600; }}
[data-baseweb="tab"] {{ font-weight:600; }}
[data-baseweb="tab-highlight"] {{ background-color:{GOLD}; }}
[data-testid="stDataFrame"] {{ border-radius:14px; overflow:hidden; background:#fff; }}
[data-testid="stMain"] [data-testid="stExpander"], section.main [data-testid="stExpander"] {{ background:#fff; border:1px solid {LINE}; border-radius:18px; }}
[data-testid="stAlert"] {{ border-radius:16px; }}
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x):
    return html.escape(str(x))


def brand():
    st.sidebar.markdown(f'<div class="hdg-brand">{LOGO_SVG}<div><b>HelpDeskGenie</b>'
                        '<span>Your friendly IT help desk</span></div></div>', unsafe_allow_html=True)


def who(user, is_admin):
    pills = []
    if user.get("role") == "it_admin":
        pills.append(("IT admin", BLUE, "#fff"))
        pills.append(("Admin views open", "#1E8A68", "#fff") if is_admin else ("Passcode needed", "#C27C0E", "#fff"))
    else:
        pills.append(("Employee", "rgba(124,200,240,.22)", "#CFE9FA"))
    if user.get("locked"):
        pills.append(("Account locked", "#C2334D", "#fff"))
    chips = "".join(f'<span class="hdg-pill" style="background:{bg};color:{fg}">{esc(t)}</span>' for t, bg, fg in pills)
    st.sidebar.markdown(f'<div class="hdg-who"><b>{esc(user["name"])}</b><br>{chips}</div>', unsafe_allow_html=True)


def header(title, desc=""):
    st.markdown(f'<div class="hdg-head"><h1>{esc(title)}</h1>' + (f"<p>{desc}</p>" if desc else "") + "</div>",
                unsafe_allow_html=True)


def hero(title, desc, chips):
    """chips: [(label, value, state)] with state ok | wait | alert | off."""
    chip_html = "".join(f'<span class="hdg-chip"><i style="background:{DOT[s]}"></i>{esc(l)}: {esc(v)}</span>'
                        for l, v, s in chips)
    st.markdown(
        f'<div class="hdg-hero"><div class="hdg-hero-text"><div class="hdg-eyebrow">✦ AI-powered IT assistant</div><h1>{esc(title)}</h1><p>{esc(desc)}</p>'
        f'<div class="hdg-chips">{chip_html}</div></div>'
        f'<div class="hdg-genie"><div class="hdg-bubble">Hi, I\'m Genie!</div>{GENIE_SVG}</div></div>',
        unsafe_allow_html=True)


def label(text):
    st.markdown(f'<div class="hdg-label">{esc(text)}</div>', unsafe_allow_html=True)
