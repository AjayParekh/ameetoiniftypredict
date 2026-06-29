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
from github import Github, GithubException
import base64
from io import StringIO
import warnings
warnings.filterwarnings('ignore')
import requests
import json
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

access_token = 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIxMDM2NjciLCJqdGkiOiI2OWQyMzJlMWNjZDUyZDRjZDQzMzc5NjYiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc3NTM4MzI2NSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODA2OTYyNDAwfQ.VFRZ5NP87NM1Vyn4-bCB2FAvanu4wsueNHo_POQtPv8'

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


def fetch_upstox_oi_data():
    # Auto date (today, IST) and auto weekly expiry (next Tuesday, IST)
    ist_now = datetime.now(pytz.timezone("Asia/Kolkata"))
    today_str = ist_now.strftime('%Y-%m-%d')

    days_until_tuesday = (1 - ist_now.weekday()) % 7  # Monday=0 ... Tuesday=1
    expiry_date = ist_now + dt_mod.timedelta(days=days_until_tuesday)
    expiry_str = expiry_date.strftime('%Y-%m-%d')

    url = 'https://api.upstox.com/v2/market/oi'
    params = {
        'instrument_key': 'NSE_INDEX|Nifty 50',
        'expiry': expiry_str,
        'date': today_str
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token  # Replace with your actual access token
    }

    upstoxResponse = requests.get(url, params=params, headers=headers)
    print("----------upstoxResponse ---------", upstoxResponse)

    upstoxResponse = json.loads(upstoxResponse.text)
    return upstoxResponse
upstoxResponse = fetch_upstox_oi_data()
print("----------upstoxResponse ---------", isinstance(upstoxResponse, dict), upstoxResponse)
data = upstoxResponse["data"]



st.write(f"Status: {upstoxResponse['status']}")
st.write(f"Total Puts: {data['total_puts']}")
st.write(f"Total Calls: {data['total_calls']}")
st.write(f"Spot Closing Price: {data['spot_closing_price']}")
st.write(f"Expiry: {data['expiry']}")

st.subheader("OI by Strike Price")

# Display as a table
oi_rows = [
    {
        "Strike Price": int(item["strike_price"]),
        "Call OI": item["call_oi"],
        "Put OI": item["put_oi"],
        "HIGH OI": "HIGH PUT" if item["put_oi"] > item["call_oi"] else "HIGH CALL",
        "OI Difference": abs(item["put_oi"] - item["call_oi"]),
    }
    for item in data["call_put_oi_data_list"]
]

top_20 = pd.DataFrame(oi_rows).sort_values(
    by="OI Difference",
    ascending=False
).head(20).reset_index(drop=True)

# IMPROVED HIGHLIGHT: golden background for top 5
def highlight_top5(row):
    if row.name < 5:
        return ["background-color: #ffd700; font-weight: bold; color: #000000;"] * len(row)
    return [""] * len(row)

st.dataframe(top_20.style.apply(highlight_top5, axis=1))

# ==============================
# GLOBAL CONFIG & TIMING
# ==============================
st_autorefresh(interval=15_000, key="global_sync_refresh")
ist = pytz.timezone("Asia/Kolkata")
now = datetime.now(ist)
today = now.strftime("%Y-%m-%d")

CHINA_CLOSE_TIME = time(12, 30)
is_after_china = now.time() >= CHINA_CLOSE_TIME
trade_file = "Paper_Trades.csv"
excel_file = "Market_Data.xlsx"

# ==============================
# GITHUB API CONFIGURATION
# ==============================
# GITHUB_TOKEN = st.secrets.get("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", None)
GITHUB_TOKEN = "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"
REPO_NAME = "AjayParekh/niftypredictiondeepseekversion1"
FILE_PATH = "Paper_Trades.csv"

def save_to_github(dataframe, filename=FILE_PATH, repo_name=REPO_NAME, token=GITHUB_TOKEN):
    if not token:
        dataframe.to_csv(filename, index=False)
        return
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        csv_content = dataframe.to_csv(index=False)
        try:
            contents = repo.get_contents(filename)
            repo.update_file(contents.path, f"Update trade log {datetime.now().strftime('%Y-%m-%d %H:%M')}", csv_content, contents.sha)
        except GithubException as e:
            if e.status == 404:
                repo.create_file(filename, "Initial trade log commit", csv_content)
            else:
                raise e
    except Exception as e:
        st.sidebar.error(f"GitHub Sync Failed: {e}")

