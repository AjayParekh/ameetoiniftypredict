import streamlit as st
import requests
import pandas as pd
from datetime import datetime, time
import datetime as dt_mod
import os
import pytz
from streamlit_autorefresh import st_autorefresh
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import warnings
warnings.filterwarnings('ignore')
import json
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# --- Reversal Meter: optional Plotly import ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except Exception:
    PLOTLY_AVAILABLE = False

# --- Fragment availability (Streamlit >= 1.37 preferred) ---
if hasattr(st, "fragment"):
    _frag = st.fragment
    _FRAGMENT_SUPPORTED = True
elif hasattr(st, "experimental_fragment"):
    _frag = st.experimental_fragment
    _FRAGMENT_SUPPORTED = True
else:
    _frag = None
    _FRAGMENT_SUPPORTED = False

access_token = 'Bearer eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIxMDM2NjciLCJqdGkiOiI2OWQyMzJlMWNjZDUyZDRjZDQzMzc5NjYiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc3NTM4MzI2NSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODA2OTYyNDAwfQ.VFRZ5NP87NM1Vyn4-bCB2FAvanu4wsueNHo_POQtPv8'

# ==============================
# DEFAULT HARDCODED SETTINGS
# ==============================
w_gift = 0.35
w_sgx = 0.25
w_nasdaq = 0.15
w_dax = 0.10
w_dxy = -0.10
w_usdinr = -0.10
w_hangseng = 0.05

vix_threshold = 20.0
vix_dampener = 0.5
india_vix_threshold = 25.0
india_vix_dampener = 0.5

# ==============================
# PAGE CONFIG
# ==============================
if "page_config_done" not in st.session_state:
    st.set_page_config(
        page_title="Nifty Strategy & Predictor Pro",
        page_icon="🔮",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    st.session_state.page_config_done = True

# ==============================
# STYLES
# ==============================
st.markdown("""
    <style>
    .main { background-color: #f4f7f9; }
    .market-box { background-color: white; padding: 18px; border-radius: 12px;
        border: 1px solid #e1e4e8; box-shadow: 0px 4px 10px rgba(0,0,0,0.03);
        margin-bottom: 15px; }
    .prediction-box { background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
        color: white; padding: 20px; border-radius: 15px; text-align: center;
        margin-bottom: 15px; position: relative; }
    .prediction-achieved { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%) !important; }
    .confidence-tag { background: rgba(255,255,255,0.2); padding: 4px 12px;
        border-radius: 20px; font-size: 0.9rem; font-weight: bold;
        display: inline-block; margin-top: 10px; border: 1px solid rgba(255,255,255,0.3); }
    .divergence-alert { background-color: #f8d7da; color: #721c24; padding: 12px 20px;
        border-radius: 10px; border-left: 5px solid #dc3545; margin-bottom: 20px;
        font-weight: bold; font-size: 1.05rem; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    .vix-alert { background-color: #fff3cd; color: #856404; padding: 10px 20px;
        border-radius: 10px; border-left: 5px solid #ffc107; margin-bottom: 15px;
        font-weight: bold; }
    .status-badge { position: absolute; top: 10px; right: 15px;
        background: rgba(255,255,255,0.25); color: white; padding: 2px 10px;
        border-radius: 8px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
    .prediction-card { padding: 30px; border-radius: 20px; text-align: center;
        color: white; margin-bottom: 15px; position: relative; }
    .bullish  { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .bearish  { background: linear-gradient(135deg, #cb2d3e 0%, #ef473a 100%); }
    .weak-bullish { background: linear-gradient(135deg, #2d6a4f 0%, #52b788 100%); }
    .weak-bearish { background: linear-gradient(135deg, #7b2d00 0%, #c05c2a 100%); }
    .neutral  { background: linear-gradient(135deg, #2c3e50 0%, #4ca1af 100%); }
    .price-large { font-size: 2.8rem; font-weight: 800; margin: 10px 0; }
    .move-text { font-size: 1.5rem; font-weight: 600; margin-bottom: 10px; opacity: 0.9; }
    .sl-badge  { font-size: 1.2rem; font-weight: 700; background: rgba(0,0,0,0.2);
                 padding: 8px 20px; border-radius: 10px; display: inline-block;
                 margin-top: 10px; border: 1px solid rgba(255,255,255,0.3); }
    .market-header { display: flex; justify-content: space-between; align-items: center;
                     border-bottom: 1px solid #eee; padding-bottom: 8px; margin-bottom: 10px; }
    .market-name  { font-weight: 700; font-size: 1.1rem; color: #1a1a1a; }
    .price-row    { display: flex; justify-content: space-between; align-items: baseline; }
    .price-value  { font-size: 1.5rem; font-weight: 800; color: #1a1a1a; }
    .change-value { font-size: 1rem; font-weight: 600; }
    .positive, .pos { color: #00873c; font-weight: bold; }
    .negative, .neg { color: #eb4444; font-weight: bold; }
    .neutral-color  { color: #6e7781; }
    .signal-score-bar { background: rgba(255,255,255,0.15); border-radius: 8px;
        padding: 8px 16px; margin-top: 10px; font-size: 0.95rem; display: inline-block; }
    .indicator-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
    .indicator-pill { padding: 4px 12px; border-radius: 20px; font-size: 0.8rem;
        font-weight: 600; border: 1px solid rgba(0,0,0,0.08); }
    .pill-green  { background:#d4edda; color:#155724; }
    .pill-red    { background:#f8d7da; color:#721c24; }
    .pill-yellow { background:#fff3cd; color:#856404; }
    .pill-gray   { background:#e9ecef; color:#495057; }
    .momentum-badge { display: inline-block; padding: 3px 12px; border-radius: 15px;
        font-size: 0.8rem; font-weight: bold; margin-left: 8px; }
    .entry-box { padding: 15px 20px; border-radius: 12px; margin-bottom: 20px;
        color: #000000; border-left: 6px solid; }
    .entry-box .status-badge-dark { background: rgba(0,0,0,0.6); color: white;
        padding: 2px 10px; border-radius: 8px; font-size: 0.75rem;
        font-weight: bold; text-transform: uppercase; margin-left: 10px; }
    .entry-box .status-text { font-weight: bold; }
    .greeks-panel { background: white; padding: 12px 18px; border-radius: 10px;
        border-left: 5px solid; margin-bottom: 15px; color: #000; }
    .greeks-panel .badge-pass { background-color: #2e7d32; color: white;
        padding: 2px 10px; border-radius: 12px; font-weight: bold; font-size: 0.8rem; }
    .greeks-panel .badge-weak { background-color: #f9a825; color: #000;
        padding: 2px 10px; border-radius: 12px; font-weight: bold; font-size: 0.8rem; }
    .greeks-panel .greek-item { display: inline-block; margin-right: 20px; font-size: 0.9rem; }
    .greeks-panel .greek-item b { color: #1a1a1a; }
    /* Reversal Meter */
    .rev-card { background: white; padding: 14px 18px; border-radius: 12px;
        border-left: 5px solid; margin-bottom: 12px; color: #000;
        box-shadow: 0px 2px 6px rgba(0,0,0,0.04); }
    .rev-card .rev-title { font-weight: 800; font-size: 1.05rem; margin-bottom: 6px; }
    .rev-card .rev-sub   { font-size: 0.85rem; color: #555; }
    .rev-pill { display: inline-block; padding: 2px 10px; border-radius: 12px;
        font-size: 0.78rem; font-weight: 700; margin-left: 6px; }
    .rev-pill-green  { background:#d4edda; color:#155724; }
    .rev-pill-red    { background:#f8d7da; color:#721c24; }
    .rev-pill-yellow { background:#fff3cd; color:#856404; }
    .rev-pill-gray   { background:#e9ecef; color:#495057; }
    .rev-alert-item { padding: 8px 12px; border-radius: 8px; margin-bottom: 6px;
        font-size: 0.86rem; border-left: 4px solid; color: #000000; }
    .rev-alert-bear { background:#fdecea; border-color:#c62828; }
    .rev-alert-bull { background:#e8f5e9; border-color:#2e7d32; }
    .rev-alert-neutral { background:#f1f3f5; border-color:#6c757d; }
    </style>
""", unsafe_allow_html=True)

def inr_format(num):
    s = str(num)
    if len(s) <= 3:
        return s
    last_three = s[-3:]
    remaining = s[:-3]
    parts = []
    while len(remaining) > 2:
        parts.insert(0, remaining[-2:])
        remaining = remaining[:-2]
    if remaining:
        parts.insert(0, remaining)
    return ",".join(parts + [last_three])

# Auto date (today, IST) and auto weekly expiry
ist_now = datetime.now(pytz.timezone("Asia/Kolkata"))
today_str = ist_now.strftime('%Y-%m-%d')

days_until_tuesday = (1 - ist_now.weekday()) % 7
expiry_date = ist_now + dt_mod.timedelta(days=days_until_tuesday)
expiry_str = expiry_date.strftime('%Y-%m-%d')

@st.cache_data(ttl=1800)
def get_nearest_expiry(instrument_key, fallback_str, today_key):
    try:
        r = requests.get(
            'https://api.upstox.com/v2/option/contract',
            params={'instrument_key': instrument_key},
            headers={'Accept': 'application/json', 'Authorization': access_token},
            timeout=10
        )
        d = json.loads(r.text)
        expiries = sorted({c.get('expiry') for c in (d.get('data') or []) if c.get('expiry')})
        upcoming = [e for e in expiries if e >= today_key]
        if upcoming:
            return upcoming[0]
    except Exception:
        pass
    return fallback_str

expiry_str = get_nearest_expiry('NSE_INDEX|Nifty 50', expiry_str, today_str)

# ==============================
# RAW UPSTOX FETCHERS (parameterised so they can be cached)
# ==============================
def _fetch_change_oi_raw(instrument_key, expiry, date, interval=2):
    url = 'https://api.upstox.com/v2/market/change-oi'
    params = {'instrument_key': instrument_key, 'expiry': expiry, 'date': date, 'interval': interval}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'Authorization': access_token}
    r = requests.get(url, params=params, headers=headers, timeout=6)
    return json.loads(r.text)

def _fetch_oi_raw(instrument_key, expiry, date):
    url = 'https://api.upstox.com/v2/market/oi'
    params = {'instrument_key': instrument_key, 'expiry': expiry, 'date': date}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'Authorization': access_token}
    r = requests.get(url, params=params, headers=headers, timeout=6)
    return json.loads(r.text)

def _fetch_spot_raw():
    try:
        r = requests.get(
            'https://api.upstox.com/v2/market-quote/quotes',
            params={'instrument_key': 'NSE_INDEX|Nifty 50'},
            headers={'Accept': 'application/json', 'Authorization': access_token},
            timeout=4
        )
        d = json.loads(r.text)
        if d.get("status") != "success":
            return None
        for k, v in (d.get("data") or {}).items():
            lp = v.get("last_price")
            if lp:
                return float(lp)
    except Exception as e:
        print(f"spot fetch error: {e}")
    return None

# Cached wrappers — TTL=4 s so fragment (5 s cadence) always gets fresh data
@st.cache_data(ttl=4, show_spinner=False)
def _sampled_change_oi(instrument_key, expiry, date):
    return _fetch_change_oi_raw(instrument_key, expiry, date)

@st.cache_data(ttl=4, show_spinner=False)
def _sampled_oi(instrument_key, expiry, date):
    return _fetch_oi_raw(instrument_key, expiry, date)

@st.cache_data(ttl=4, show_spinner=False)
def _sampled_spot():
    return _fetch_spot_raw()

# Original fetchers (used by main flow — preserved as-is, no behavioural change)
def fetch_upstox_oi_change_data():
    return _fetch_change_oi_raw('NSE_INDEX|Nifty 50', expiry_str, today_str, interval=2)

def fetch_upstox_oi_data():
    return _fetch_oi_raw('NSE_INDEX|Nifty 50', expiry_str, today_str)

upstoxOiChangeResponse = fetch_upstox_oi_change_data()
upstoxOiResponse = fetch_upstox_oi_data()
data = upstoxOiResponse["data"]

