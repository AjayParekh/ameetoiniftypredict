import streamlit as st
import requests
import pandas as pd
from datetime import datetime, time, timedelta
import datetime as dt_mod
import os
import pytz
from streamlit_autorefresh import st_autorefresh
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import warnings
warnings.filterwarnings('ignore')
import requests
import json

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
    .market-box {
        background-color: white;
        padding: 18px;
        border-radius: 12px;
        border: 1px solid #e1e4e8;
        box-shadow: 0px 4px 10px rgba(0,0,0,0.03);
        margin-bottom: 15px;
    }
    .prediction-box {
        background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
        color: white;
        padding: 20px;
        border-radius: 15px;
        text-align: center;
        margin-bottom: 15px;
        position: relative;
    }
    .prediction-achieved { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%) !important; }
    .confidence-tag {
        background: rgba(255,255,255,0.2);
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.9rem;
        font-weight: bold;
        display: inline-block;
        margin-top: 10px;
        border: 1px solid rgba(255,255,255,0.3);
    }
    .divergence-alert {
        background-color: #f8d7da; color: #721c24;
        padding: 12px 20px; border-radius: 10px;
        border-left: 5px solid #dc3545;
        margin-bottom: 20px; font-weight: bold;
        font-size: 1.05rem; box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .vix-alert {
        background-color: #fff3cd; color: #856404;
        padding: 10px 20px; border-radius: 10px;
        border-left: 5px solid #ffc107;
        margin-bottom: 15px; font-weight: bold;
    }
    .status-badge {
        position: absolute; top: 10px; right: 15px;
        background: rgba(255,255,255,0.25); color: white;
        padding: 2px 10px; border-radius: 8px;
        font-size: 0.75rem; font-weight: bold; text-transform: uppercase;
    }
    .prediction-card {
        padding: 30px; border-radius: 20px;
        text-align: center; color: white;
        margin-bottom: 15px; position: relative;
    }
    .bullish  { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .bearish  { background: linear-gradient(135deg, #cb2d3e 0%, #ef473a 100%); }
    .weak-bullish { background: linear-gradient(135deg, #2d6a4f 0%, #52b788 100%); }
    .weak-bearish { background: linear-gradient(135deg, #7b2d00 0%, #c05c2a 100%); }
    .neutral  { background: linear-gradient(135deg, #2c3e50 0%, #4ca1af 100%); }
    .no-data  { background: linear-gradient(135deg, #5c5c5c 0%, #8a8a8a 100%); }
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
    .signal-score-bar {
        background: rgba(255,255,255,0.15);
        border-radius: 8px; padding: 8px 16px;
        margin-top: 10px; font-size: 0.95rem;
        display: inline-block;
    }
    .indicator-row {
        display: flex; gap: 10px; flex-wrap: wrap;
        margin-bottom: 12px;
    }
    .indicator-pill {
        padding: 4px 12px; border-radius: 20px;
        font-size: 0.8rem; font-weight: 600;
        border: 1px solid rgba(0,0,0,0.08);
    }
    .pill-green  { background:#d4edda; color:#155724; }
    .pill-red    { background:#f8d7da; color:#721c24; }
    .pill-yellow { background:#fff3cd; color:#856404; }
    .pill-gray   { background:#e9ecef; color:#495057; }
    .momentum-badge {
        display: inline-block; padding: 3px 12px; border-radius: 15px;
        font-size: 0.8rem; font-weight: bold; margin-left: 8px;
    }
    </style>
""", unsafe_allow_html=True)

# ==============================
# GLOBAL CONFIG & TIMING
# ==============================
st_autorefresh(interval=15_000, key="global_sync_refresh")
ist = pytz.timezone("Asia/Kolkata")
now = datetime.now(ist)
today = now.strftime("%Y-%m-%d")

CHINA_CLOSE_TIME = time(12, 30)
is_after_china = now.time() >= CHINA_CLOSE_TIME

# ==============================
# CODE 3 — OI / UPSTOX CONFIG (REWRITTEN SECTION)
# ==============================
# Token now comes from Streamlit secrets, never hardcoded in source.
# Add this to your Streamlit Cloud app secrets (Settings -> Secrets):
#
#   UPSTOX_TOKEN = "eyJ0eXAiOiJKV1Qi..."
#
UPSTOX_TOKEN = st.secrets.get("eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIxMDM2NjciLCJqdGkiOiI2OWQyMzJlMWNjZDUyZDRjZDQzMzc5NjYiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc3NTM4MzI2NSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODA2OTYyNDAwfQ.VFRZ5NP87NM1Vyn4-bCB2FAvanu4wsueNHo_POQtPv8", None)
UPSTOX_OI_URL = "https://api.upstox.com/v2/market/oi"
NIFTY_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"


def get_nearest_weekly_expiry(reference_dt):
    """
    Computes the nearest upcoming Nifty weekly options expiry (Thursday).
    If 'today' is already Thursday but past market close (15:30 IST),
    rolls forward to next week's Thursday.

    NOTE: This does not account for exchange holiday-shifted expiries
    (e.g. expiry moved to Wednesday due to a Thursday holiday). If NSE
    shifts an expiry, override manually via the sidebar date input below.
    """
    days_ahead = (3 - reference_dt.weekday()) % 7  # Thursday == weekday() 3
    candidate = reference_dt + timedelta(days=days_ahead)

    market_close = dt_mod.time(15, 30)
    if days_ahead == 0 and reference_dt.time() > market_close:
        candidate = candidate + timedelta(days=7)

    return candidate.date()


def fetch_oi_data(expiry_date_str, trade_date_str, token):
    """
    Fetches option chain OI data from Upstox.
    Returns (data_dict, error_message). On any failure, data_dict is None
    and error_message explains why, so the caller can render a graceful
    fallback instead of crashing the whole app.
    """
    if not token:
        return None, "UPSTOX_TOKEN not found in Streamlit secrets."

    params = {
        "instrument_key": NIFTY_INSTRUMENT_KEY,
        "expiry": expiry_date_str,
        "date": trade_date_str,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    try:
        resp = requests.get(UPSTOX_OI_URL, params=params, headers=headers, timeout=8)
    except requests.exceptions.RequestException as e:
        return None, f"Network error reaching Upstox: {e}"

    if resp.status_code != 200:
        return None, f"Upstox returned HTTP {resp.status_code}: {resp.text[:200]}"

    try:
        payload = resp.json()
    except ValueError:
        return None, "Upstox response was not valid JSON."

    if payload.get("status") != "success":
        return None, f"Upstox status was '{payload.get('status')}', not 'success'."

    inner = payload.get("data")
    if not inner or not inner.get("call_put_oi_data_list"):
        return None, "Upstox returned no OI rows for this expiry/date (market closed, holiday, or wrong contract)."

    return inner, None


# Sidebar override in case the auto-picked Thursday is wrong (holiday shift, etc.)
with st.sidebar:
    st.markdown("---")
    st.markdown("#### 📅 Code 3 — Option Chain Expiry")
    auto_expiry = get_nearest_weekly_expiry(now)
    expiry_override = st.date_input(
        "Expiry date (auto-picked, override if NSE shifted it)",
        value=auto_expiry,
        key="oi_expiry_override",
    )
    expiry_str = expiry_override.strftime("%Y-%m-%d")

oi_raw_data, oi_fetch_error = fetch_oi_data(expiry_str, today, UPSTOX_TOKEN)

# ==============================
# (GitHub-based paper trade persistence removed per request —
#  this app is now pure live prediction display, no trade logging,
#  no GitHub read/write, no secrets needed for this part.)
# ==============================

# ==============================
# SIDEBAR
# ==============================
with st.sidebar:
    st.title("🎯 Predictor Settings")
    st.sidebar.markdown(f"### 🕒 IST: {now.strftime('%H:%M:%S')}")

    st.markdown("#### Code 1 — Global Weights")
    w_gift    = st.slider("GIFT Nifty",     0.0, 1.0, 0.35, 0.05, key="w_gift")
    w_sgx     = st.slider("BankNifty Fut Weight", 0.0, 1.0, 0.25, 0.05, key="w_sgx")
    w_nasdaq  = st.slider("Nasdaq 100",     0.0, 1.0, 0.15, 0.05, key="w_nasdaq")
    w_dax     = st.slider("DAX",            0.0, 1.0, 0.10, 0.05, key="w_dax")
    w_dxy     = st.slider("Dollar Index",  -1.0, 0.0,-0.10, 0.05, key="w_dxy")
    w_usdinr  = st.slider("USD/INR",       -1.0, 0.0,-0.10, 0.05, key="w_usdinr")
    w_hangseng= st.slider("Hang Seng",      0.0, 1.0, 0.05, 0.05, key="w_hangseng")

    st.markdown("---")
    st.markdown("#### VIX Filter")
    vix_threshold = st.slider("VIX Danger Level", 15.0, 35.0, 20.0, 0.5, key="vix_thresh")
    vix_dampener  = st.slider("VIX Dampening Factor", 0.0, 1.0, 0.5, 0.05, key="vix_damp")

    st.markdown("---")
    st.markdown("#### Code 2 — Signal Gate")
    min_signal_score = st.slider("Min Signal Score (0–5)", 0, 5, 3, 1, key="min_score")

    st.markdown("---")
    st.markdown("#### 🚀 Momentum Settings")
    momentum_lookback = st.slider("Momentum Lookback (min)", 5, 30, 15, 5, key="mom_lookback")
    momentum_threshold = st.slider("Momentum Threshold %", 0.1, 0.5, 0.25, 0.05, key="mom_thresh")

    if is_after_china:
        st.sidebar.success("China Logic: ACTIVE")
    else:
        st.sidebar.warning("Waiting for 12:30 PM IST")

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

def fetch_master_data(symbol_dict):
    payload = {
        "symbols": {"tickers": [symbol_dict["tv_symbol"]], "query": {"types": []}},
        "columns": ["close", "change", "change_abs"]
    }
    try:
        r = SESSION.post(TV_URL, json=payload, headers=HEADERS, timeout=5)
        d = r.json()["data"][0]["d"]
        close, pct, change_abs = d[0], d[1], d[2]
        prev_close = close - change_abs
        return symbol_dict, (round(prev_close, 2), round(close, 2), round(change_abs, 2), round(pct, 2))
    except:
        return symbol_dict, None

# ==============================
# ENHANCED PREDICTION FUNCTIONS  (CODE 1 — UNTOUCHED)
# ==============================

def detect_domestic_pressure(nifty_change_pct, sgx_pct, gift_pct, nifty_price, nifty_prev_close):
    """Advanced domestic pressure detection with multiple factors"""
    pressure_score = 0
    pressure_type = "ALIGNED"
    reasons = []
    
    # Factor 1: Price vs Futures divergence
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
                
    # Factor 2: Volume/Price relationship (simplified with price movement)
    if nifty_price > 0 and nifty_prev_close > 0:
        range_size = abs(nifty_price - nifty_prev_close) / nifty_prev_close * 100
        if range_size > 0.5 and pressure_type == "ALIGNED":
            if nifty_change_pct < -0.3:
                pressure_type = "STRONG_DOWN_MOMENTUM"
                pressure_score = abs(nifty_change_pct) * 2
                reasons.append(f"🔴 Strong downward momentum: {nifty_change_pct:+.2f}%")
            elif nifty_change_pct > 0.3:
                pressure_type = "STRONG_UP_MOMENTUM"
                pressure_score = abs(nifty_change_pct) * 2
                reasons.append(f"✅ Strong upward momentum: {nifty_change_pct:+.2f}%")
    
    return pressure_type, pressure_score, reasons

def calculate_momentum_score(nifty_price, nifty_prev_close, lookback_minutes=15):
    """Calculate momentum based on price action"""
    try:
        change_pct = ((nifty_price - nifty_prev_close) / nifty_prev_close) * 100 if nifty_prev_close > 0 else 0
        
        if change_pct < -0.5:
            momentum_score = -2
            momentum_label = "STRONG_BEARISH"
        elif change_pct < -0.25:
            momentum_score = -1
            momentum_label = "BEARISH"
        elif change_pct > 0.5:
            momentum_score = 2
            momentum_label = "STRONG_BULLISH"
        elif change_pct > 0.25:
            momentum_score = 1
            momentum_label = "BULLISH"
        else:
            momentum_score = 0
            momentum_label = "NEUTRAL"
            
        return momentum_score, momentum_label, change_pct
    except:
        return 0, "NEUTRAL", 0

def apply_domestic_override(sentiment_score, pressure_type, pressure_score, momentum_score):
    """Intelligent override based on domestic conditions"""
    override_factor = 0
    
    if "SELLING" in pressure_type:
        # Domestic selling overrides bullish sentiment
        if sentiment_score > 0:
            reduction = min(0.95, pressure_score * 0.15)
            adjusted_score = sentiment_score * (1 - reduction)
            override_factor = reduction
            return adjusted_score, f"🛑 Domestic Selling Override: {reduction:.0%} reduction"
        else:
            # Amplify bearish sentiment during selling
            amplification = min(1.5, 1 + pressure_score * 0.05)
            adjusted_score = sentiment_score * amplification
            return adjusted_score, f"⬇️ Bearish amplified: {amplification:.1f}x"
    
    elif "MOMENTUM" in pressure_type:
        # Strong momentum overrides global sentiment
        if pressure_type == "STRONG_DOWN_MOMENTUM" and sentiment_score > 0:
            reduction = min(0.9, 0.7 + abs(pressure_score) * 0.05)
            adjusted_score = sentiment_score * (1 - reduction)
            return adjusted_score, f"📉 Down Momentum Override: {reduction:.0%} reduction"
        elif pressure_type == "STRONG_UP_MOMENTUM" and sentiment_score < 0:
            reduction = min(0.9, 0.7 + abs(pressure_score) * 0.05)
            adjusted_score = sentiment_score * (1 - reduction)
            return adjusted_score, f"📈 Up Momentum Override: {reduction:.0%} reduction"
    
    return sentiment_score, "No override"

def calculate_confidence_score(weighted_pcts, vix_value, nifty_change_pct, pressure_type):
    """Enhanced confidence calculation"""
    if len(weighted_pcts) > 1:
        std_dev = np.std(weighted_pcts)
        base_confidence = max(0, min(100, 100 - (std_dev * 20)))
        
        # VIX adjustment
        vix_bonus = max(0, (20 - vix_value) * 0.5) if vix_value > 0 else 0
        
        # Domestic pressure adjustment - reduce confidence during divergence
        pressure_penalty = 0
        if "SELLING" in pressure_type and nifty_change_pct < -0.2:
            pressure_penalty = min(30, abs(nifty_change_pct) * 30)
        elif "BUYING" in pressure_type and nifty_change_pct > 0.2:
            pressure_penalty = min(30, abs(nifty_change_pct) * 30)
        
        confidence = min(100, base_confidence + vix_bonus - pressure_penalty)
        return confidence
    elif len(weighted_pcts) == 1:
        return 40.0
    return 0

# ==============================
# CODE 3 – OI BASED PREDICTOR (REWRITTEN: bug fixes + safety)
# ==============================

def compute_max_pain(oi_data, spot):
    """
    Fixed: the loop variable used to be named 'st', shadowing the
    Streamlit module import for the duration of this function. Renamed
    to 'strike_k' so it can never collide with st.* calls if this
    function is ever extended.
    """
    strikes = [item["strike_price"] for item in oi_data]
    best_strike = strikes[0]
    min_pain = float('inf')
    for s in strikes:
        total = 0.0
        for item in oi_data:
            strike_k = item["strike_price"]
            call_oi = item["call_oi"]
            put_oi = item["put_oi"]
            # intrinsic value at strike s
            total += call_oi * max(s - strike_k, 0) + put_oi * max(strike_k - s, 0)
        if total < min_pain:
            min_pain = total
            best_strike = s
    return best_strike

def compute_oi_signal(oi_data_list, spot_price):
    # total calls / puts
    total_calls = sum(item["call_oi"] for item in oi_data_list)
    total_puts = sum(item["put_oi"] for item in oi_data_list)
    pcr = total_puts / total_calls if total_calls > 0 else 1.0

    # max call OI strike (resistance) and max put OI strike (support)
    max_call_strike = max(oi_data_list, key=lambda x: x["call_oi"])["strike_price"]
    max_put_strike = max(oi_data_list, key=lambda x: x["put_oi"])["strike_price"]

    # max pain
    max_pain = compute_max_pain(oi_data_list, spot_price)

    # voting
    bull_votes = 0
    bear_votes = 0

    # 1. Max Pain direction
    if spot_price > max_pain:
        bear_votes += 1   # tend to move down
    elif spot_price < max_pain:
        bull_votes += 1   # tend to move up
    # else neutral

    # 2. PCR
    if pcr > 1.5:
        bear_votes += 1   # high puts -> bearish
    elif pcr < 0.7:
        bull_votes += 1   # low puts -> bullish

    # 3. Support/Resistance break
    if spot_price > max_call_strike:
        bull_votes += 1   # broke resistance
    elif spot_price < max_put_strike:
        bear_votes += 1   # broke support

    # direction
    if bull_votes > bear_votes:
        direction = "BULLISH"
    elif bear_votes > bull_votes:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    # target: max pain strike (or average of support/resistance if neutral)
    if direction == "BULLISH":
        target = max_pain if max_pain > spot_price else spot_price * 1.005
    elif direction == "BEARISH":
        target = max_pain if max_pain < spot_price else spot_price * 0.995
    else:
        target = (max_call_strike + max_put_strike) / 2

    # stop loss
    if direction == "BULLISH":
        stop_loss = min(spot_price * 0.995, max_put_strike)
    elif direction == "BEARISH":
        stop_loss = max(spot_price * 1.005, max_call_strike)
    else:
        stop_loss = spot_price

    # confidence: based on OI concentration and PCR extremeness
    oi_concentration = max(total_calls, total_puts) / (total_calls + total_puts + 1e-6)
    pcr_extreme = abs(pcr - 1.0) / 1.0
    confidence = min(100, 50 + 30 * oi_concentration + 20 * pcr_extreme)

    return {
        "direction": direction,
        "target": round(target, 2),
        "stop_loss": round(stop_loss, 2),
        "confidence": round(confidence, 1),
        "max_pain": round(max_pain, 2),
        "resistance": round(max_call_strike, 2),
        "support": round(max_put_strike, 2),
        "pcr": round(pcr, 2),
        "bull_votes": bull_votes,
        "bear_votes": bear_votes,
    }

# ==============================
# FETCH ALL DATA
# ==============================
with ThreadPoolExecutor(max_workers=len(master_symbols)) as executor:
    results = list(executor.map(fetch_master_data, master_symbols))

# ==============================
# PARSE RESULTS
# ==============================
weighted_pcts_c1  = []
sentiment_score_c1 = 0.0
trigger_pcts_c2   = []
final_display     = []
volatility_alerts = []

nifty_price = nifty_prev_close = 0.0
vix_value   = 0.0
usdinr_pct  = 0.0
china_pct   = 0.0
sgx_pct     = 0.0
gift_pct    = 0.0
hangseng_pct= 0.0
sp500_pct   = 0.0
nasdaq_pct  = 0.0
topix_pct   = 0.0

rows_c1 = []

for s, res in results:
    if res:
        prev, close, change, pct = res
        final_display.append({"s": s, "close": close, "pct": pct, "abs": change, "prev": prev})

        if s["name"] == "NIFTY 50":
            nifty_price, nifty_prev_close = close, prev
        elif s["name"] == "VIX":
            vix_value = close
        elif s["name"] == "USD/INR":
            usdinr_pct = pct
        elif s["name"] == "CSI 300":
            china_pct = pct
        elif s["name"] == "BankNifty Fut":
            sgx_pct = pct
        elif s["name"] == "GIFT Nifty":
            gift_pct = pct
        elif s["name"] == "Hang Seng":
            hangseng_pct = pct
        elif s["name"] == "S&P 500":
            sp500_pct = pct
        elif s["name"] == "Nasdaq 100":
            nasdaq_pct = pct
        elif s["name"] == "TOPIX":
            topix_pct = pct

        if s["w"] != 0:
            sentiment_score_c1 += pct * s["w"]
            weighted_pcts_c1.append(pct)

        if s["trigger_alignment"]:
            trigger_pcts_c2.append(pct)

        if abs(pct) >= 2.0:
            volatility_alerts.append(f"{s['icon']} {s['name']} moved {pct:+.2f}%")

        rows_c1.append([today, s["start"], s["end"], prev, s["market"], s["name"],
                        close, change, pct, "-", "-"])
    else:
        final_display.append({"s": s, "close": 0, "pct": 0, "abs": 0, "prev": 0})
        rows_c1.append([today, s["start"], s["end"], 0, s["market"], s["name"],
                        0, 0, 0, "-", "-"])

st.sidebar.write(f"**Nifty Prev Close:** {nifty_prev_close:,.2f}")

# ==============================
# ENHANCED CODE 1 — CALCULATIONS (UNTOUCHED)
# ==============================

# Calculate Nifty change metrics
nifty_change_pct = ((nifty_price - nifty_prev_close) / nifty_prev_close) * 100 if nifty_prev_close > 0 else 0
nifty_actual_change = nifty_price - nifty_prev_close

# Detect domestic pressure
pressure_type, pressure_score, pressure_reasons = detect_domestic_pressure(
    nifty_change_pct, sgx_pct, gift_pct, nifty_price, nifty_prev_close
)

# Calculate momentum
momentum_score, momentum_label, momentum_pct = calculate_momentum_score(
    nifty_price, nifty_prev_close, momentum_lookback
)

# VIX processing
vix_regime = "NORMAL"
vix_dampener_val = 1.0
vix_warning = ""

if vix_value > 0:
    if vix_value >= vix_threshold + 5:
        vix_regime = "EXTREME FEAR"
        vix_dampener_val = vix_dampener * 0.3
        vix_warning = f"🔴 VIX EXTREME: {vix_value:.1f} — Strong bearish overlay applied. Avoid fresh longs."
    elif vix_value >= vix_threshold:
        vix_regime = "ELEVATED"
        vix_dampener_val = vix_dampener
        vix_warning = f"🟡 VIX ELEVATED: {vix_value:.1f} — Bullish signals dampened. Trade smaller size."

raw_sentiment = sentiment_score_c1

# Apply VIX dampener
if raw_sentiment > 0 and vix_dampener_val < 1.0:
    sentiment_score_c1 = raw_sentiment * vix_dampener_val

# Apply domestic pressure override
sentiment_score_c1, override_note = apply_domestic_override(
    sentiment_score_c1, pressure_type, pressure_score, momentum_score
)

# Calculate confidence with domestic pressure
confidence = calculate_confidence_score(weighted_pcts_c1, vix_value, nifty_change_pct, pressure_type)

# Generate target
target_price_c1 = round(nifty_prev_close * (1 + (sentiment_score_c1 / 100)), 2) if nifty_prev_close > 0 else 0.0
pred_change_c1 = round(target_price_c1 - nifty_prev_close, 2)
pred_pct_c1 = round(sentiment_score_c1, 2)

# Enhanced prediction text with override
if sentiment_score_c1 > 0.5: 
    pred_text_c1 = "STRONG BULLISH 🚀" 
elif sentiment_score_c1 >= 0.1: 
    pred_text_c1 = "SLIGHTLY BULLISH 📈" 
elif sentiment_score_c1 > -0.1: 
    pred_text_c1 = "NEUTRAL ⚖️" 
elif sentiment_score_c1 >= -0.5:
    pred_text_c1 = "SLIGHTLY BEARISH 📉" 
else:                            
    pred_text_c1 = "STRONG BEARISH ⚠️"

# Add override info to prediction text if significant
if "override" in override_note.lower() and "No override" not in override_note:
    pred_text_c1 = f"{pred_text_c1} {override_note}"

# Status tracking (live calculation only — no file persistence)
status_c1 = "Pending"
is_achieved_c1 = False

if nifty_price > 0:
    if sentiment_score_c1 > 0.01 and nifty_price >= target_price_c1:
        is_achieved_c1, status_c1 = True, "Achieved"
    elif sentiment_score_c1 < -0.01 and nifty_price <= target_price_c1:
        is_achieved_c1, status_c1 = True, "Achieved"

# ==============================
# ENHANCED CODE 2 — SIGNAL ENGINE (UNTOUCHED)
# ==============================
def compute_signal_score_enhanced(trigger_pcts, china_pct, sgx_pct, vix_val, usdinr_pct, 
                                 hangseng_pct, nifty_change_pct, pressure_type, momentum_label):
    """Enhanced signal scoring with domestic pressure and momentum"""
    bull_votes, bear_votes = 0, 0
    reasons = []

    # Global triggers
    trigger_positives = sum(1 for x in trigger_pcts if x > 0)
    trigger_negatives = sum(1 for x in trigger_pcts if x < 0)
    trigger_total = len(trigger_pcts)
    
    if trigger_total > 0:
        if trigger_positives >= int(trigger_total * 0.6):
            bull_votes += 1
            reasons.append(f"✅ {trigger_positives}/{trigger_total} global triggers bullish")
        elif trigger_negatives >= int(trigger_total * 0.6):
            bear_votes += 1
            reasons.append(f"🔴 {trigger_negatives}/{trigger_total} global triggers bearish")
        else:
            reasons.append(f"⚪ Mixed trigger signals ({trigger_positives}↑ {trigger_negatives}↓)")

    # China
    if china_pct > 0.3:
        bull_votes += 1
        reasons.append(f"✅ CSI 300 bullish ({china_pct:+.2f}%)")
    elif china_pct < -0.3:
        bear_votes += 1
        reasons.append(f"🔴 CSI 300 bearish ({china_pct:+.2f}%)")
    else:
        reasons.append(f"⚪ CSI 300 flat ({china_pct:+.2f}%)")

    # BankNifty Futures
    if sgx_pct > 0.2:
        bull_votes += 1
        reasons.append(f"✅ BankNifty Fut bullish ({sgx_pct:+.2f}%) — institutional buying")
    elif sgx_pct < -0.2:
        bear_votes += 1
        reasons.append(f"🔴 BankNifty Fut bearish ({sgx_pct:+.2f}%) — institutional selling")
    else:
        reasons.append(f"⚪ BankNifty Fut flat ({sgx_pct:+.2f}%)")

    # VIX
    if vix_val > 0:
        if vix_val < 15:
            bull_votes += 1
            reasons.append(f"✅ VIX calm ({vix_val:.1f}) — Low fear")
        elif vix_val > vix_threshold:
            bear_votes += 1
            reasons.append(f"🔴 VIX elevated ({vix_val:.1f}) — High fear")
        else:
            reasons.append(f"⚪ VIX neutral ({vix_val:.1f})")

    # USD/INR
    if usdinr_pct < -0.1:
        bull_votes += 1
        reasons.append(f"✅ Rupee strengthening ({usdinr_pct:+.2f}%) — FII friendly")
    elif usdinr_pct > 0.2:
        bear_votes += 1
        reasons.append(f"🔴 Rupee weakening ({usdinr_pct:+.2f}%) — FII outflow risk")
    else:
        reasons.append(f"⚪ USD/INR stable ({usdinr_pct:+.2f}%)")

    # DOMESTIC PRESSURE (Heavily weighted)
    if "SELLING" in pressure_type:
        bear_votes += 2
        reasons.append(f"🔴🔴 DOMESTIC SELLING PRESSURE: Nifty {nifty_change_pct:+.2f}%")
    elif "BUYING" in pressure_type:
        bull_votes += 2
        reasons.append(f"✅✅ DOMESTIC BUYING PRESSURE: Nifty {nifty_change_pct:+.2f}%")
    
    # MOMENTUM
    if "STRONG_BEARISH" in momentum_label:
        bear_votes += 2
        reasons.append(f"🔴🔴 STRONG DOWN MOMENTUM: {momentum_pct:+.2f}%")
    elif "BEARISH" in momentum_label:
        bear_votes += 1
        reasons.append(f"🔴 Down momentum: {momentum_pct:+.2f}%")
    elif "STRONG_BULLISH" in momentum_label:
        bull_votes += 2
        reasons.append(f"✅✅ STRONG UP MOMENTUM: {momentum_pct:+.2f}%")
    elif "BULLISH" in momentum_label:
        bull_votes += 1
        reasons.append(f"✅ Up momentum: {momentum_pct:+.2f}%")

    if bull_votes > bear_votes:
        direction = "BULLISH"; score = bull_votes
    elif bear_votes > bull_votes:
        direction = "BEARISH"; score = bear_votes
    else:
        direction = "NEUTRAL"; score = 0

    return direction, score, bull_votes, bear_votes, reasons

direction_c2, score_c2, bull_votes_c2, bear_votes_c2, reasons_c2 = compute_signal_score_enhanced(
    trigger_pcts_c2, china_pct, sgx_pct, vix_value, usdinr_pct, hangseng_pct,
    nifty_change_pct, pressure_type, momentum_label
)

# Determine if signal should fire
signal_fires = (is_after_china and score_c2 >= min_signal_score)

# Handle momentum override for signal firing
if not signal_fires and score_c2 >= min_signal_score - 1:
    if "STRONG" in momentum_label and abs(nifty_change_pct) > 0.5:
        signal_fires = True
        reasons_c2.append("🚀 Momentum override activated signal")

prediction_c2 = direction_c2 if signal_fires else "NEUTRAL"
signal_strength = "STRONG" if score_c2 >= 5 else "MODERATE" if score_c2 >= 3 else "WEAK" if score_c2 >= 1 else "NONE"

# --- Enhanced Target Calculation ---
if nifty_prev_close > 0 and prediction_c2 != "NEUTRAL":
    # Dynamic weighting based on market conditions
    if "SELLING" in pressure_type:
        # During domestic selling, weight domestic factors more
        china_weight = 0.3
        sgx_weight = 0.3
        momentum_weight = 0.4
        blended_pct = (china_pct * china_weight) + (sgx_pct * sgx_weight) + (momentum_pct * momentum_weight)
    elif "BUYING" in pressure_type:
        china_weight = 0.3
        sgx_weight = 0.3
        momentum_weight = 0.4
        blended_pct = (china_pct * china_weight) + (sgx_pct * sgx_weight) + (momentum_pct * momentum_weight)
    else:
        # Normal conditions - balanced approach
        blended_pct = (china_pct * 0.4) + (sgx_pct * 0.4) + (momentum_pct * 0.2)
    
    target_c2 = round(nifty_prev_close * (1 + blended_pct / 100), 2)
    points_move_c2 = round(target_c2 - nifty_prev_close, 2)
    display_move_pct_c2 = round(blended_pct, 2)
else:
    target_c2 = points_move_c2 = display_move_pct_c2 = 0.0

# Stop loss calculation with momentum consideration
if prediction_c2 == "BULLISH" and nifty_price > 0:
    # Dynamic stop based on volatility
    if momentum_label in ["STRONG_BULLISH", "BULLISH"]:
        stop_loss_c2 = round(nifty_price * 0.997, 2)  # Tighter stop in strong momentum
    else:
        stop_loss_c2 = round(nifty_price * 0.995, 2)
elif prediction_c2 == "BEARISH" and nifty_price > 0:
    if momentum_label in ["STRONG_BEARISH", "BEARISH"]:
        stop_loss_c2 = round(nifty_price * 1.003, 2)
    else:
        stop_loss_c2 = round(nifty_price * 1.005, 2)
else:
    stop_loss_c2 = 0.0

# Card styling
if prediction_c2 == "BULLISH" and signal_strength == "STRONG":  
    card_class_c2 = "bullish"
elif prediction_c2 == "BULLISH":                                    
    card_class_c2 = "weak-bullish"
elif prediction_c2 == "BEARISH" and signal_strength == "STRONG":  
    card_class_c2 = "bearish"
elif prediction_c2 == "BEARISH":                                    
    card_class_c2 = "weak-bearish"
else:                                                               
    card_class_c2 = "neutral"

# ==============================
# DIVERGENCE DETECTION (UNTOUCHED)
# ==============================
divergence_detected = False
divergence_msg = ""
divergence_level = "NONE"

if nifty_price > 0 and nifty_prev_close > 0:
    # Calculate divergence severity
    sent_abs = abs(sentiment_score_c1)
    price_abs = abs(nifty_change_pct)
    
    if sentiment_score_c1 > 0.1 and nifty_change_pct < -0.15:
        divergence_detected = True
        divergence_level = "BULLISH_DIVERGENCE"
        severity = min(1.0, abs(nifty_change_pct) / 0.5)
        divergence_msg = (f"⚠️ BULLISH DIVERGENCE: Global weights suggest upward drift "
                          f"(+{raw_sentiment:.2f}% raw → {sentiment_score_c1:+.2f}% adjusted), "
                          f"but Nifty Spot is sliding ({nifty_change_pct:+.2f}% / {nifty_actual_change:+.2f} pts). "
                          f"Domestic selling is overriding global cues. "
                          f"Severity: {severity:.0%}")
    elif sentiment_score_c1 < -0.1 and nifty_change_pct > 0.15:
        divergence_detected = True
        divergence_level = "BEARISH_DIVERGENCE"
        severity = min(1.0, abs(nifty_change_pct) / 0.5)
        divergence_msg = (f"⚠️ BEARISH DIVERGENCE: Global weights negative "
                          f"({raw_sentiment:.2f}% → {sentiment_score_c1:+.2f}%), "
                          f"but Nifty Spot is squeezing up ({nifty_change_pct:+.2f}% / {nifty_actual_change:+.2f} pts). "
                          f"Local institutional buying absorbing pressure. "
                          f"Severity: {severity:.0%}")

box1_badge = "SYNC ACTIVE" if not divergence_detected else "DIVERTED"
box2_badge = (
    "WAITING" if not is_after_china
    else ("🚀 STRONG SIGNAL" if signal_strength == "STRONG"
          else ("📊 MODERATE" if signal_strength == "MODERATE"
                else "⏸️ WEAK / NO CONF"))
)

# ==============================
# (Paper trade engine removed per request — Code 1/2/3 are now
#  display-only predictors with no trade logging or persistence.)
# ==============================

# ==============================
# UI RENDER
# ==============================
st.title("🔮 Nifty Analytics & Strategy Suite — Pro")

# Alerts
if divergence_detected:
    st.markdown(f'<div class="divergence-alert">{divergence_msg}</div>', unsafe_allow_html=True)
if vix_warning:
    st.markdown(f'<div class="vix-alert">{vix_warning}</div>', unsafe_allow_html=True)
if oi_fetch_error:
    st.markdown(
        f'<div class="vix-alert">⚠️ Code 3 (OI Predictor) unavailable: {oi_fetch_error} '
        f'— Code 1 and Code 2 are unaffected.</div>',
        unsafe_allow_html=True
    )

# Enhanced indicator pills with momentum
def pill(label, value, pct, invert=False):
    if pct is None:
        return f'<span class="indicator-pill pill-gray">{label}: —</span>'
    good = pct < 0 if invert else pct > 0
    bad = pct > 0 if invert else pct < 0
    cls = "pill-green" if good else ("pill-red" if bad else "pill-yellow")
    sign = "+" if pct > 0 else ""
    return f'<span class="indicator-pill {cls}">{label}: {value:.2f} ({sign}{pct:.2f}%)</span>'

vix_pill_cls = "pill-green" if vix_value < 15 else ("pill-red" if vix_value > vix_threshold else "pill-yellow")
vix_pill = f'<span class="indicator-pill {vix_pill_cls}">😨 VIX: {vix_value:.1f} [{vix_regime}]</span>' if vix_value > 0 else ""

# Momentum pill
momentum_color = "pill-green" if "BULLISH" in momentum_label else ("pill-red" if "BEARISH" in momentum_label else "pill-yellow")
momentum_pill = f'<span class="indicator-pill {momentum_color}">🚀 {momentum_label}: {momentum_pct:+.2f}%</span>'

pills_html = f"""
<div class="indicator-row">
    {vix_pill}
    {momentum_pill}
    {pill("🏦 BNF", sgx_pct, sgx_pct)}
    {pill("🎁 GIFT", gift_pct, gift_pct)}
    {pill("🇭🇰 HSI", hangseng_pct, hangseng_pct)}
    {pill("💱 USD/INR", usdinr_pct, usdinr_pct, invert=True)}
    {pill("🇺🇸 NDX", nasdaq_pct, nasdaq_pct)}
    {pill("🇨🇳 CSI", china_pct, china_pct)}
</div>
"""
st.markdown(pills_html, unsafe_allow_html=True)

# Domestic Pressure Display
if "SELLING" in pressure_type:
    st.warning(f"🔴 Domestic Selling Pressure Detected (Score: {pressure_score:.1f})")
elif "BUYING" in pressure_type:
    st.success(f"✅ Domestic Buying Pressure Detected (Score: {pressure_score:.1f})")

# ==============================
# CODE 3 — OI based predictor: compute signal only if data fetched OK
# ==============================
oi_signal = None
if oi_raw_data is not None:
    try:
        oi_signal = compute_oi_signal(oi_raw_data["call_put_oi_data_list"], nifty_price)
    except Exception as e:
        oi_fetch_error = f"OI signal computation failed: {e}"
        oi_signal = None

if oi_signal:
    if oi_signal["direction"] == "BULLISH":
        oi_card_class = "bullish" if oi_signal["confidence"] > 70 else "weak-bullish"
    elif oi_signal["direction"] == "BEARISH":
        oi_card_class = "bearish" if oi_signal["confidence"] > 70 else "weak-bearish"
    else:
        oi_card_class = "neutral"
else:
    oi_card_class = "no-data"

top_cols = st.columns(3)

with top_cols[0]:
    st.subheader("📊 Code 1 — Global Weighted Predictor")
    achieved_class = "prediction-achieved" if is_achieved_c1 else ""
    vix_note = f" | VIX dampener: {vix_dampener_val:.0%}" if vix_dampener_val < 1.0 else ""
    st.markdown(f"""
        <div class="prediction-box {achieved_class}" style="min-height: 240px;">
            <div class="status-badge">{box1_badge}</div>
            <p style="margin:0; opacity:0.8; font-size:0.9rem;">
                Weighted Global Sentiment (VIX-adjusted){vix_note}
            </p>
            <h2 style="margin:5px 0; font-size:2rem;">{pred_text_c1} ({sentiment_score_c1:+.2f})</h2>
            <div style="display:flex; justify-content:center; gap:20px; margin-top:12px;
                        font-weight:bold; font-size:1.1rem;">
                <span>🎯 Target: {target_price_c1:,.2f}</span>
                <span>↕️ {pred_change_c1:+.2f} pts</span>
                <span>📊 {pred_pct_c1:+.2f}%</span>
            </div>
            <p style="font-size:0.82rem; margin-top:8px; opacity:0.7;">
                Raw sentiment: {raw_sentiment:+.2f}% | Prev Close: {nifty_prev_close:,.2f} |
                Current: {nifty_price:,.2f} ({nifty_change_pct:+.2f}%)
            </p>
            <div class="confidence-tag">Confidence: {confidence:.1f}%</div>
            <div style="margin-top:10px; font-size:1.1rem;">Status: <b>{status_c1}</b></div>
        </div>
    """, unsafe_allow_html=True)

with top_cols[1]:
    st.subheader("⚖️ Code 2 — Multi-Factor Signal Engine")
    score_bar = "█" * score_c2 + "░" * (5 - score_c2)
    st.markdown(f"""
        <div class="prediction-card {card_class_c2}" style="min-height:240px; padding:20px;">
            <div class="status-badge">{box2_badge}</div>
            <h2 style="margin:0; font-size:2rem;">{prediction_c2} — {signal_strength}</h2>
            <div class="signal-score-bar">
                Signal Score: {score_bar} {score_c2}/5
                &nbsp;|&nbsp; 🟢 {bull_votes_c2} vs 🔴 {bear_votes_c2}
                &nbsp;|&nbsp; 🚀 {momentum_label}
            </div>
            <div class="price-large" style="font-size:2.1rem; margin:6px 0;">
                Target: {target_c2:,.2f}
            </div>
            <div class="move-text" style="font-size:1.1rem; margin-bottom:5px;">
                Move: {points_move_c2:+,.2f} pts ({display_move_pct_c2:+.2f}%)
                &nbsp;[Dynamic Blend: China + BNF + Momentum]
            </div>
            <div class="sl-badge" style="font-size:1rem; padding:4px 15px;">
                STOP LOSS: {stop_loss_c2:,.2f}
            </div>
            <p style="margin-top:10px; font-size:0.82rem; opacity:0.8;">
                Ref Prev Close: {nifty_prev_close:,.2f} | Current: {nifty_price:,.2f}
            </p>
        </div>
    """, unsafe_allow_html=True)

with top_cols[2]:
    st.subheader("📊 Code 3 — OI Open Interest")
    if oi_signal:
        st.markdown(f"""
            <div class="prediction-card {oi_card_class}" style="min-height:240px; padding:20px;">
                <div class="status-badge">OI SIGNAL</div>
                <h2 style="margin:0; font-size:2rem;">{oi_signal['direction']}</h2>
                <div style="margin:6px 0; font-size:1.1rem;">
                    Max Pain: {oi_signal['max_pain']:,.2f} &nbsp;|&nbsp;
                    PCR: {oi_signal['pcr']:.2f}
                </div>
                <div class="price-large" style="font-size:2.1rem; margin:6px 0;">
                    Target: {oi_signal['target']:,.2f}
                </div>
                <div style="font-size:1rem; margin-bottom:5px;">
                    Support: {oi_signal['support']:,.2f} &nbsp;|&nbsp;
                    Resistance: {oi_signal['resistance']:,.2f}
                </div>
                <div class="sl-badge" style="font-size:1rem; padding:4px 15px;">
                    STOP: {oi_signal['stop_loss']:,.2f}
                </div>
                <div style="margin-top:10px; font-size:0.9rem; opacity:0.9;">
                    Votes 🟢 {oi_signal['bull_votes']} vs 🔴 {oi_signal['bear_votes']}
                    &nbsp;·&nbsp; Confidence {oi_signal['confidence']}%
                </div>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
            <div class="prediction-card no-data" style="min-height:240px; padding:20px;">
                <div class="status-badge">NO DATA</div>
                <h2 style="margin:0; font-size:1.6rem;">OI Data Unavailable</h2>
                <p style="font-size:0.9rem; margin-top:10px; opacity:0.9;">
                    {oi_fetch_error or "Waiting for option chain data."}
                </p>
                <p style="font-size:0.8rem; margin-top:12px; opacity:0.75;">
                    Expiry attempted: {expiry_str}
                </p>
            </div>
        """, unsafe_allow_html=True)

with st.expander("🧠 Signal Reasoning — Why this signal fired (or didn't)", expanded=False):
    st.markdown("**Enhanced Code 2 factor-by-factor breakdown:**")
    for r in reasons_c2:
        st.markdown(f"- {r}")
    if pressure_reasons:
        st.markdown("**Domestic Pressure Factors:**")
        for r in pressure_reasons:
            st.markdown(f"- {r}")
    if score_c2 < min_signal_score:
        st.warning(f"Signal score {score_c2}/5 is below your minimum threshold of {min_signal_score}. Signal suppressed.")
    if not is_after_china:
        st.info("China market hasn't closed yet (12:30 PM IST). Code 2 signal will activate after that.")
    if "STRONG" in momentum_label and abs(nifty_change_pct) > 0.5:
        st.success(f"🚀 Strong momentum ({momentum_label}: {momentum_pct:+.2f}%) overrode signal threshold")
    if oi_fetch_error:
        st.markdown("**Code 3 (OI) status:**")
        st.warning(f"⚠️ {oi_fetch_error}")

if volatility_alerts:
    items = "".join([f"<li>{a}</li>" for a in volatility_alerts])
    st.markdown(f'<div class="vix-alert">⚠️ High Volatility Moves:<ul>{items}</ul></div>',
                unsafe_allow_html=True)

st.subheader("📈 Live Tracking — All Instruments")

for i in range(0, len(final_display), 3):
    cols = st.columns(3)
    for j in range(3):
        if i + j < len(final_display):
            item = final_display[i + j]
            s = item["s"]
            close = item["close"]; pct = item["pct"]
            abs_v = item["abs"];   prev = item["prev"]
            if close > 0 or pct != 0:
                color_class = "positive" if pct > 0 else "negative" if pct < 0 else "neutral-color"
                arrow = "▲" if pct > 0 else "▼" if pct < 0 else "—"
                strategy_tag = "STRATEGY COMPONENT" if s["trigger_alignment"] else "REFERENCE ONLY"
                cat_label = s["category"].upper().replace("_", " ")
                with cols[j]:
                    st.markdown(f"""
                    <div class="market-box">
                        <div class="market-header">
                            <span class="market-name">{s['icon']} {s['name']}</span>
                            <span style="color:#888; font-size:0.75rem;">{s['market']} · {cat_label}</span>
                        </div>
                        <div class="price-row">
                            <span class="price-value">{close:,.2f}</span>
                            <span class="change-value {color_class}">{abs_v:+,.2f}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:5px;">
                            <span class="pct-value {color_class}"
                                  style="background:#f8f9fa; padding:2px 8px; border-radius:6px;">
                                {arrow} {abs(pct):.2f}%
                            </span>
                            <span style="font-size:0.75rem; color:#999;">Prev: {prev:,.2f}</span>
                        </div>
                        <div style="margin-top:10px; font-size:0.65rem; color:#bbb;
                                    border-top:1px dashed #eee; padding-top:5px; text-align:center;">
                            {strategy_tag}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Market Status:**")
st.sidebar.markdown(f"- Nifty Change: {nifty_change_pct:+.2f}%")
st.sidebar.markdown(f"- Momentum: {momentum_label}")
st.sidebar.markdown(f"- Pressure: {pressure_type}")
st.sidebar.markdown(f"- Divergence: {divergence_level if divergence_detected else 'NONE'}")