def load_from_github(filename=FILE_PATH, repo_name=REPO_NAME, token=GITHUB_TOKEN):
    if not token:
        if os.path.exists(filename):
            return pd.read_csv(filename)
        return pd.DataFrame()
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(filename)
        decoded = base64.b64decode(contents.content).decode('utf-8')
        return pd.read_csv(StringIO(decoded))
    except Exception:
        if os.path.exists(filename):
            return pd.read_csv(filename)
        return pd.DataFrame()

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

    if st.sidebar.button("🗑️ Reset All Logs"):
        if os.path.exists(trade_file): os.remove(trade_file)
        save_to_github(pd.DataFrame())
        st.rerun()

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

# Configure connection pooling
retry_strategy = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504]
)
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

def fetch_master_data(symbol_dict):
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

# ==============================
# ENHANCED PREDICTION FUNCTIONS
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
# NEW CODE 3 – OI BASED PREDICTOR
# ==============================

def compute_max_pain(oi_data, spot):
    strikes = [item["strike_price"] for item in oi_data]
    best_strike = strikes[0]
    min_pain = float('inf')
    for s in strikes:
        total = 0.0
        for item in oi_data:
            st = item["strike_price"]
            call_oi = item["call_oi"]
            put_oi = item["put_oi"]
            # intrinsic value at strike s
            total += call_oi * max(s - st, 0) + put_oi * max(st - s, 0)
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
# ENHANCED CODE 1 — CALCULATIONS
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

# Status tracking
status_c1 = "Pending"
is_achieved_c1 = False
if os.path.exists(excel_file):
    try:
        hdf = pd.read_excel(excel_file)
        hits = hdf[(hdf["Date"] == today) &
                   (hdf["Instrument"] == "NIFTY 50") &
                   (hdf["Status"] == "Achieved")]
        if not hits.empty:
            is_achieved_c1, status_c1 = True, "Achieved"
    except: pass

if not is_achieved_c1 and nifty_price > 0:
    if sentiment_score_c1 > 0.01 and nifty_price >= target_price_c1:
        is_achieved_c1, status_c1 = True, "Achieved"
    elif sentiment_score_c1 < -0.01 and nifty_price <= target_price_c1:
        is_achieved_c1, status_c1 = True, "Achieved"

# ==============================
# ENHANCED CODE 2 — SIGNAL ENGINE
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
# DIVERGENCE DETECTION (ENHANCED)
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
# PAPER TRADE ENGINE (GITHUB DRIVEN)
# ==============================
if now.time().hour == 14 and now.time().minute == 0 and prediction_c2 != "NEUTRAL":
    strike = (round(nifty_price / 50) * 50) + (-100 if prediction_c2 == "BULLISH" else 100)
    opt_type = "CE" if prediction_c2 == "BULLISH" else "PE"
    trade_row = pd.DataFrame({
        "Date": [now.strftime("%Y-%m-%d")], "Time": ["14:00"],
        "Signal": [prediction_c2], "Strength": [signal_strength],
        "Score": [f"{score_c2}/5"],
        "Strike": [f"{strike} {opt_type}"], "Entry": [nifty_price],
        "Exit": [0.0], "PnL": [0.0], "Status": ["OPEN"],
        "Expected_Move_Pts": [round(points_move_c2, 2)],
        "Final_Capture_Pts": [0.0],
        "Momentum": [momentum_label],
        "Divergence": [divergence_level]
    })
    
    trades = load_from_github()
    if trades.empty:
        save_to_github(trade_row)
        trade_row.to_csv(trade_file, index=False)
    else:
        if now.strftime("%Y-%m-%d") not in trades["Date"].values:
            updated_trades = pd.concat([trades, trade_row], ignore_index=True)
            save_to_github(updated_trades)
            updated_trades.to_csv(trade_file, index=False)

if now.time() >= time(15, 30):
    trades = load_from_github()
    if not trades.empty:
        if (trades.iloc[-1]["Status"] == "OPEN" and
                trades.iloc[-1]["Date"] == now.strftime("%Y-%m-%d")):
            entry_val = trades.iloc[-1]["Entry"]
            sig_val = trades.iloc[-1]["Signal"]
            pnl_val = (nifty_price - entry_val) if sig_val == "BULLISH" else (entry_val - nifty_price)
            trades.loc[trades.index[-1],
                       ["Exit", "PnL", "Status", "Final_Capture_Pts"]] = [
                           nifty_price, round(pnl_val, 2), "CLOSED", round(pnl_val, 2)]
            save_to_github(trades)
            trades.to_csv(trade_file, index=False)