# ==============================
# OPTION CHAIN + GREEKS
# ==============================
def fetch_option_chain(instrument_key, expiry_date):
    url = 'https://api.upstox.com/v2/option/chain'
    params = {'instrument_key': instrument_key, 'expiry_date': expiry_date}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'Authorization': access_token}
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

def parse_greeks_by_strike(option_chain_response):
    greeks_map = {}
    if option_chain_response.get("status") != "success":
        return greeks_map
    for item in option_chain_response.get("data", []):
        strike = item.get("strike_price")
        if strike is None:
            continue
        call_g = (item.get("call_options") or {}).get("option_greeks") or {}
        put_g  = (item.get("put_options")  or {}).get("option_greeks") or {}
        greeks_map[strike] = {
            "call_delta": call_g.get("delta", 0), "call_gamma": call_g.get("gamma", 0),
            "call_theta": call_g.get("theta", 0), "call_vega":  call_g.get("vega", 0),
            "call_iv":    call_g.get("iv", 0),
            "put_delta":  put_g.get("delta", 0),  "put_gamma":  put_g.get("gamma", 0),
            "put_theta":  put_g.get("theta", 0),  "put_vega":   put_g.get("vega", 0),
            "put_iv":     put_g.get("iv", 0),
        }
    return greeks_map

def compute_greeks_confidence(entry_type, greeks):
    if not greeks:
        return 40.0, True, ["⚪ No Greeks data — falling back to OI-only confidence"]
    notes = []
    if entry_type == "HIGH PUT":
        delta = abs(greeks.get("put_delta", 0)); gamma = greeks.get("put_gamma", 0)
        theta = greeks.get("put_theta", 0); iv = greeks.get("put_iv", 0)
    else:
        delta = abs(greeks.get("call_delta", 0)); gamma = greeks.get("call_gamma", 0)
        theta = greeks.get("call_theta", 0); iv = greeks.get("call_iv", 0)
    delta_ok = 0.15 <= delta <= 0.75
    notes.append(f"{'✅' if delta_ok else '⚠️'} Delta {delta:.2f} {'in' if delta_ok else 'outside'} relevant band (0.15–0.75)")
    delta_score = max(0, 100 - abs(delta - 0.45) * 150)
    gamma_score = min(100, gamma * 5000)
    theta_penalty = min(30, max(0, -theta))
    if theta < -5:
        notes.append(f"🔥 Theta {theta:.2f}/day — fast premium decay if trading the option itself")
    if iv:
        notes.append(f"📈 IV: {iv:.1f}%")
    confidence = round(max(0, min(100, 0.55 * delta_score + 0.35 * gamma_score - 0.10 * theta_penalty)), 1)
    return confidence, delta_ok, notes

nifty_option_chain_response = fetch_option_chain('NSE_INDEX|Nifty 50', expiry_str)
nifty_greeks_by_strike = parse_greeks_by_strike(nifty_option_chain_response)

def reusable_display_oi_data(upstoxResponse, title):
    if not upstoxResponse or not upstoxResponse.get("data"):
        st.subheader(title)
        st.info("ℹ️ No data available right now (market closed or data not yet published).")
        return
    data = upstoxResponse["data"]
    Total_Puts = 0
    Total_Calls = 0

    def get_oi_value(item, key1, key2, format_num=0):
        value = item.get(key1) if item.get(key1) is not None else item.get(key2)
        return inr_format(value) if format_num else value

    def get_high_oi(item):
        nonlocal Total_Calls, Total_Puts
        if get_oi_value(item, 'put_oi', 'put_change_oi') > get_oi_value(item, 'call_oi', 'call_change_oi'):
            Total_Puts += 1
            return "HIGH PUT"
        else:
            Total_Calls += 1
            return "HIGH CALL"

    oi_rows = [
        {
            "Strike Price": int(item["strike_price"]),
            "Call OI": get_oi_value(item, 'call_oi', 'call_change_oi', format_num=1),
            "Put OI": get_oi_value(item, 'put_oi', 'put_change_oi', format_num=1),
            "HIGH OI": get_high_oi(item),
            "OI Difference": abs(get_oi_value(item, 'put_oi', 'put_change_oi') - get_oi_value(item, 'call_oi', 'call_change_oi')),
        }
        for item in data["call_put_oi_data_list"]
    ]

    oi_header = [{
        "Status": upstoxResponse["status"],
        "Total Puts": get_oi_value(data, 'total_puts', 'total_put_change_oi', format_num=1),
        "Total Calls": get_oi_value(data, 'total_calls', 'total_call_change_oi', format_num=1),
        "Spot Closing Price": data.get('spot_closing_price'),
        "Expiry": data.get('expiry'),
        "Total Call OI": Total_Calls,
        "Total Put OI": Total_Puts
    }]

    st.subheader(title)
    st.dataframe(pd.DataFrame(oi_header))

    top_20 = pd.DataFrame(oi_rows).sort_values(
        by="OI Difference", ascending=False
    ).head(20).reset_index(drop=True)

    def highlight_top5(row):
        if row.name < 5:
            return ["background-color: #ffd700; font-weight: bold; color: #000000;"] * len(row)
        return [""] * len(row)

    st.dataframe(top_20.style.apply(highlight_top5, axis=1))

# ==============================
# GLOBAL CONFIG & TIMING
# ==============================
ist = pytz.timezone("Asia/Kolkata")
now = datetime.now(ist)
today = now.strftime("%Y-%m-%d")
CHINA_CLOSE_TIME = time(12, 30)
is_after_china = now.time() >= CHINA_CLOSE_TIME
excel_file = "Market_Data.xlsx"

# ==============================
# SIDEBAR
# ==============================
with st.sidebar:
    st.title("🎯 Predictor Settings")
    st.sidebar.markdown(f"### 🕒 IST: {now.strftime('%H:%M:%S')}")
    st.markdown("---")

    st.markdown("#### ⚡ Refresh Cadence")
    refresh_sec = st.slider("Main page refresh (sec)", 5, 60, 15, 1, key="page_refresh_sec",
                            help="Whole-page rerun interval. Reversal Meter uses a faster "
                                 "independent 5-second sampler underneath.")
    st.caption(f"🔁 Reversal sampler: **5 s** (independent). "
               f"Fragment API: {'✅ available' if _FRAGMENT_SUPPORTED else '⚠️ not available — will run at page cadence'}")

    st.markdown("---")
    st.markdown("#### 🚀 Momentum Settings")
    momentum_lookback = st.slider("Momentum Lookback (min)", 5, 30, 15, 5, key="mom_lookback")
    momentum_threshold = st.slider("Momentum Threshold %", 0.1, 0.5, 0.25, 0.05, key="mom_thresh")

    st.markdown("---")
    st.markdown("#### 🛡️ Entry Confirmation Gate")
    gate_hold_min     = st.slider("Signal must hold (min)", 0, 30, 5, 1, key="gate_hold")
    gate_price_min    = st.slider("Price beyond trigger for (min)", 0, 15, 3, 1, key="gate_price")
    gate_min_score    = st.slider("Min futures score to agree", 0.0, 0.9, 0.2, 0.05, key="gate_score")
    gate_min_dom      = st.slider("Strike dominance (x vs next)", 1.0, 3.0, 1.3, 0.1, key="gate_dom")
    gate_max_dist_pct = st.slider("Max strike distance from spot %", 0.5, 5.0, 2.0, 0.5, key="gate_dist")
    gate_sl_buffer    = st.slider("Stop-loss buffer beyond strike (pts)", 5, 100, 20, 5, key="gate_sl")
    gate_time_filter  = st.checkbox("Block opening 15 min & last 30 min", value=True, key="gate_time")
    gate_use_futures  = st.checkbox("Require futures score agreement", value=True, key="gate_use_fut")

    st.markdown("---")
    st.markdown("#### 🧭 OI Flip Meter")
    meter_window_strikes = st.slider("Strikes each side of spot", 2, 12, 6, 1, key="meter_win")
    meter_flip_threshold = st.slider("Flip strength threshold (±)", 10, 60, 20, 5, key="meter_thr")
    meter_flip_lookback  = st.slider("Flip look-back / validity (min)", 10, 90, 30, 5, key="meter_look")
    gate_flip_override   = st.checkbox("Confirmed OI flip overrides hold-time, opening window & opposite locked signal",
                                       value=True, key="gate_flip_ovr")
    if st.button("🔄 Reset locked signals", key="gate_reset"):
        for _k in [k for k in list(st.session_state.keys()) if str(k).startswith("gate_state_")]:
            del st.session_state[_k]

    st.markdown("---")
    st.markdown("#### 🔄 Change-in-OI Reversal Meter")
    rev_enabled          = st.checkbox("Enable Reversal Meter", value=True, key="rev_enabled")
    rev_window_strikes   = st.slider("Strikes each side of ATM", 3, 25, 10, 1, key="rev_win")
    rev_lookback         = st.slider("Anomaly baseline (snapshots)", 3, 30, 6, 1, key="rev_look")
    rev_z_threshold      = st.slider("Anomaly Z-threshold", 1.0, 4.0, 2.0, 0.1, key="rev_z")
    rev_min_abs_lakh     = st.slider("Min abs change (lakh contracts)", 1, 200, 5, 1, key="rev_minabs")
    rev_cooldown_min     = st.slider("Alert cooldown (minutes)", 1, 30, 5, 1, key="rev_cool")
    if st.button("🧹 Clear reversal snapshots", key="rev_clear"):
        for _k in ["rev_snapshots", "rev_alerts", "rev_cooldowns"]:
            st.session_state.pop(_k, None)

    if is_after_china:
        st.sidebar.success("China Logic: ACTIVE")
    else:
        st.sidebar.warning("Waiting for 12:30 PM IST")

# ==============================
# Register autorefresh AFTER sidebar so it uses the chosen interval
# ==============================
st_autorefresh(interval=refresh_sec * 1000, key=f"global_sync_refresh_{refresh_sec}")

# ==============================
# MASTER INSTRUMENT LIST
# ==============================
master_symbols = [
    {"market": "India",      "name": "NIFTY 50",    "tv_symbol": "NSE:NIFTY",        "start": "09:15", "end": "15:30", "icon": "🇮🇳", "w": 0,          "trigger_alignment": False, "category": "india"},
    {"market": "Gift City",  "name": "GIFT Nifty",  "tv_symbol": "NSEIX:NIFTY1!",    "start": "06:30", "end": "02:45", "icon": "🎁", "w": w_gift,     "trigger_alignment": True,  "category": "nifty_futures"},
    {"market": "NSE Intl",   "name": "BankNifty Fut","tv_symbol": "NSEIX:BANKNIFTY1!","start": "06:30", "end": "03:00", "icon": "🏦", "w": w_sgx,      "trigger_alignment": True,  "category": "nifty_futures"},
    {"market": "USA",        "name": "Nasdaq 100",  "tv_symbol": "NASDAQ:NDX",       "start": "20:00", "end": "02:30", "icon": "🇺🇸", "w": w_nasdaq,   "trigger_alignment": True,  "category": "us"},
    {"market": "USA",        "name": "S&P 500",     "tv_symbol": "SP:SPX",           "start": "20:00", "end": "02:30", "icon": "🇺🇸", "w": 0,          "trigger_alignment": True,  "category": "us"},
    {"market": "Global",     "name": "VIX",         "tv_symbol": "TVC:VIX",          "start": "24 Hrs","end": "24 Hrs","icon": "😨", "w": 0,          "trigger_alignment": False, "category": "risk"},
    {"market": "India",      "name": "India VIX",   "tv_symbol": "NSE:INDIAVIX",     "start": "09:15", "end": "15:30", "icon": "🇮🇳", "w": 0,          "trigger_alignment": False, "category": "india"},
    {"market": "Forex",      "name": "USD/INR",     "tv_symbol": "FX:USDINR",        "start": "24 Hrs","end": "24 Hrs","icon": "💱", "w": w_usdinr,   "trigger_alignment": False, "category": "currency"},
    {"market": "Global",     "name": "Dollar Index","tv_symbol": "TVC:DXY",          "start": "24 Hrs","end": "24 Hrs","icon": "💵", "w": w_dxy,      "trigger_alignment": False, "category": "currency"},
    {"market": "Germany",    "name": "DAX Index",   "tv_symbol": "XETR:DAX",         "start": "13:30", "end": "22:00", "icon": "🇩🇪", "w": w_dax,      "trigger_alignment": False, "category": "europe"},
    {"market": "Hong Kong",  "name": "Hang Seng",   "tv_symbol": "HSI:HSI",          "start": "07:15", "end": "13:30", "icon": "🇭🇰", "w": w_hangseng, "trigger_alignment": True,  "category": "asia"},
    {"market": "China",      "name": "CSI 300",     "tv_symbol": "SSE:000300",       "start": "07:00", "end": "12:30", "icon": "🇨🇳", "w": 0,          "trigger_alignment": False, "category": "asia"},
    {"market": "Japan",      "name": "TOPIX",       "tv_symbol": "TSE:TOPIX",        "start": "05:30", "end": "12:00", "icon": "🇯🇵", "w": 0,          "trigger_alignment": True,  "category": "asia"},
    {"market": "India (MCX)","name": "Crude Oil",   "tv_symbol": "MCX:CRUDEOILM1!",  "start": "09:00", "end": "23:30", "icon": "🛢️", "w": 0,          "trigger_alignment": False, "category": "commodity"},
]