# ==============================
# UI RENDER
# ==============================
st.title("🔮 Nifty Analytics & Strategy Suite — Pro")

# Alerts
if divergence_detected:
    st.markdown(f'<div class="divergence-alert">{divergence_msg}</div>', unsafe_allow_html=True)
if vix_warning:
    st.markdown(f'<div class="vix-alert">{vix_warning}</div>', unsafe_allow_html=True)

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
# CODE 3 – OI BASED PREDICTOR (NEW)
# ==============================
oi_signal = compute_oi_signal(data["call_put_oi_data_list"], nifty_price)

# Determine card styling for OI
if oi_signal["direction"] == "BULLISH":
    oi_card_class = "bullish" if oi_signal["confidence"] > 70 else "weak-bullish"
elif oi_signal["direction"] == "BEARISH":
    oi_card_class = "bearish" if oi_signal["confidence"] > 70 else "weak-bearish"
else:
    oi_card_class = "neutral"

# NOW CREATE THREE COLUMNS
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

# ---- Paper Trade Log Display ----
df_trades = load_from_github()
if not df_trades.empty:
    st.write("---")
    st.subheader("📦 Position Log & Variance Status")
    st.dataframe(df_trades.tail(5), hide_index=True, use_container_width=True)

    if len(df_trades) > 1:
        closed = df_trades[df_trades["Status"] == "CLOSED"]
        if not closed.empty:
            wins = (closed["PnL"] > 0).sum()
            total = len(closed)
            win_pct = wins / total * 100 if total > 0 else 0
            avg_pnl = closed["PnL"].mean() if total > 0 else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("Win Rate", f"{win_pct:.1f}%")
            c2.metric("Avg P&L", f"{avg_pnl:+.1f} pts")
            c3.metric("Trades", total)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Market Status:**")
st.sidebar.markdown(f"- Nifty Change: {nifty_change_pct:+.2f}%")
st.sidebar.markdown(f"- Momentum: {momentum_label}")
st.sidebar.markdown(f"- Pressure: {pressure_type}")
st.sidebar.markdown(f"- Divergence: {divergence_level if divergence_detected else 'NONE'}")

def fetch_news_data():
    """
    Fetch news data from Upstox API and return the JSON response.
    """
    url = 'https://api.upstox.com/v2/news'
    params = {
        'category': 'instrument_keys',
        'instrument_keys': 'NSE_EQ|INE040H01021,NSE_EQ|INE002A01018'
    }
    headers = {
        'Accept': 'application/json',
        'Authorization': access_token
    }

    response = requests.get(url, params=params, headers=headers)

    print(isinstance(response.json(), dict), response.json())
    parse_news_data(response.json()) if response.json().get("status") == "success" else None


def fetch_futures_data():
    """
    Fetch futures data from Upstox API and return the JSON response.
    """

    url = 'https://api.upstox.com/v2/market/smartlist/futures'
    params = {
        'asset_type': 'INDEX',
        'category': 'TOP_TRADED',
        'page_number': 1,
        'page_size': 20,
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': access_token  # Ensure you have a valid access token
    }

    response = requests.get(url, params=params, headers=headers)

    # Allow user to upload a custom JSON (optional)
    uploaded_file = json.loads(response.text)
    # print("------fetch_futures_data------", uploaded_file)
    if uploaded_file is not None:
        data = uploaded_file
    else:
        data = json_data
        
    return data