TV_URL  = "https://scanner.tradingview.com/global/scan"
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
SESSION = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

UPSTOX_INDEX_KEYS = {"NIFTY 50": "NSE_INDEX|Nifty 50"}

def fetch_upstox_index_quotes():
    out = {}
    try:
        r = requests.get(
            'https://api.upstox.com/v2/market-quote/quotes',
            params={'instrument_key': ",".join(UPSTOX_INDEX_KEYS.values())},
            headers={'Accept': 'application/json', 'Authorization': access_token},
            timeout=5
        )
        d = json.loads(r.text)
        if d.get("status") != "success":
            return out
        by_token = {}
        for k, v in (d.get("data") or {}).items():
            by_token[k.replace(":", "|")] = v
            if v.get("instrument_token"):
                by_token[v["instrument_token"]] = v
        for name, key in UPSTOX_INDEX_KEYS.items():
            q = by_token.get(key)
            if not q:
                continue
            close = q.get("last_price")
            if not close:
                continue
            net = q.get("net_change")
            if net is None:
                net = close - ((q.get("ohlc") or {}).get("close") or close)
            prev = close - net
            pct = (net / prev * 100) if prev else 0
            out[name] = (round(prev, 2), round(close, 2), round(net, 2), round(pct, 2))
    except Exception as e:
        print(f"Error fetching Upstox index quotes: {e}")
    return out

upstox_index_quotes = fetch_upstox_index_quotes()

def fetch_master_data(symbol_dict):
    if symbol_dict["name"] in UPSTOX_INDEX_KEYS and symbol_dict["name"] in upstox_index_quotes:
        return symbol_dict, upstox_index_quotes[symbol_dict["name"]]
    payload = {
        "symbols": {"tickers": [symbol_dict["tv_symbol"]], "query": {"types": []}},
        "columns": ["close", "change", "change_abs"]
    }
    try:
        r = SESSION.post(TV_URL, json=payload, headers=HEADERS, timeout=5)
        r.raise_for_status()
        d = r.json()["data"][0]["d"]
        close, pct, change_abs = d[0], d[1], d[2]
        prev_close = close - change_abs
        return symbol_dict, (round(prev_close, 2), round(close, 2), round(change_abs, 2), round(pct, 2))
    except Exception as e:
        print(f"Error fetching {symbol_dict['name']}: {e}")
        return symbol_dict, None

def calculate_momentum_score(nifty_price, nifty_prev_close, lookback_minutes=15):
    try:
        change_pct = ((nifty_price - nifty_prev_close) / nifty_prev_close) * 100 if nifty_prev_close > 0 else 0
        if change_pct < -0.5: return -2, "STRONG_BEARISH", change_pct
        elif change_pct < -0.25: return -1, "BEARISH", change_pct
        elif change_pct > 0.5: return 2, "STRONG_BULLISH", change_pct
        elif change_pct > 0.25: return 1, "BULLISH", change_pct
        else: return 0, "NEUTRAL", change_pct
    except:
        return 0, "NEUTRAL", 0

def detect_domestic_pressure(nifty_change_pct, sgx_pct, gift_pct, nifty_price, nifty_prev_close):
    pressure_score = 0
    pressure_type = "ALIGNED"
    reasons = []
    if abs(sgx_pct) > 0.1 and abs(gift_pct) > 0.1:
        avg_futures = (sgx_pct + gift_pct) / 2
        if nifty_change_pct < -0.15 and avg_futures > 0:
            divergence = abs(nifty_change_pct) / (abs(avg_futures) + 0.01)
            if divergence > 1.5:
                pressure_type = "HIGH_DOMESTIC_SELLING"
                pressure_score = divergence * nifty_change_pct * -1
                reasons.append(f"🔴 High domestic selling: Nifty {nifty_change_pct:+.2f}% vs futures {avg_futures:+.2f}%")
            elif divergence > 0.8:
                pressure_type = "MODERATE_DOMESTIC_SELLING"
                pressure_score = divergence * nifty_change_pct * -1
                reasons.append(f"🟡 Moderate domestic selling: divergence {divergence:.1f}x")
    if nifty_price > 0 and nifty_prev_close > 0:
        range_size = abs(nifty_price - nifty_prev_close) / nifty_prev_close * 100
        if range_size > 0.5 and pressure_type == "ALIGNED":
            if nifty_change_pct < -0.3:
                pressure_type = "STRONG_DOWN_MOMENTUM"; pressure_score = abs(nifty_change_pct) * 2
                reasons.append(f"🔴 Strong downward momentum: {nifty_change_pct:+.2f}%")
            elif nifty_change_pct > 0.3:
                pressure_type = "STRONG_UP_MOMENTUM"; pressure_score = abs(nifty_change_pct) * 2
                reasons.append(f"✅ Strong upward momentum: {nifty_change_pct:+.2f}%")
    return pressure_type, pressure_score, reasons

def apply_domestic_override(sentiment_score, pressure_type, pressure_score, momentum_score):
    if "SELLING" in pressure_type:
        if sentiment_score > 0:
            reduction = min(0.95, pressure_score * 0.15)
            return sentiment_score * (1 - reduction), f"🛑 Domestic Selling Override: {reduction:.0%} reduction"
        else:
            amplification = min(1.5, 1 + pressure_score * 0.05)
            return sentiment_score * amplification, f"⬇️ Bearish amplified: {amplification:.1f}x"
    elif "MOMENTUM" in pressure_type:
        if pressure_type == "STRONG_DOWN_MOMENTUM" and sentiment_score > 0:
            reduction = min(0.9, 0.7 + abs(pressure_score) * 0.05)
            return sentiment_score * (1 - reduction), f"📉 Down Momentum Override: {reduction:.0%} reduction"
        elif pressure_type == "STRONG_UP_MOMENTUM" and sentiment_score < 0:
            reduction = min(0.9, 0.7 + abs(pressure_score) * 0.05)
            return sentiment_score * (1 - reduction), f"📈 Up Momentum Override: {reduction:.0%} reduction"
    return sentiment_score, "No override"

def fetch_futures_data():
    url = 'https://api.upstox.com/v2/market/smartlist/futures'
    params = {'asset_type': 'INDEX', 'category': 'TOP_TRADED', 'page_number': 1, 'page_size': 20}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'Authorization': access_token}
    response = requests.get(url, params=params, headers=headers)
    return json.loads(response.text)

def parse_futures_flow(data, title="OI Flow Details", key_prefix=None, key_contains=None):
    smartlist = data['data']['smartlist']
    if key_prefix:
        smartlist = [item for item in smartlist if item["instrument_key"].startswith(key_prefix)]
    if key_contains:
        smartlist = [item for item in smartlist if key_contains in item["instrument_key"]]
    rows = []
    weighted_score = 0.0
    total_value_weight = 0.0
    for item in smartlist:
        current_value = item['metric']['current']
        if current_value < 100_000_000:
            continue
        price_change = item['price']['change_pct']
        change_abs = item['metric']['change_abs']
        change_pct = item['metric']['change_pct']
        score = 0.0
        if change_abs > 1_000_000_000 and price_change < -0.3: score = -0.9
        elif change_abs > 1_000_000_000 and price_change > 0.3: score = 0.9
        elif change_pct > 30 and price_change < -0.3: score = -0.6
        elif change_pct > 10 and price_change < -0.5: score = -0.4
        elif change_pct > 10 and price_change > 0.5: score = 0.4
        weight = current_value / 1_000_000_000
        weighted_score += score * weight
        total_value_weight += weight
        rows.append({"instrument_key": item["instrument_key"], "score": score, "weight": weight,
                     "current_value": current_value, "price_change": price_change,
                     "change_abs": change_abs, "change_pct": change_pct})
    final_score = 0.0 if total_value_weight == 0 else weighted_score / total_value_weight
    final_score = max(-1, min(1, final_score))
    return {"score": final_score, "rows": rows, "title": title, "key_prefix": key_prefix}

with ThreadPoolExecutor(max_workers=len(master_symbols)) as executor:
    results = list(executor.map(fetch_master_data, master_symbols))

final_display = []
volatility_alerts = []
weighted_pcts_c1 = []
sentiment_score_c1 = 0.0
trigger_pcts_c2 = []

nifty_price = nifty_prev_close = 0.0
vix_value = 0.0; usdinr_pct = 0.0; china_pct = 0.0; sgx_pct = 0.0; gift_pct = 0.0
hangseng_pct = 0.0; sp500_pct = 0.0; nasdaq_pct = 0.0; topix_pct = 0.0
india_vix_value = 0.0; india_vix_pct = 0.0

for s, res in results:
    if res:
        prev, close, change, pct = res
        final_display.append({"s": s, "close": close, "pct": pct, "abs": change, "prev": prev})
        if s["name"] == "NIFTY 50": nifty_price, nifty_prev_close = close, prev
        elif s["name"] == "VIX": vix_value = close
        elif s["name"] == "India VIX": india_vix_value = close; india_vix_pct = pct
        elif s["name"] == "USD/INR": usdinr_pct = pct
        elif s["name"] == "CSI 300": china_pct = pct
        elif s["name"] == "BankNifty Fut": sgx_pct = pct
        elif s["name"] == "GIFT Nifty": gift_pct = pct
        elif s["name"] == "Hang Seng": hangseng_pct = pct
        elif s["name"] == "S&P 500": sp500_pct = pct
        elif s["name"] == "Nasdaq 100": nasdaq_pct = pct
        elif s["name"] == "TOPIX": topix_pct = pct
        if s["w"] != 0:
            sentiment_score_c1 += pct * s["w"]; weighted_pcts_c1.append(pct)
        if s["trigger_alignment"]: trigger_pcts_c2.append(pct)
        if abs(pct) >= 2.0: volatility_alerts.append(f"{s['icon']} {s['name']} moved {pct:+.2f}%")
    else:
        final_display.append({"s": s, "close": 0, "pct": 0, "abs": 0, "prev": 0})

fetched_data = fetch_futures_data()
nifty_flow_result = parse_futures_flow(fetched_data, title="Nifty OI Flow Details", key_prefix="NSE_FO")
nifty_macro_score = nifty_flow_result["score"]

momentum_score, momentum_label, momentum_pct = calculate_momentum_score(
    nifty_price, nifty_prev_close, momentum_lookback)

nifty_change_pct = ((nifty_price - nifty_prev_close) / nifty_prev_close) * 100 if nifty_prev_close > 0 else 0
nifty_actual_change = nifty_price - nifty_prev_close

pressure_type, pressure_score, pressure_reasons = detect_domestic_pressure(
    nifty_change_pct, sgx_pct, gift_pct, nifty_price, nifty_prev_close)

# VIX LOGIC
vix_regime = "NORMAL"; vix_dampener_val = 1.0; vix_warning = ""
us_vix_dampener = 1.0
if vix_value > 0:
    if vix_value >= vix_threshold + 5:
        us_vix_dampener = vix_dampener * 0.3; vix_regime = "EXTREME FEAR"
        vix_warning = f"🔴 US VIX EXTREME: {vix_value:.1f}"
    elif vix_value >= vix_threshold:
        us_vix_dampener = vix_dampener; vix_regime = "ELEVATED"
        vix_warning = f"🟡 US VIX ELEVATED: {vix_value:.1f}"
india_vix_dampener = 1.0; india_vix_regime = "NORMAL"
if india_vix_value > 0:
    if india_vix_value >= india_vix_threshold + 5:
        india_vix_dampener = india_vix_dampener * 0.3; india_vix_regime = "EXTREME FEAR"
        vix_warning += f" | 🔴 India VIX EXTREME: {india_vix_value:.1f}"
    elif india_vix_value >= india_vix_threshold:
        india_vix_dampener = india_vix_dampener; india_vix_regime = "ELEVATED"
        vix_warning += f" | 🟡 India VIX ELEVATED: {india_vix_value:.1f}"
combined_dampener = min(us_vix_dampener, india_vix_dampener)
if vix_warning:
    vix_warning = "⚠️ " + vix_warning + " — Bullish signals dampened."

raw_sentiment = sentiment_score_c1
if raw_sentiment > 0 and combined_dampener < 1.0:
    sentiment_score_c1 = raw_sentiment * combined_dampener
sentiment_score_c1, override_note = apply_domestic_override(
    sentiment_score_c1, pressure_type, pressure_score, momentum_score)

# DIVERGENCE
divergence_detected = False; divergence_msg = ""; divergence_level = "NONE"
if nifty_price > 0 and nifty_prev_close > 0:
    if sentiment_score_c1 > 0.1 and nifty_change_pct < -0.15:
        divergence_detected = True; divergence_level = "BULLISH_DIVERGENCE"
        divergence_msg = (f"⚠️ BULLISH DIVERGENCE: Global weights suggest upward drift "
                          f"(+{raw_sentiment:.2f}% raw → {sentiment_score_c1:+.2f}% adjusted), "
                          f"but Nifty Spot is sliding ({nifty_change_pct:+.2f}% / {nifty_actual_change:+.2f} pts).")
    elif sentiment_score_c1 < -0.1 and nifty_change_pct > 0.15:
        divergence_detected = True; divergence_level = "BEARISH_DIVERGENCE"
        divergence_msg = (f"⚠️ BEARISH DIVERGENCE: Global weights negative "
                          f"({raw_sentiment:.2f}% → {sentiment_score_c1:+.2f}%), "
                          f"but Nifty Spot is squeezing up ({nifty_change_pct:+.2f}% / {nifty_actual_change:+.2f} pts).")

# ==============================
# CODE 1 — entry/exit/gate functions (unchanged)
# ==============================
def get_entry_signal_from_change_oi(change_oi_response, spot_price, buffer_points=27, greeks_by_strike=None, max_candidates=5):
    if not change_oi_response or change_oi_response.get("status") != "success":
        return None
    data = change_oi_response.get("data") or {}
    items = data.get("call_put_oi_data_list") or []
    if not items:
        return None
    ranked = []
    for item in items:
        call_oi = item.get("call_change_oi", item.get("call_oi", 0))
        put_oi = item.get("put_change_oi", item.get("put_oi", 0))
        ranked.append((abs(put_oi - call_oi), item, call_oi, put_oi))
    ranked.sort(key=lambda x: x[0], reverse=True)
    best_item = None; best_diff = -1; best_call_oi = best_put_oi = 0
    best_conf, best_delta_ok, best_notes = 40.0, True, []
    for diff, item, call_oi, put_oi in ranked[:max_candidates]:
        high_type = "HIGH PUT" if put_oi > call_oi else "HIGH CALL"
        strike = item["strike_price"]
        greeks = greeks_by_strike.get(strike) if greeks_by_strike else None
        conf, delta_ok, notes = compute_greeks_confidence(high_type, greeks)
        if delta_ok:
            best_item, best_diff = item, diff
            best_call_oi, best_put_oi = call_oi, put_oi
            best_conf, best_delta_ok, best_notes = conf, delta_ok, notes
            break
        elif best_item is None:
            best_item, best_diff = item, diff
            best_call_oi, best_put_oi = call_oi, put_oi
            best_conf, best_delta_ok, best_notes = conf, delta_ok, notes
    if best_item is None: return None
    strike = best_item["strike_price"]
    high_type = "HIGH PUT" if best_put_oi > best_call_oi else "HIGH CALL"
    if high_type == "HIGH PUT":
        trigger_price = strike + buffer_points; signal = "BUY"
        reason = f"Support at {strike} (Put OI > Call OI). Trigger at {trigger_price}"
    else:
        trigger_price = strike - buffer_points; signal = "SELL"
        reason = f"Resistance at {strike} (Call OI > Put OI). Trigger at {trigger_price}"
    active = False
    if signal == "BUY" and spot_price >= trigger_price: active = True
    elif signal == "SELL" and spot_price <= trigger_price: active = True
    _others = [r[0] for r in ranked if r[1] is not best_item]
    _second = _others[0] if _others else 0
    dominance = (best_diff / _second) if _second > 0 else 99.0
    stop_loss = (strike - gate_sl_buffer) if signal == "BUY" else (strike + gate_sl_buffer)
    reason = f"{reason} | SL {stop_loss:,.0f}"
    return {"strike": strike, "high_type": high_type, "signal": signal,
            "trigger_price": trigger_price, "active": active, "reason": reason,
            "call_oi": best_call_oi, "put_oi": best_put_oi, "oi_diff": best_diff,
            "dominance": dominance, "stop_loss": stop_loss,
            "greeks": greeks_by_strike.get(strike) if greeks_by_strike else None,
            "greeks_confidence": best_conf, "delta_ok": best_delta_ok,
            "greeks_notes": best_notes}

def get_exit_signal_from_change_oi(change_oi_response, spot_price, entry_signal, buffer_points=27, min_gap=100, greeks_by_strike=None):
    if not change_oi_response or change_oi_response.get("status") != "success":
        return None
    data = change_oi_response.get("data") or {}
    items = data.get("call_put_oi_data_list") or []
    if not items: return None
    opposite_high_type = "HIGH CALL" if entry_signal["signal"] == "BUY" else "HIGH PUT"
    best_item = None; best_diff = -1
    for item in items:
        call_oi = item.get("call_change_oi", item.get("call_oi", 0))
        put_oi = item.get("put_change_oi", item.get("put_oi", 0))
        high_type = "HIGH PUT" if put_oi > call_oi else "HIGH CALL"
        if high_type == opposite_high_type:
            diff = abs(put_oi - call_oi)
            if diff > best_diff:
                best_diff = diff; best_item = item
    if best_item is None: return None
    strike = best_item["strike_price"]
    call_oi = best_item.get("call_change_oi", best_item.get("call_oi", 0))
    put_oi = best_item.get("put_change_oi", best_item.get("put_oi", 0))
    if opposite_high_type == "HIGH PUT":
        trigger_price = strike + buffer_points; exit_signal_type = "BUY"
    else:
        trigger_price = strike - buffer_points; exit_signal_type = "SELL"
    if abs(entry_signal["trigger_price"] - trigger_price) < min_gap:
        return None
    active = spot_price >= trigger_price if entry_signal["signal"] == "BUY" else spot_price <= trigger_price
    reason = f"Exit {'BUY' if opposite_high_type=='HIGH PUT' else 'SELL'} signal: " \
             f"{'Support' if opposite_high_type=='HIGH PUT' else 'Resistance'} at {strike}. Trigger at {trigger_price}"
    return {"strike": strike, "high_type": opposite_high_type, "signal": exit_signal_type,
            "trigger_price": trigger_price, "active": active, "reason": reason,
            "call_oi": call_oi, "put_oi": put_oi, "oi_diff": best_diff,
            "greeks": greeks_by_strike.get(strike) if greeks_by_strike else None}

def _fmt_t(dt_obj):
    return dt_obj.strftime("%H:%M:%S") if dt_obj else "—"

def _in_trade_window(now_dt, allow_opening=False):
    if now_dt.weekday() >= 5: return False, "Weekend — market closed"
    t = now_dt.time()
    if t < time(9, 15) or t > time(15, 30): return False, "Market closed"
    if not gate_time_filter: return True, "Market open (time filter off)"
    if t < time(9, 30):
        if allow_opening: return True, "Opening 15 min allowed — confirmed OI flip"
        return False, "Opening 15 min — wait for liquidity to settle"
    if t > time(15, 0): return False, "Last 30 min — avoid late entries"
    return True, "Inside preferred trading window (09:30–15:00)"

def _beyond_trigger(sig, trig, spot):
    return (sig == "BUY" and spot >= trig) or (sig == "SELL" and spot <= trig)

def entry_status_text(sig):
    return sig.get("status_label") or ("ACTIVE" if sig.get("active") else "PENDING")