def parse_futures_flow(data):
    """
    Parses the screener JSON using raw absolute values for weighting and filtering.
    Returns a Macro Bearish/Bullish Score (-1 to +1).
    """
    smartlist = data['data']['smartlist']
    
    # We will build a weighted average based on the absolute traded value
    rows = []
    weighted_score = 0.0
    total_value_weight = 0.0
    
    for item in smartlist:
        # Extract raw values
        instrument_key = item['instrument_key']
        current_value = item['metric']['current']
        prev_value = item['metric']['previous']
        change_abs = item['metric']['change_abs']  # Absolute change in turnover
        change_pct = item['metric']['change_pct']  # Percentage change
        
        price_change = item['price']['change_pct']
        
        # 1. FILTER: Ignore instruments with tiny turnover (< 10 Crore / 100M) to avoid noise
        if current_value < 100_000_000:  # Less than 10 Crore INR
            continue  
        
        # 2. Calculate raw score for this instrument (-1 to 1)
        score = 0.0
        
        # Logic using ABSOLUTE change (change_abs) AND percentage
        # If absolute change is > 1 Billion (1,000,000,000) and price is falling hard
        if change_abs > 1_000_000_000 and price_change < -0.3:
            # Massive absolute selling pressure
            score = -0.9
        elif change_abs > 1_000_000_000 and price_change > 0.3:
            # Massive absolute buying pressure
            score = 0.9
        elif change_pct > 30 and price_change < -0.3:
            # High percentage surge but lower absolute value -> still bearish, but less
            score = -0.6
        elif change_pct > 10 and price_change < -0.5:
            score = -0.4
        elif change_pct > 10 and price_change > 0.5:
            score = 0.4
        else:
            # For small absolute changes, the signal is weak
            score = 0.0
            
        # 3. WEIGHT by absolute current value (Bigger contracts get more vote)
        # This ensures Nifty (132B) weighs more than the small third contract (5.7B)
        weight = current_value / 1_000_000_000  # Scale to billions for manageable numbers
        
        weighted_score += score * weight
        total_value_weight += weight

        # print(f"------parse_futures_flow----{instrument_key}------", {score, weight, weighted_score, total_value_weight, current_value, prev_value, change_abs, change_pct, price_change})
        rows.append({
            "instrument_key": instrument_key,
            "score": score,
            "weight": weight,
            "weighted_score": score * weight,
            "total_value_weight": total_value_weight,
            "current_value": current_value,
            "prev_value": prev_value,
            "change_abs": change_abs,
            "change_pct": change_pct,
            "price_change": price_change,
        })

    df = pd.DataFrame(rows)
        
    # Normalize the weighted score
    if total_value_weight == 0:
        return 0.0
        
    final_score = weighted_score / total_value_weight

    final_score = max(-1, min(1, final_score))  # Clamp to [-1, 1]
    st.subheader(f"OI Flow Details {final_score:.2f}")
    st.markdown("**Weighted Macro Score (-1 to +1)**: Based on absolute turnover and price change across top traded futures.")
    if final_score > 0:
        indicator = "Bullish"
    elif final_score < 0:
        indicator = "Bearish"
    else:
        indicator = "Sideways"

    st.write(f"Market Bias: {indicator}")
    # st.text(f"Weighted Score: {"Bullish" if final_score >= 0 else "Bearish"} ({final_score:.2f})")
    st.dataframe(df)
    return final_score

def parse_news_data(data):
    """
    Parses the news JSON and returns a list of news items with relevant details.
    """
    
    # Flatten news items
    rows = []
    for symbol, articles in data["data"].items():
        for article in articles:
            published_time = article.get("published_time")
            published_str = None
            if published_time:
                published_str = datetime.fromtimestamp(published_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
            rows.append({
                "Symbol": symbol,
                "Headline": article.get("heading", ""),
                "Summary": article.get("summary", ""),
                "Link": article.get("article_link", ""),
                "Published": published_str,
            })

    # Create DataFrame
    df = pd.DataFrame(rows)

    st.title("News Table")
    st.write("Latest news from futures_data.json")

    # Display as a table
    st.dataframe(df)

# Example usage
json_data = {
    "status": "success",
    "data": {
        "asset_type": "INDEX",
        "category": "TOP_TRADED",
        "time_stamp": 1780045636752,
        "metric_key": "total_traded_value",
        "smartlist": [
            {"instrument_key": "NSE_FO|62329", "price": {"current": 23867.0, "close_price": 23996.7, "change_abs": -129.70, "change_pct": -0.54}, "metric": {"current": 132094775540, "previous": 69295823909, "change_abs": 62798951631.00, "change_pct": 90.62}},
            {"instrument_key": "NSE_FO|62326", "price": {"current": 54970.0, "close_price": 55207.0, "change_abs": -237.00, "change_pct": -0.43}, "metric": {"current": 45591018600, "previous": 43236361746, "change_abs": 2354656854.00, "change_pct": 5.45}},
            {"instrument_key": "NSE_FO|61093", "price": {"current": 23977.8, "close_price": 24089.6, "change_abs": -111.80, "change_pct": -0.46}, "metric": {"current": 5752633887, "previous": 4917306790.5, "change_abs": 835327096.50, "change_pct": 16.99}}
        ],
        "page_number": 1, "page_size": 3, "total_pages": 9
    }
}

fetched_data = fetch_futures_data()
fetched_news = fetch_news_data()

macro_score = parse_futures_flow(fetched_data)
# print(f"Macro Flow Score: {macro_score}")  # Output: -0.8 (Extremely Bearish)