def apply_signal_gate(index_name, entry, spot_price, macro_score, flip=None):
    key = f"gate_state_{index_name}"
    now_dt = datetime.now(ist)
    today_key = now_dt.strftime("%Y-%m-%d")
    state = st.session_state.get(key)
    if not state or state.get("date") != today_key:
        state = {"date": today_key, "cand_dir": None, "cand_since": None,
                 "cross_since": None, "locked": None, "event": ""}
    status = {"verdict": "NONE", "checks": [], "time_label": "—", "warning": "", "event": state.get("event", "")}
    hist_key = f"gate_hist_{index_name}"
    hist = st.session_state.get(hist_key, [])
    hist.append((now_dt, macro_score))
    hist = [h for h in hist if (now_dt - h[0]).total_seconds() <= 900]
    st.session_state[hist_key] = hist
    ref = next((sc for t, sc in hist if (now_dt - t).total_seconds() <= 300), None)
    trend_txt = f", {macro_score - ref:+.2f} vs ~5 min ago" if (ref is not None and len(hist) > 1) else ""
    flip_dir = (flip or {}).get("flip")
    flip_sig = {"BULLISH": "BUY", "BEARISH": "SELL"}.get(flip_dir)
    locked = state.get("locked")
    if locked:
        sig = locked["signal"]
        stopped = (sig == "BUY" and spot_price <= locked["stop_loss"]) or \
                  (sig == "SELL" and spot_price >= locked["stop_loss"])
        flip_release = bool(gate_flip_override and flip_sig and flip_sig != sig)
        if stopped or flip_release:
            if stopped:
                state["event"] = (f"🛑 {sig} signal (locked {_fmt_t(locked['confirmed_at'])}) hit stop-loss "
                                  f"{locked['stop_loss']:,.2f} at {_fmt_t(now_dt)} — signal released")
            else:
                state["event"] = (f"🔄 Confirmed {flip_dir} OI flip at {_fmt_t(now_dt)} — locked {sig} signal "
                                  f"(since {_fmt_t(locked['confirmed_at'])}) released")
            state.update({"locked": None, "cand_dir": None, "cand_since": None, "cross_since": None})
            locked = None
        else:
            out = dict(locked)
            beyond = _beyond_trigger(sig, out["trigger_price"], spot_price)
            out["active"] = beyond
            out["status_label"] = "🔒 CONFIRMED & ACTIVE" if beyond else "🔒 LOCKED — price back inside trigger"
            status.update({"verdict": "LOCKED", "time_label": f"Locked {_fmt_t(out['confirmed_at'])}",
                           "event": state.get("event", "")})
            status["checks"] = [(True, f"Locked at {_fmt_t(out['confirmed_at'])} — ignores OI re-ranking until "
                                       f"stop-loss {out['stop_loss']:,.2f} is hit")]
            if entry and entry["signal"] != sig:
                status["warning"] = (f"Live OI now leans {entry['signal']} (key strike {entry['strike']}), "
                                     f"opposite to your locked {sig}. Review your risk.")
            st.session_state[key] = state
            return out, status
    if not entry:
        state.update({"cand_dir": None, "cand_since": None, "cross_since": None})
        status["event"] = state.get("event", "")
        st.session_state[key] = state
        return None, status
    sig = entry["signal"]
    if state["cand_dir"] != sig:
        state.update({"cand_dir": sig, "cand_since": now_dt, "cross_since": None})
    if _beyond_trigger(sig, entry["trigger_price"], spot_price):
        if state["cross_since"] is None: state["cross_since"] = now_dt
    else:
        state["cross_since"] = None
    held_s = (now_dt - state["cand_since"]).total_seconds()
    cross_s = (now_dt - state["cross_since"]).total_seconds() if state["cross_since"] else 0.0
    checks = []
    flip_ok = bool(gate_flip_override and flip_sig and flip_sig == sig)
    held_ok = held_s >= gate_hold_min * 60
    checks.append((held_ok or flip_ok,
                   f"Signal held {held_s/60:.1f} / {gate_hold_min} min (same direction, no flip)"
                   + (" — bypassed by confirmed OI flip" if (flip_ok and not held_ok) else "")))
    checks.append((state["cross_since"] is not None and cross_s >= gate_price_min * 60,
                   f"Price beyond trigger {entry['trigger_price']:,.0f} for {cross_s/60:.1f} / {gate_price_min} min"))
    if gate_use_futures:
        agree = (macro_score >= gate_min_score) if sig == "BUY" else (macro_score <= -gate_min_score)
        need = f"≥ +{gate_min_score:.2f}" if sig == "BUY" else f"≤ -{gate_min_score:.2f}"
        checks.append((agree, f"Futures flow score {macro_score:+.2f}{trend_txt} (needs {need})"))
    dom = entry.get("dominance", 99.0)
    checks.append((dom >= gate_min_dom, f"Key strike dominance {min(dom, 99):.1f}x vs next (min {gate_min_dom:.1f}x)"))
    dist_pct = abs(entry["strike"] - spot_price) / spot_price * 100 if spot_price else 0
    checks.append((dist_pct <= gate_max_dist_pct, f"Key strike {dist_pct:.2f}% from spot (max {gate_max_dist_pct:.1f}%)"))
    checks.append((entry.get("delta_ok", True), "Strike passes Delta relevance filter"))
    if flip_sig:
        checks.append((flip_sig == sig, f"OI flip meter: {flip_dir} flip active "
                                        f"({'agrees with' if flip_sig == sig else 'CONFLICTS with'} {sig} signal)"))
    win_ok, win_txt = _in_trade_window(now_dt, allow_opening=flip_ok)
    checks.append((win_ok, win_txt))
    passed = sum(1 for ok, _ in checks if ok)
    status["checks"] = checks
    if passed == len(checks):
        locked_entry = dict(entry); locked_entry["confirmed_at"] = now_dt
        state["locked"] = locked_entry
        state["event"] = f"✅ {sig} confirmed at {_fmt_t(now_dt)} (spot {spot_price:,.2f}) — signal locked"
        out = dict(locked_entry); out["active"] = True
        out["status_label"] = "🔒 CONFIRMED & ACTIVE"
        status.update({"verdict": "CONFIRMED", "time_label": f"Locked {_fmt_t(now_dt)}", "event": state["event"]})
    else:
        out = dict(entry); out["active"] = False
        out["status_label"] = f"⏳ WAITING — {passed}/{len(checks)} checks passed"
        out["reason"] = f"{out['reason']} | NOT CONFIRMED"
        status.update({"verdict": "WAITING", "time_label": f"First seen {_fmt_t(state['cand_since'])}",
                       "event": state.get("event", "")})
    st.session_state[key] = state
    return out, status

def render_gate_panel(gate, label):
    verdict = gate.get("verdict", "NONE")
    if verdict == "NONE":
        st.caption(f"🛡️ {label} entry gate: no raw OI signal right now.")
        if gate.get("event"): st.caption(gate["event"])
        return
    color = {"CONFIRMED": "#2e7d32", "LOCKED": "#2e7d32", "WAITING": "#f9a825"}.get(verdict, "#6e7781")
    title = {"CONFIRMED": "✅ CONFIRMED — signal locked", "LOCKED": "🔒 LOCKED SIGNAL",
             "WAITING": "⏳ WAITING FOR CONFIRMATION"}.get(verdict, verdict)
    rows = "".join(f"<div>{'✅' if ok else '❌'} {txt}</div>" for ok, txt in gate["checks"])
    extra = ""
    if gate.get("warning"): extra += f'<div style="margin-top:6px; color:#c62828;"><b>⚠️ {gate["warning"]}</b></div>'
    if gate.get("event"): extra += f'<div style="margin-top:6px; font-size:0.85rem;">{gate["event"]}</div>'
    html = (f'<div class="greeks-panel" style="border-left-color: {color};">'
            f'<b>🛡️ {label} Entry Gate — {title}</b>'
            f'<div style="margin-top:6px; font-size:0.9rem;">{rows}</div>{extra}</div>')
    st.markdown(html, unsafe_allow_html=True)

# ==============================
# OI FLIP METER (unchanged)
# ==============================
def _fv(v, spec):
    try: return format(v, spec)
    except Exception: return "—"

def compute_oi_flip_meter(index_name, change_oi_response, spot_price, greeks_by_strike):
    now_dt = datetime.now(ist)
    res = {"available": False, "score": 0.0, "state": "NO DATA", "flip": None, "flip_since": None,
           "flip_from": None, "msg": "", "atm": None, "history": [], "n_strikes": 0}
    if spot_price <= 0 or not change_oi_response or change_oi_response.get("status") != "success":
        res["msg"] = "change-in-OI data not available (market closed or not yet published)."
        return res
    items = ((change_oi_response.get("data") or {}).get("call_put_oi_data_list")) or []
    if not items:
        res["msg"] = "change-in-OI data not available (market closed or not yet published)."
        return res
    rows = sorted(items, key=lambda x: x["strike_price"])
    strikes = [r["strike_price"] for r in rows]
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot_price))
    lo = max(0, atm_idx - meter_window_strikes)
    hi = min(len(rows), atm_idx + meter_window_strikes + 1)
    window = rows[lo:hi]
    greeks_by_strike = greeks_by_strike or {}
    use_gamma = any(((greeks_by_strike.get(r["strike_price"]) or {}).get("call_gamma") or
                     (greeks_by_strike.get(r["strike_price"]) or {}).get("put_gamma")) for r in window)
    P = C = 0.0
    for i, r in enumerate(window):
        g = greeks_by_strike.get(r["strike_price"]) or {}
        dist = abs((lo + i) - atm_idx)
        if use_gamma:
            wc = g.get("call_gamma") or 0; wp = g.get("put_gamma") or 0
        else:
            wc = wp = 1.0 / (1 + dist)
        ccoi = r.get("call_change_oi", r.get("call_oi", 0)) or 0
        pcoi = r.get("put_change_oi", r.get("put_oi", 0)) or 0
        P += pcoi * wp; C += ccoi * wc
    denom = abs(P) + abs(C)
    score = ((P - C) / denom * 100.0) if denom > 0 else 0.0
    hist_key = f"meter_hist_{index_name}"
    hist = st.session_state.get(hist_key, [])
    hist.append((now_dt, score))
    hist = [h for h in hist if (now_dt - h[0]).total_seconds() <= 5400]
    st.session_state[hist_key] = hist
    thr = meter_flip_threshold; confirm_n = 3
    recent = [sc for _, sc in hist[-confirm_n:]]
    older = [sc for t, sc in hist[:-confirm_n] if (now_dt - t).total_seconds() <= meter_flip_lookback * 60]
    new_flip, from_val = None, None
    if len(recent) == confirm_n and older:
        if all(sc >= thr for sc in recent) and any(sc <= -thr for sc in older):
            new_flip, from_val = "BULLISH", min(older)
        elif all(sc <= -thr for sc in recent) and any(sc >= thr for sc in older):
            new_flip, from_val = "BEARISH", max(older)
    fkey = f"gate_state_flip_{index_name}"
    fstate = st.session_state.get(fkey)
    if fstate:
        age = (now_dt - fstate["since"]).total_seconds()
        crossed_back = (fstate["dir"] == "BULLISH" and score < 0) or (fstate["dir"] == "BEARISH" and score > 0)
        if age > meter_flip_lookback * 60 or crossed_back: fstate = None
    if new_flip and (not fstate or fstate["dir"] != new_flip):
        fstate = {"dir": new_flip, "since": now_dt, "from": from_val}
    st.session_state[fkey] = fstate
    if fstate:
        res["flip"], res["flip_since"], res["flip_from"] = fstate["dir"], fstate["since"], fstate.get("from")
        res["state"] = f"🔄 {fstate['dir']} FLIP"
    elif score >= thr: res["state"] = "BULLISH"
    elif score <= -thr: res["state"] = "BEARISH"
    else: res["state"] = "NEUTRAL"
    g = greeks_by_strike.get(strikes[atm_idx]) or {}
    cg, pg = g.get("call_iv"), g.get("put_iv")
    res.update({"available": True, "score": score, "n_strikes": len(window),
                "history": [sc for _, sc in hist][-120:],
                "atm": {"strike": strikes[atm_idx],
                        "call_delta": g.get("call_delta"), "put_delta": g.get("put_delta"),
                        "gamma": g.get("call_gamma") or g.get("put_gamma"),
                        "call_theta": g.get("call_theta"), "put_theta": g.get("put_theta"),
                        "vega": g.get("call_vega") or g.get("put_vega"),
                        "call_iv": cg, "put_iv": pg,
                        "skew": (pg - cg) if (cg is not None and pg is not None) else None}})
    return res

def render_oi_meter(meter, label, spot_price):
    if not meter.get("available"):
        st.caption(f"🧭 {label} OI Flip Meter: {meter.get('msg', 'no data')}")
        return
    score = meter["score"]; thr = meter_flip_threshold
    color = "#2e7d32" if score >= thr else ("#c62828" if score <= -thr else "#f9a825")
    pos = max(0.0, min(100.0, (score + 100) / 2))
    atm = meter["atm"]
    flip_html = ""
    if meter.get("flip"):
        arrow = "🟢" if meter["flip"] == "BULLISH" else "🔴"
        flip_html = (f'<div style="margin-top:8px; font-weight:bold;">{arrow} {meter["flip"]} FLIP — OI bias swung from '
                     f'{_fv(meter.get("flip_from"), "+.0f")} to {score:+.0f} (detected {_fmt_t(meter.get("flip_since"))})</div>')
    spark = ""
    hist = meter.get("history", [])
    if len(hist) >= 2:
        W, H = 280, 44
        pts = " ".join(f"{i * W / (len(hist) - 1):.1f},{H / 2 - sc / 100 * (H / 2):.1f}" for i, sc in enumerate(hist))
        spark = (f'<svg width="{W}" height="{H}" style="margin-top:8px; background:#f4f7f9; border-radius:6px;">'
                 f'<line x1="0" y1="{H / 2}" x2="{W}" y2="{H / 2}" stroke="#bbb" stroke-dasharray="3,3"/>'
                 f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/></svg>'
                 f'<span style="font-size:0.75rem; color:#555; margin-left:8px;">score history (since app opened)</span>')
    items = [
        ("Δ Call/Put", f"{_fv(atm['call_delta'], '.2f')} / {_fv(atm['put_delta'], '.2f')}"),
        ("Γ Gamma", _fv(atm["gamma"], ".5f")),
        ("Θ Theta C/P", f"{_fv(atm['call_theta'], '.1f')} / {_fv(atm['put_theta'], '.1f')}"),
        ("V Vega", _fv(atm["vega"], ".2f")),
        ("IV Call/Put", f"{_fv(atm['call_iv'], '.1f')}% / {_fv(atm['put_iv'], '.1f')}%"),
        ("IV skew (P−C)", _fv(atm["skew"], "+.2f")),
    ]
    greeks_html = "".join(f'<span style="margin-right:18px;">{k}: <b>{v}</b></span>' for k, v in items)
    html = (
        f'<div class="greeks-panel" style="border-left-color: {color};">'
        f'<b>🧭 {label} OI Flip Meter</b> &nbsp;|&nbsp; <b>{meter["state"]}</b> &nbsp;|&nbsp; '
        f'Live {label}: <b>{spot_price:,.2f}</b> &nbsp;|&nbsp; ATM strike: <b>{atm["strike"]:,.0f}</b>'
        f'<div style="position:relative; height:14px; border-radius:7px; margin:16px 4px 4px 4px; '
        f'background:linear-gradient(90deg,#c62828 0%,#f9a825 50%,#2e7d32 100%);">'
        f'<div style="position:absolute; left:{pos:.1f}%; top:-5px; width:4px; height:24px; background:#000; border-radius:2px;"></div></div>'
        f'<div style="display:flex; justify-content:space-between; font-size:0.75rem; color:#555;">'
        f'<span>−100 Bearish</span><span>Score {score:+.0f}</span><span>Bullish +100</span></div>'
        f'{flip_html}'
        f'<div style="margin-top:8px; font-size:0.9rem;">ATM Greeks @ {atm["strike"]:,.0f}: {greeks_html}</div>'
        f'{spark}'
        f'<div style="font-size:0.78rem; color:#555; margin-top:6px;">Score = gamma-weighted (Put ΔOI − Call ΔOI) over '
        f'{meter["n_strikes"]} strikes around live price. Green = put writing / call unwinding (support building); '
        f'red = call writing / put unwinding (resistance building).</div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)

def process_index_signals(index_name, change_oi_response, spot_price, greeks, macro_score, flip=None):
    entry = None; exit_sig = None
    if spot_price > 0 and change_oi_response.get("status") == "success":
        entry = get_entry_signal_from_change_oi(change_oi_response, spot_price, buffer_points=27, greeks_by_strike=greeks)
    if entry:
        exit_sig = get_exit_signal_from_change_oi(change_oi_response, spot_price, entry, buffer_points=27, min_gap=100, greeks_by_strike=greeks)
        if exit_sig is None: entry = None
    entry, gate = apply_signal_gate(index_name, entry, spot_price, macro_score, flip) if spot_price > 0 else (None, {"verdict": "NONE", "checks": [], "time_label": "—", "warning": "", "event": ""})
    if entry and gate.get("verdict") == "LOCKED" and change_oi_response.get("status") == "success":
        exit_sig = get_exit_signal_from_change_oi(change_oi_response, spot_price, entry, buffer_points=27, min_gap=100, greeks_by_strike=greeks)
    if not entry: exit_sig = None
    return entry, exit_sig, gate

nifty_meter = compute_oi_flip_meter("Nifty", upstoxOiChangeResponse, nifty_price, nifty_greeks_by_strike)
nifty_entry_signal, nifty_exit_signal, nifty_gate = process_index_signals(
    "Nifty", upstoxOiChangeResponse, nifty_price, nifty_greeks_by_strike, nifty_macro_score, nifty_meter)

updated_datetime = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")
entry_datetime = updated_datetime

def render_greeks_panel(signal_data, label):
    if not signal_data or not signal_data.get("greeks"):
        st.caption(f"ℹ️ No Greeks data for {label} key strike.")
        return
    g = signal_data["greeks"]; high_type = signal_data["high_type"]
    conf = signal_data.get("greeks_confidence", 0)
    if high_type == "HIGH PUT":
        delta, gamma, theta, vega, iv, leg = g["put_delta"], g["put_gamma"], g["put_theta"], g["put_vega"], g["put_iv"], "PUT"
    else:
        delta, gamma, theta, vega, iv, leg = g["call_delta"], g["call_gamma"], g["call_theta"], g["call_vega"], g["call_iv"], "CALL"
    color = "#2e7d32" if conf >= 60 else "#f9a825" if conf >= 35 else "#c62828"
    badge_class = "badge-pass" if signal_data.get("delta_ok", True) else "badge-weak"
    badge_text = "✅ PASSES DELTA FILTER" if signal_data.get("delta_ok", True) else "⚠️ WEAK — OUTSIDE DELTA BAND"
    st.markdown(f"""
    <div class="greeks-panel" style="border-left-color: {color};">
        <b>{leg} Greeks @ {signal_data['strike']}</b> &nbsp;|&nbsp; <span class="{badge_class}">{badge_text}</span>
        <div style="display:flex; gap:20px; margin-top:6px; font-size:0.9rem; flex-wrap:wrap;">
            <span class="greek-item">Δ Delta: <b>{delta:.3f}</b></span>
            <span class="greek-item">Γ Gamma: <b>{gamma:.5f}</b></span>
            <span class="greek-item">Θ Theta: <b>{theta:.2f}</b></span>
            <span class="greek-item">V Vega: <b>{vega:.2f}</b></span>
            <span class="greek-item">IV: <b>{iv:.1f}%</b></span>
            <span class="greek-item">Greeks Confidence: <b>{conf:.0f}%</b></span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    for n in signal_data.get("greeks_notes", []): st.caption(n)

# ==========================================================
# ============ CHANGE-IN-OI REVERSAL METER (NEW) ============
# ==========================================================
def _fmt_oi_units(v, signed=True):
    try: v = float(v)
    except Exception: return "—"
    a = abs(v)
    sign = "+" if (signed and v > 0) else ("−" if v < 0 else "")
    if a >= 1e7: return f"{sign}{a/1e7:.2f} Cr"
    if a >= 1e5: return f"{sign}{a/1e5:.2f} L"
    if a >= 1e3: return f"{sign}{a/1e3:.1f} K"
    return f"{sign}{a:.0f}"

def _rev_change_oi_hash(resp):
    if not resp or resp.get("status") != "success": return None
    items = (resp.get("data") or {}).get("call_put_oi_data_list") or []
    if not items: return None
    parts = []
    for it in sorted(items, key=lambda x: x.get("strike_price", 0)):
        parts.append((it.get("strike_price"),
                      round(float(it.get("call_change_oi", 0) or 0), 2),
                      round(float(it.get("put_change_oi", 0) or 0), 2)))
    return hash(tuple(parts))

def _rev_aggregate_change_oi(resp, spot_price, window_strikes):
    out = {"available": False, "ce": 0.0, "pe": 0.0, "atm": None,
           "n": 0, "ce_by_strike": {}, "pe_by_strike": {}}
    if not resp or resp.get("status") != "success": return out
    items = (resp.get("data") or {}).get("call_put_oi_data_list") or []
    if not items: return out
    rows = sorted(items, key=lambda x: x.get("strike_price", 0))
    strikes = [r.get("strike_price", 0) for r in rows]
    if spot_price > 0:
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot_price))
        lo = max(0, atm_idx - window_strikes); hi = min(len(rows), atm_idx + window_strikes + 1)
        out["atm"] = strikes[atm_idx]
    else:
        lo, hi = 0, len(rows)
    for r in rows[lo:hi]:
        s = r.get("strike_price")
        ce = float(r.get("call_change_oi", r.get("call_oi", 0)) or 0)
        pe = float(r.get("put_change_oi", r.get("put_oi", 0)) or 0)
        out["ce_by_strike"][s] = ce; out["pe_by_strike"][s] = pe
        out["ce"] += ce; out["pe"] += pe
    out["n"] = hi - lo; out["available"] = out["n"] > 0
    return out

def _rev_compute_pcr(oi_resp):
    if not oi_resp or oi_resp.get("status") != "success": return None
    items = (oi_resp.get("data") or {}).get("call_put_oi_data_list") or []
    tp = sum(float(it.get("put_oi", 0) or 0) for it in items)
    tc = sum(float(it.get("call_oi", 0) or 0) for it in items)
    if tc <= 0: return None
    return tp / tc

def _rev_capture_snapshot(change_oi_resp, oi_resp, spot_price, window_strikes):
    agg = _rev_aggregate_change_oi(change_oi_resp, spot_price, window_strikes)
    if not agg["available"]: return None
    return {"ts": datetime.now(ist), "ce": agg["ce"], "pe": agg["pe"],
            "imb": agg["ce"] - agg["pe"],
            "spot": float(spot_price) if spot_price else 0.0,
            "atm": agg["atm"], "n": agg["n"],
            "pcr": _rev_compute_pcr(oi_resp),
            "hash": _rev_change_oi_hash(change_oi_resp)}

def _rev_add_snapshot(snap, max_keep=3000):
    if not snap: return
    hist = st.session_state.get("rev_snapshots", [])
    if hist and hist[-1].get("hash") == snap.get("hash"): return
    hist.append(snap)
    if len(hist) > max_keep: hist = hist[-max_keep:]
    st.session_state.rev_snapshots = hist

def _rev_find_at(history, current_ts, seconds_ago):
    if not history: return None
    target = current_ts - dt_mod.timedelta(seconds=seconds_ago)
    best, best_d = None, None
    for s in history:
        d = abs((s["ts"] - target).total_seconds())
        if best_d is None or d < best_d: best, best_d = s, d
    if best and best_d is not None and best_d <= max(15, seconds_ago * 0.5): return best
    return None

def _rev_baseline(history, field, lookback, exclude_last=1):
    if not history or len(history) < lookback + exclude_last: return None, None
    vals = [s[field] for s in history[-(lookback + exclude_last):-exclude_last] if s.get(field) is not None]
    if len(vals) < 2: return None, None
    arr = np.array(vals, dtype=float)
    return float(arr.mean()), float(arr.std(ddof=1))

def _rev_is_anomaly(value, mean, std, z_thr, min_abs):
    if mean is None or std is None: return False
    if abs(value - mean) < min_abs: return False
    if std <= 0: return abs(value - mean) >= min_abs
    return abs((value - mean) / std) >= z_thr

def _rev_detect_anomalies(history, params):
    out = {"any": False, "ce_unwind": False, "ce_build": False,
           "pe_unwind": False, "pe_build": False, "imb_flip": False, "reasons": []}
    if len(history) < 3: return out
    cur = history[-1]; look = params["lookback"]; min_abs = params["min_abs_contracts"]
    ce_mean, ce_std = _rev_baseline(history, "ce", look)
    pe_mean, pe_std = _rev_baseline(history, "pe", look)
    if _rev_is_anomaly(cur["ce"], ce_mean, ce_std, params["z"], min_abs):
        if cur["ce"] < ce_mean:
            out["ce_unwind"] = True
            out["reasons"].append(f"CE ΔOI dropping (anomaly) — {_fmt_oi_units(cur['ce'])} vs baseline {_fmt_oi_units(ce_mean)}")
        else:
            out["ce_build"] = True
            out["reasons"].append(f"CE ΔOI building (anomaly) — {_fmt_oi_units(cur['ce'])} vs baseline {_fmt_oi_units(ce_mean)}")
    if _rev_is_anomaly(cur["pe"], pe_mean, pe_std, params["z"], min_abs):
        if cur["pe"] > pe_mean:
            out["pe_build"] = True
            out["reasons"].append(f"PE ΔOI building (anomaly) — {_fmt_oi_units(cur['pe'])} vs baseline {_fmt_oi_units(pe_mean)}")
        else:
            out["pe_unwind"] = True
            out["reasons"].append(f"PE ΔOI unwinding (anomaly) — {_fmt_oi_units(cur['pe'])} vs baseline {_fmt_oi_units(pe_mean)}")
    if len(history) >= 6:
        rec = [s["imb"] for s in history[-3:]]; ear = [s["imb"] for s in history[-6:-3]]
        if ear and rec:
            em = float(np.mean(ear)); rm = float(np.mean(rec))
            if em * rm < 0:
                out["imb_flip"] = True
                out["reasons"].append(f"CE−PE imbalance flipped sign: {em:+.0f} → {rm:+.0f}")
    out["any"] = any([out["ce_unwind"], out["ce_build"], out["pe_unwind"], out["pe_build"], out["imb_flip"]])
    return out

def _rev_bearish_score(history, anomalies):
    if len(history) < 3: return 0, [], ["Insufficient history"], None, None, None, None
    cur = history[-1]; ref = _rev_find_at(history, cur["ts"], 60)
    score = 0; reasons, missing = [], []
    if anomalies["ce_unwind"]: score += 20; reasons.append("CE ΔOI unwinding anomalously")
    else: missing.append("No CE ΔOI unwinding anomaly")
    if anomalies["pe_build"]: score += 20; reasons.append("PE ΔOI building anomalously")
    else: missing.append("No PE ΔOI buildup anomaly")
    if cur["pe"] > cur["ce"] * 1.1:
        score += 15; reasons.append(f"PE ΔOI dominance ({_fmt_oi_units(cur['pe'])} vs {_fmt_oi_units(cur['ce'])})")
    else: missing.append("PE ΔOI not dominant")
    if ref:
        d = cur["spot"] - ref["spot"]
        if d < -5: score += 15; reasons.append(f"Nifty down {d:+.1f} pts (~1 min)")
        else: missing.append("Nifty not falling")
    else: missing.append("Need ~1 min price history")
    if anomalies["imb_flip"]: score += 15; reasons.append("CE−PE imbalance flipped")
    else: missing.append("No imbalance flip")
    if ref and ref.get("pcr") is not None and cur.get("pcr") is not None:
        dp = cur["pcr"] - ref["pcr"]
        if dp < -0.02: score += 15; reasons.append(f"PCR falling {dp:+.3f}")
        else: missing.append("PCR not falling")
    else: missing.append("PCR history unavailable")
    score = max(0, min(100, score)); spot = cur["spot"]
    return (score, reasons, missing,
            spot - 5 if spot else None, spot + 30 if spot else None,
            spot + 15 if spot else None, 2.0 if score >= 60 else None)

def _rev_bullish_score(history, anomalies):
    if len(history) < 3: return 0, [], ["Insufficient history"], None, None, None, None
    cur = history[-1]; ref = _rev_find_at(history, cur["ts"], 60)
    score = 0; reasons, missing = [], []
    if anomalies["pe_unwind"]: score += 20; reasons.append("PE ΔOI unwinding anomalously")
    else: missing.append("No PE ΔOI unwinding anomaly")
    if anomalies["ce_build"]: score += 20; reasons.append("CE ΔOI building anomalously")
    else: missing.append("No CE ΔOI buildup anomaly")
    if cur["ce"] > cur["pe"] * 1.1:
        score += 15; reasons.append(f"CE ΔOI dominance ({_fmt_oi_units(cur['ce'])} vs {_fmt_oi_units(cur['pe'])})")
    else: missing.append("CE ΔOI not dominant")
    if ref:
        d = cur["spot"] - ref["spot"]
        if d > 5: score += 15; reasons.append(f"Nifty up {d:+.1f} pts (~1 min)")
        else: missing.append("Nifty not rising")
    else: missing.append("Need ~1 min price history")
    if anomalies["imb_flip"]: score += 15; reasons.append("CE−PE imbalance flipped")
    else: missing.append("No imbalance flip")
    if ref and ref.get("pcr") is not None and cur.get("pcr") is not None:
        dp = cur["pcr"] - ref["pcr"]
        if dp > 0.02: score += 15; reasons.append(f"PCR rising {dp:+.3f}")
        else: missing.append("PCR not rising")
    else: missing.append("PCR history unavailable")
    score = max(0, min(100, score)); spot = cur["spot"]
    return (score, reasons, missing,
            spot + 5 if spot else None, spot - 30 if spot else None,
            spot - 15 if spot else None, 2.0 if score >= 60 else None)

def _rev_push_alert(kind, msg, cooldown_sec):
    now_ts = datetime.now(ist).timestamp()
    cooldowns = st.session_state.get("rev_cooldowns", {})
    if now_ts - cooldowns.get(kind, 0) < cooldown_sec: return False
    cooldowns[kind] = now_ts
    st.session_state.rev_cooldowns = cooldowns
    alerts = st.session_state.get("rev_alerts", [])
    alerts.append({"ts": datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S"), "type": kind, "msg": msg})
    st.session_state.rev_alerts = alerts[-200:]
    return True

def _rev_label(score):
    if score >= 75: return "🟢 STRONG CONFIRMATION", "#2e7d32"
    if score >= 60: return "🟡 SETUP DEVELOPING", "#f9a825"
    if score >= 40: return "🟠 WATCH", "#ef6c00"
    return "⚪ NO CONFIRMATION", "#6e7781"

def rev_render_meter(params, change_oi_resp, oi_resp, spot_price):
    st.markdown("---")
    st.subheader("🔄 Change-in-OI Reversal Meter")
    st.caption(f"Sampling every **5 s** — last snapshot at **{datetime.now(ist).strftime('%H:%M:%S')} IST** "
               f"| Spot **{spot_price:,.2f}**")
    if spot_price <= 0:
        st.info("ℹ️ Live Nifty price not available — reversal meter paused.")
        return
    snap = _rev_capture_snapshot(change_oi_resp, oi_resp, spot_price, params["window_strikes"])
    if snap is None:
        st.info("ℹ️ Change-in-OI data not available — reversal meter paused.")
        return
    _rev_add_snapshot(snap)
    history = st.session_state.get("rev_snapshots", [])
    if len(history) < 2:
        st.info(f"⏳ Collecting snapshots ({len(history)}/2). Will activate shortly...")
        agg = _rev_aggregate_change_oi(change_oi_resp, spot_price, params["window_strikes"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total CE ΔOI", _fmt_oi_units(agg["ce"]))
        c2.metric("Total PE ΔOI", _fmt_oi_units(agg["pe"]))
        c3.metric("CE − PE", _fmt_oi_units(agg["ce"] - agg["pe"]))
        c4.metric("Strikes aggregated", agg["n"])
        return
    cur = history[-1]
    prev = history[-2] if len(history) >= 2 else None
    anomalies = _rev_detect_anomalies(history, params)
    bear_score, bear_reasons, bear_missing, bear_trig, bear_inval, bear_sl, bear_rr = _rev_bearish_score(history, anomalies)
    bull_score, bull_reasons, bull_missing, bull_trig, bull_inval, bull_sl, bull_rr = _rev_bullish_score(history, anomalies)
    if anomalies["any"]:
        if bear_score >= 60 and (anomalies["ce_unwind"] or anomalies["pe_build"]):
            _rev_push_alert("bearish_setup",
                            f"Bearish setup {bear_score:.0f}/100 — {bear_reasons[0] if bear_reasons else 'OI shift'}",
                            params["cooldown_sec"])
        if bull_score >= 60 and (anomalies["pe_unwind"] or anomalies["ce_build"]):
            _rev_push_alert("bullish_setup",
                            f"Bullish setup {bull_score:.0f}/100 — {bull_reasons[0] if bull_reasons else 'OI shift'}",
                            params["cooldown_sec"])

    st.markdown("#### 📊 Aggregate Change-in-OI (Cumulative vs Snapshot Δ)")
    d_ce = (cur["ce"] - prev["ce"]) if prev else None
    d_pe = (cur["pe"] - prev["pe"]) if prev else None
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total CE ΔOI", _fmt_oi_units(cur["ce"]),
              delta=_fmt_oi_units(d_ce) if d_ce is not None else None,
              help="Cumulative exchange-reported CE change-in-OI. Δ = change since previous snapshot.")
    c2.metric("Total PE ΔOI", _fmt_oi_units(cur["pe"]),
              delta=_fmt_oi_units(d_pe) if d_pe is not None else None,
              help="Cumulative exchange-reported PE change-in-OI. Δ = change since previous snapshot.")
    imb = cur["ce"] - cur["pe"]
    c3.metric("CE − PE Imbalance", _fmt_oi_units(imb))
    if prev:
        prev_imb = prev["imb"]
        pct_imb = ((imb - prev_imb) / abs(prev_imb) * 100) if prev_imb != 0 else None
        c4.metric("Imbalance Δ%", f"{pct_imb:+.1f}%" if pct_imb is not None else "—")
    else:
        c4.metric("Imbalance Δ%", "—")

    dominant, gauge_val = "NEUTRAL", 0
    if bear_score > bull_score and bear_score >= 40: dominant, gauge_val = "BEARISH", -bear_score
    elif bull_score > bear_score and bull_score >= 40: dominant, gauge_val = "BULLISH", bull_score
    if PLOTLY_AVAILABLE:
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=gauge_val,
            number={'font': {'size': 26}},
            title={'text': f"{dominant} pressure", 'font': {'size': 16}},
            gauge={'axis': {'range': [-100, 100], 'tickwidth': 1}, 'bar': {'color': '#1a1a1a'},
                   'steps': [
                       {'range': [-100, -75], 'color': '#c62828'},
                       {'range': [-75, -40],  'color': '#ef6c00'},
                       {'range': [-40, -15],  'color': '#ffe082'},
                       {'range': [-15, 15],   'color': '#e0e0e0'},
                       {'range': [15, 40],    'color': '#c8e6c9'},
                       {'range': [40, 75],    'color': '#66bb6a'},
                       {'range': [75, 100],   'color': '#2e7d32'},
                   ],
                   'threshold': {'line': {'color': 'black', 'width': 3}, 'thickness': 0.8, 'value': gauge_val}},
        ))
        fig.update_layout(height=240, margin=dict(l=20, r=20, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.markdown(f"**Directional Gauge**: {'🔴 Bearish' if gauge_val < 0 else '🟢 Bullish' if gauge_val > 0 else '⚪ Neutral'} (score {gauge_val:+.0f}/100)")

    st.markdown("#### 🕒 Multi-Interval Change Detection")
    intervals = [(30, "30 sec"), (60, "1 min"), (180, "3 min"), (300, "5 min")]
    rows = []
    for sec, label in intervals:
        ref = _rev_find_at(history, cur["ts"], sec)
        if not ref:
            rows.append({"Window": label, "Spot Δ": "—", "CE ΔOI Δ": "—", "PE ΔOI Δ": "—",
                         "Imbalance Δ": "—", "Rate (Δ/min)": "—"}); continue
        actual_sec = max(1.0, (cur["ts"] - ref["ts"]).total_seconds())
        scale = 60.0 / actual_sec
        spot_delta = cur["spot"] - ref["spot"]
        ce_delta = cur["ce"] - ref["ce"]; pe_delta = cur["pe"] - ref["pe"]
        imb_delta = cur["imb"] - ref["imb"]
        rate = (pe_delta - ce_delta) * scale
        rows.append({"Window": label, "Spot Δ": f"{spot_delta:+.1f}",
                     "CE ΔOI Δ": _fmt_oi_units(ce_delta),
                     "PE ΔOI Δ": _fmt_oi_units(pe_delta),
                     "Imbalance Δ": _fmt_oi_units(imb_delta),
                     "Rate (Δ/min)": _fmt_oi_units(rate)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
    st.caption("ΔOI Δ = change in *cumulative* change-in-OI between the two snapshots. "
               "Rate = scale-normalised net PE−CE change per minute.")

    if anomalies["any"]:
        st.warning("**⚡ OI Reversal Anomalies Detected:**\n\n" + "\n".join(f"- {r}" for r in anomalies["reasons"]))
    else:
        st.info("No statistical OI reversal anomalies detected in the latest snapshot.")

    st.markdown("#### 🎯 Rule-Based Setup Scores")
    cA, cB = st.columns(2)

    def score_card(col, title, score, reasons, missing, trig, inval, sl, rr, bearish=True):
        label, color = _rev_label(score)
        border = "#c62828" if bearish else "#2e7d32"
        with col:
            st.markdown(
                f'<div class="rev-card" style="border-left-color:{border};">'
                f'<div class="rev-title">{title} <span class="rev-pill rev-pill-gray">{label}</span></div>'
                f'<div style="font-size:1.6rem; font-weight:800; margin:6px 0; color:{color};">{score:.0f}/100</div>'
                f'<div class="rev-sub"><b>Reasons:</b><br>' +
                ("".join(f"✅ {r}<br>" for r in reasons) if reasons else "—") +
                f'<br><b>Missing:</b><br>' +
                ("".join(f"⭕ {m}<br>" for m in missing[:4]) if missing else "—") +
                (f'<br><b>Trigger:</b> {trig:,.1f}' if trig else '') +
                (f'<br><b>Invalidation:</b> {inval:,.1f}' if inval else '') +
                (f'<br><b>SL ref:</b> {sl:,.1f} &nbsp;|&nbsp; R:R ≈ {rr:.1f}' if sl and rr else '') +
                '</div></div>', unsafe_allow_html=True)

    score_card(cA, "🔴 BEARISH (PE) Setup", bear_score, bear_reasons, bear_missing,
               bear_trig, bear_inval, bear_sl, bear_rr, bearish=True)
    score_card(cB, "🟢 BULLISH (CE) Setup", bull_score, bull_reasons, bull_missing,
               bull_trig, bull_inval, bull_sl, bull_rr, bearish=False)
    st.caption("⚠️ Decision-support only. Scores are heuristic, not probabilities. "
               "Validate against price action, liquidity and historical performance before taking a trade.")

    if PLOTLY_AVAILABLE and len(history) >= 3:
        st.markdown("#### 📈 Charts")
        ts_list = [s["ts"] for s in history]
        ce_list = [s["ce"] for s in history]; pe_list = [s["pe"] for s in history]
        imb_list = [s["imb"] for s in history]; spot_list = [s["spot"] for s in history]
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=ts_list, y=ce_list, mode="lines", name="CE ΔOI",
                                  line=dict(color="#c62828", width=2)))
        fig1.add_trace(go.Scatter(x=ts_list, y=pe_list, mode="lines", name="PE ΔOI",
                                  line=dict(color="#2e7d32", width=2)))
        fig1.update_layout(title="Cumulative CE vs PE Change-in-OI", height=300,
                           margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h"))
        st.plotly_chart(fig1, use_container_width=True)
        fig2 = make_subplots(specs=[[{"secondary_y": True}]])
        fig2.add_trace(go.Bar(x=ts_list, y=imb_list, name="CE−PE Imbalance",
                              marker_color=["#c62828" if v < 0 else "#2e7d32" for v in imb_list],
                              opacity=0.5), secondary_y=False)
        fig2.add_trace(go.Scatter(x=ts_list, y=spot_list, mode="lines", name="Nifty Spot",
                                  line=dict(color="#1e88e5", width=2)), secondary_y=True)
        fig2.update_layout(title="CE−PE Imbalance vs Nifty Spot", height=300,
                           margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h"))
        fig2.update_yaxes(title_text="Imbalance (contracts)", secondary_y=False)
        fig2.update_yaxes(title_text="Nifty", secondary_y=True)
        st.plotly_chart(fig2, use_container_width=True)
        if len(history) >= 2:
            v_ce, v_pe = [], []; prev_s = history[0]
            for s in history:
                dt_sec = max(1.0, (s["ts"] - prev_s["ts"]).total_seconds())
                v_ce.append((s["ce"] - prev_s["ce"]) * (60.0 / dt_sec))
                v_pe.append((s["pe"] - prev_s["pe"]) * (60.0 / dt_sec))
                prev_s = s
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=ts_list, y=v_ce, mode="lines", name="CE velocity /min",
                                      line=dict(color="#c62828", width=2)))
            fig3.add_trace(go.Scatter(x=ts_list, y=v_pe, mode="lines", name="PE velocity /min",
                                      line=dict(color="#2e7d32", width=2)))
            fig3.update_layout(title="OI Velocity (ΔOI change per minute)", height=280,
                               margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h"))
            st.plotly_chart(fig3, use_container_width=True)

    alerts = st.session_state.get("rev_alerts", [])
    with st.expander(f"🔔 Alert log ({len(alerts)} entries)", expanded=False):
        if not alerts: st.caption("No alerts recorded yet.")
        else:
            for a in reversed(alerts[-30:]):
                cls = "rev-alert-bear" if "bear" in a["type"] else ("rev-alert-bull" if "bull" in a["type"] else "rev-alert-neutral")
                # Added explicit color:#000000 inline to guarantee visibility in Dark Mode
                st.markdown(f'<div class="rev-alert-item {cls}" style="color: #000000;"><b>{a["ts"]}</b> — {a["msg"]}</div>',
                            unsafe_allow_html=True)

    with st.expander("🧪 Quick backtest summary (recorded snapshots only)", expanded=False):
        if len(history) < 10:
            st.info(f"Need more history. Collected {len(history)} snapshots so far.")
        else:
            hits_bear = 0; total_bear = 0; hits_bull = 0; total_bull = 0
            for i in range(4, len(history) - 4):
                sub = history[:i+1]
                an = _rev_detect_anomalies(sub, params)
                if not an["any"]: continue
                bs, *_ = _rev_bearish_score(sub, an)
                ls, *_ = _rev_bullish_score(sub, an)
                fut = history[i+4]
                spot_now = sub[-1]["spot"]; spot_fut = fut["spot"]
                if bs >= 60:
                    total_bear += 1
                    if spot_fut < spot_now: hits_bear += 1
                if ls >= 60:
                    total_bull += 1
                    if spot_fut > spot_now: hits_bull += 1
            st.write(f"**Bearish signals**: {total_bear} (hit rate {hits_bear/max(1,total_bear)*100:.0f}%)")
            st.write(f"**Bullish signals**: {total_bull} (hit rate {hits_bull/max(1,total_bull)*100:.0f}%)")
            st.caption("Hit = Nifty moved in the predicted direction within ~1 min (4 snapshots). "
                       "Excludes brokerage/taxes/slippage. Not a profit guarantee.")

# Build params from sidebar settings
rev_params = {
    "window_strikes": rev_window_strikes,
    "lookback": rev_lookback,
    "z": rev_z_threshold,
    "min_abs_contracts": rev_min_abs_lakh * 1_00_000,
    "cooldown_sec": rev_cooldown_min * 60,
}

# ---- Fragment: 5-second reversal sampler ----
def _rev_fragment_body():
    try:
        c_oi = _sampled_change_oi('NSE_INDEX|Nifty 50', expiry_str, today_str)
    except Exception as e:
        st.error(f"Reversal meter: change-OI fetch failed — {e}")
        return
    try:
        oi_r = _sampled_oi('NSE_INDEX|Nifty 50', expiry_str, today_str)
    except Exception:
        oi_r = None
    spot = _sampled_spot()
    if not spot: spot = nifty_price
    rev_render_meter(rev_params, c_oi, oi_r, spot)

if _FRAGMENT_SUPPORTED:
    @_frag(run_every=5)
    def _run_rev_fragment():
        _rev_fragment_body()
else:
    def _run_rev_fragment():
        _rev_fragment_body()

# ==============================
# UI RENDER
# ==============================
st.title("🔮 Nifty Analytics & Strategy Suite — Pro")
entry_datetime = nifty_gate["time_label"]

if divergence_detected:
    st.markdown(f'<div class="divergence-alert">{divergence_msg}</div>', unsafe_allow_html=True)
if vix_warning:
    st.markdown(f'<div class="vix-alert">{vix_warning}</div>', unsafe_allow_html=True)

render_oi_meter(nifty_meter, "Nifty", nifty_price)

st.subheader("📊 Code 1 — Nifty OI Change Entry Signal")
render_gate_panel(nifty_gate, "Nifty")
if nifty_entry_signal:
    signal = nifty_entry_signal["signal"]; active = nifty_entry_signal["active"]
    emoji = "🟢" if signal == "BUY" else "🔴"
    status_text = entry_status_text(nifty_entry_signal)
    if active and signal == "BUY": bg_color = "#2e7d32"; text_color = "white"
    elif active and signal == "SELL": bg_color = "#c62828"; text_color = "white"
    else: bg_color = "#f9a825"; text_color = "black"
    border_color = "#2e7d32" if signal == "BUY" else "#c62828"
    st.markdown(f"""
    <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <span style="font-size: 1.8rem; font-weight: 800;">{emoji} {signal} ENTRY</span>
                <span style="margin-left: 15px; font-size: 1.2rem;">at {nifty_entry_signal['trigger_price']:,.2f}</span>
                <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{nifty_entry_signal['high_type']}</span>
            </div>
            <div style="font-weight: bold;">
                <span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span>
                <span style="margin-left: 20px; font-size: 0.9rem;">⏱ {entry_datetime}</span>
            </div>
        </div>
        <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;">
            <span>📊 Current Nifty: <b>{nifty_price:,.2f}</b> &nbsp;|&nbsp; Key Strike: <b>{nifty_entry_signal['strike']}</b> &nbsp;|&nbsp; OI Diff: <b>{nifty_entry_signal['oi_diff']:,.0f}</b></span>
            <span style="margin-left: 20px;">📌 {nifty_entry_signal['reason']}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    render_greeks_panel(nifty_entry_signal, "Nifty Entry")
else:
    st.info("ℹ️ No Nifty Change OI entry signal (gap < 100 pts or no opposite OI).")

st.subheader("📊 Code 1 — Nifty OI Change Exit Signal")
if nifty_exit_signal:
    signal = nifty_exit_signal["signal"]; active = nifty_exit_signal["active"]
    emoji = "🟢" if signal == "BUY" else "🔴"
    status_text = "🎯 TARGET REACHED" if active else "PENDING — target not reached yet"
    bg_color = "#2e7d32" if active and signal=="BUY" else ("#c62828" if active and signal=="SELL" else "#f9a825")
    text_color = "white" if active else "black"
    border_color = "#0277bd" if signal=="BUY" else "#d84315"
    st.markdown(f"""
    <div class="entry-box" style="background: {bg_color}; border-left-color: {border_color}; color: {text_color};">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <span style="font-size: 1.8rem; font-weight: 800;">{emoji} EXIT ({'BUY to cover' if signal=='BUY' else 'SELL to close'})</span>
                <span style="margin-left: 15px; font-size: 1.2rem;">at {nifty_exit_signal['trigger_price']:,.2f}</span>
                <span style="margin-left: 15px; background: rgba(0,0,0,0.15); padding: 2px 10px; border-radius: 20px;">{nifty_exit_signal['high_type']}</span>
            </div>
            <div style="font-weight: bold;">
                <span class="status-text" style="background: rgba(0,0,0,0.3); padding: 2px 10px; border-radius: 8px;">{status_text}</span>
                <span style="margin-left: 20px; font-size: 0.9rem;">Updated: {updated_datetime}</span>
            </div>
        </div>
        <div style="margin-top: 8px; font-size: 0.95rem; opacity: 0.9;">
            <span>📊 Current Nifty: <b>{nifty_price:,.2f}</b> &nbsp;|&nbsp; Key Strike: <b>{nifty_exit_signal['strike']}</b> &nbsp;|&nbsp; OI Diff: <b>{nifty_exit_signal['oi_diff']:,.0f}</b></span>
            <span style="margin-left: 20px;">📌 {nifty_exit_signal['reason']}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    render_greeks_panel(nifty_exit_signal, "Nifty Exit")
else:
    st.info("ℹ️ No Nifty exit signal available (opposite OI build-up not found or gap < 100 pts).")

# ===== NEW: Reversal Meter (independent 5 s sampler) =====
if rev_enabled:
    _run_rev_fragment()

# ---- Nifty OI Data ----
reusable_display_oi_data(upstoxOiResponse, "Nifty Open Interest Data")
reusable_display_oi_data(upstoxOiChangeResponse, "Nifty Change in OI")

# ---- Nifty OI Flow ----
if nifty_flow_result["rows"]:
    st.subheader(f"{nifty_flow_result['title']} — Macro Score: {nifty_flow_result['score']:.2f}")
    st.markdown("**Weighted Macro Score (-1 to +1)**: Based on absolute turnover and price change across top traded futures.")
    indicator = "Bullish" if nifty_flow_result["score"] > 0 else ("Bearish" if nifty_flow_result["score"] < 0 else "Sideways")
    st.write(f"Market Bias: {indicator}")
    st.dataframe(pd.DataFrame(nifty_flow_result["rows"]))
else:
    st.info("No Nifty futures met the turnover threshold right now.")
